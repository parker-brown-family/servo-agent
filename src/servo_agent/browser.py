"""ServoBrowser — drive Servo over its built-in W3C WebDriver server.

Works with Servo's official builds (`servo-agent install-servo`) and with any
servoshell built from source. Owns one `servoshell` process + one WebDriver
session, launched lazily. Wraps
the W3C protocol in agent-shaped primitives (navigate, read, find, click,
type, extract, wait, scroll) plus the lifecycle plumbing. The MCP server and
the examples are thin layers over this class.
"""
from __future__ import annotations

import base64
import os
import re
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import requests

from .engines import newest_installed

# W3C element reference key (returned by find, accepted by /element/{id}).
W3C_ELEMENT_KEY = "element-6066-11e4-a52e-4f735466cecf"

# Injected once per document on navigate: a best-effort JS error collector that
# stashes window 'error' / 'unhandledrejection' events on window.__servoAgentErrors
# so get_errors() can read them back. Idempotent (no-ops if already installed).
_ERROR_COLLECTOR_JS = r"""
(function () {
  if (window.__servoAgentErrors) return 'already';
  var store = (window.__servoAgentErrors = []);
  var push = function (rec) { try { if (store.length < 500) store.push(rec); } catch (_) {} };
  window.addEventListener('error', function (e) {
    if (e && typeof e.message === 'string' && e.message) {
      push({ type: 'error', message: String(e.message),
             source: String(e.filename || ''),
             line: e.lineno || 0, col: e.colno || 0 });
    } else if (e && e.target && (e.target.src || e.target.href)) {
      var u = String(e.target.src || e.target.href);
      push({ type: 'resource', message: 'failed to load ' + u, source: u, line: 0, col: 0 });
    }
  }, true);
  window.addEventListener('unhandledrejection', function (e) {
    var r = e && e.reason;
    var msg = (r && r.message) ? r.message : (r != null ? r : 'unhandled rejection');
    push({ type: 'unhandledrejection', message: String(msg), source: '', line: 0, col: 0 });
  });
  return 'installed';
})();
return 'ok';
"""


def find_servoshell() -> Path | None:
    """Locate servoshell, first match wins.

    $SERVOSHELL, then `servoshell` on PATH, then the newest engine installed by
    `servo-agent install-servo`, then a `servo/` directory beside or above this
    package (an unpacked release or a source build).
    """
    env = os.environ.get("SERVOSHELL")
    if env and Path(env).exists():
        return Path(env)
    on_path = shutil.which("servoshell")
    if on_path:
        return Path(on_path)
    installed = newest_installed()
    if installed:
        return installed
    return _servoshell_beside(Path(__file__).resolve())


def _servoshell_beside(start: Path) -> Path | None:
    """The nearest `servo/` engine beside `start` or above it.

    That is an unpacked release archive (`servo/servoshell`) or a source build
    (`servo/target/{release,debug}/servoshell`, release first because it is the
    faster engine). From a source checkout this finds the sibling of this repo
    (…/servo-agent → …/servo). When servo-agent is installed into another
    project's virtualenv (servo-reader does this), the package lives under that
    project's `.venv`, so walking up finds a `servo/` beside that project instead.
    """
    for parent in start.parents:
        for cand in (parent / "servo" / "servoshell",
                     parent / "servo" / "target" / "release" / "servoshell",
                     parent / "servo" / "target" / "debug" / "servoshell"):
            if cand.is_file():
                return cand
    return None


class ServoNotBuilt(RuntimeError):
    """Raised when no servoshell binary can be found."""


class ServoBrowser:
    """One servoshell process + one WebDriver session. Lazy-started, auto-cleaned."""

    # Upper bound for a full_page screenshot window height (px), so a runaway
    # document can't ask the engine for an enormous surface.
    _MAX_FULLPAGE_PX = 20000

    # How long a committed page may sit `interactive` with an unchanged DOM
    # before navigate() treats it as loaded (see navigate). Half a second is the
    # quiet a `complete` page gets from wait_for_load. It was 2 s, which every
    # open of a page that never fires `load` paid in full (issue #11: servo.org
    # is readable at about 0.6 s on Servo 0.7 and open_url took 2.9 s).
    _INTERACTIVE_QUIET_S = 0.5
    # wait_for_load() is the caller asking for a settled page, so a page stuck at
    # `interactive` gets longer there before it counts as settled.
    _SETTLE_INTERACTIVE_QUIET_S = 2.0

    # How long shutdown() waits for servoshell to exit, after Servo's shutdown
    # route and again after SIGTERM, before killing it. Servo 0.7 catches SIGTERM
    # and SIGINT and then never exits when headless (measured 2026-10-22: still
    # running 12 s later, where the June 2026 build exited in 0.12 s).
    _TERM_GRACE_S = 1.0

    # Above this PSS, navigate() restarts the engine it owns before opening the
    # next page. Servo's memory climbs with every page in one window: 0.7.0 went
    # from 334 MB to 5,279 MB over 100 navigations (2026-10-22), and closing the
    # window gave back only a third of it, so only a fresh process bounds it.
    # The check comes before a page and one page can add more: the largest jump
    # measured was 262 MB (Wikipedia), so 700 keeps the peak under 1 GB.
    # $SERVO_AGENT_MEMORY_CAP_MB overrides it; 0 turns the restarts off.
    DEFAULT_MEMORY_CAP_MB = 700

    def __init__(self, binary: str | Path | None = None, headless: bool = True,
                 memory_cap_mb: int | None = None) -> None:
        self.binary = Path(binary) if binary else find_servoshell()
        self.headless = headless
        self.proc: subprocess.Popen | None = None
        self.port: int | None = None
        self.base: str | None = None
        self.sid: str | None = None
        self.external = False   # True when attached to an externally-run engine
        if memory_cap_mb is None:
            memory_cap_mb = int(os.environ.get("SERVO_AGENT_MEMORY_CAP_MB")
                                or self.DEFAULT_MEMORY_CAP_MB)
        self.memory_cap_mb = memory_cap_mb
        # What the last navigate() restarted, or None if it restarted nothing.
        self.last_restart: dict[str, Any] | None = None
        # The last screenshot's size, and for a full page whether it was cut short.
        self.last_screenshot: dict[str, Any] | None = None
        # "0.7.0" from the session's user agent; None until a session exists or if
        # the engine does not say (Servo's own browserVersion is a fixed "0.0.1").
        self.engine_version: str | None = None

    # -- context manager ---------------------------------------------------- #
    def __enter__(self) -> ServoBrowser:
        self.ensure_started()
        return self

    def __exit__(self, *exc: object) -> None:
        self.shutdown()

    # -- lifecycle ---------------------------------------------------------- #
    @staticmethod
    def _free_port() -> int:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def ensure_started(self) -> None:
        if self.sid:
            # A cached session is only usable while its engine is alive. When we
            # OWN the servoshell process and it has exited (crashed, OOM-killed,
            # or the binary rebuilt mid-session), the WebDriver port is dead and
            # every command would wedge on "connection refused" forever. Drop the
            # stale session and fall through to respawn. An `external` engine
            # (attached, not owned by us) has no proc to poll, so trust its sid.
            if self.external or (self.proc and self.proc.poll() is None):
                return
            self.sid = None
            self.proc = None
        external = os.environ.get("SERVO_WEBDRIVER")
        if external:
            # Attach to an already-running servoshell WebDriver (e.g. a spin-managed
            # shared engine) instead of spawning our own. We own only the session.
            base = external if external.startswith("http") else f"http://{external}"
            self.base = base.rstrip("/")
            self.external = True
        else:
            if not self.binary or not Path(self.binary).exists():
                raise ServoNotBuilt(
                    "servoshell not found. Install Servo's official build with "
                    "`servo-agent install-servo`, set $SERVOSHELL to a servoshell binary, "
                    "or point $SERVO_WEBDRIVER at a running engine."
                )
            self.port = self._free_port()
            self.base = f"http://127.0.0.1:{self.port}"
            # --temporary-storage gives every engine a profile of its own that dies
            # with it. Without it, every servoshell on the machine shares cookies,
            # localStorage and caches in ~/.config/servo/default.
            # --screen-size: a headless window can grow to twice the screen, and the
            # default screen is twice the 1024x740 window, so a full-page shot was
            # cut at 2,960 px without a word. This screen lets it reach
            # _MAX_FULLPAGE_PX (measured 2026-10-22: a 6,040 px page came back whole).
            cmd = [str(self.binary), "--temporary-storage",
                   f"--screen-size=2048x{self._MAX_FULLPAGE_PX // 2}",
                   "--webdriver", str(self.port), "about:blank"]
            if self.headless:
                cmd.insert(1, "--headless")
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            self._wait_port(self.port)
        caps = {"capabilities": {"alwaysMatch": {"browserName": "servo"}}}
        session = self._raw("POST", "/session", caps)
        self.sid = session["sessionId"]
        agent = (session.get("capabilities") or {}).get("userAgent") or ""
        found = re.search(r"\bServo/(\S+)", agent)
        self.engine_version = found[1] if found else None

    @staticmethod
    def _wait_port(port: int, timeout: float = 30.0) -> None:
        # servoshell 0.7 listens about 0.2-0.4 s after launch; a fine poll keeps
        # that from rounding up to a whole poll interval on every (re)start.
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    return
            except OSError:
                time.sleep(0.05)
        raise RuntimeError(f"WebDriver port {port} never came up")

    def memory_mb(self) -> int | None:
        """The owned engine's PSS in MB, read from /proc.

        None when that is unknown: no engine running, an attached engine this
        process does not own, or a system without /proc/<pid>/smaps_rollup.
        """
        if self.external or not self.proc or self.proc.poll() is not None:
            return None
        try:
            with open(f"/proc/{self.proc.pid}/smaps_rollup") as f:
                for line in f:
                    if line.startswith("Pss:"):
                        return round(int(line.split()[1]) / 1024)
        except (OSError, ValueError):
            return None
        return None

    def _restart_if_over_cap(self) -> None:
        """Before a navigation, replace an engine whose memory passed the cap."""
        self.last_restart = None
        if not self.memory_cap_mb:
            return
        used = self.memory_mb()
        if used is None or used <= self.memory_cap_mb:
            return
        self.shutdown()
        self.ensure_started()
        self.last_restart = {
            "reason": f"the engine used {used} MB, over the {self.memory_cap_mb} MB cap",
            "pss_mb": used, "cap_mb": self.memory_cap_mb,
            "lost": "cookies, history and the page that was open",
        }

    def shutdown(self) -> None:
        """End the session; stop the engine too if this browser started it.

        An engine we own is asked to quit through Servo's own WebDriver route,
        `DELETE /session/{id}/servo/shutdown`, which upstream's test harness uses
        too: Servo 0.7 exits on it in about 0.2 s (measured 2026-10-22). Signals
        are the fallback: SIGTERM, then a kill once _TERM_GRACE_S has passed.
        An attached engine belongs to someone else, so only its session ends.
        """
        owned = self.proc is not None and self.proc.poll() is None
        if owned and self.base:
            try:
                requests.delete(f"{self.base}/session/{self.sid or 'none'}/servo/shutdown",
                                timeout=5)
                self.proc.wait(timeout=self._TERM_GRACE_S)
            except (requests.RequestException, subprocess.TimeoutExpired):
                pass  # an engine without the route, or one that hung: signals below
        elif self.sid and self.base:
            try:
                self._raw("DELETE", f"/session/{self.sid}")
            except Exception:  # noqa: BLE001 — best effort
                pass
        self.sid = None
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=self._TERM_GRACE_S)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        self.proc = None

    # -- raw W3C transport -------------------------------------------------- #
    def _raw(self, method: str, path: str, body: dict | None = None) -> Any:
        # W3C WebDriver parses every POST body as JSON and requires an object, so
        # commands that take no parameters (element click, back, refresh) must
        # still send `{}`. Servo enforces this: an empty body is a 400.
        if body is None and method == "POST":
            body = {}
        resp = requests.request(method, f"{self.base}{path}", json=body, timeout=60)
        data = resp.json()
        if resp.status_code != 200:
            err = data.get("value", {})
            raise RuntimeError(
                f"{method} {path} -> {resp.status_code} "
                f"{err.get('error', '?')}: {err.get('message', '')[:300]}"
            )
        return data.get("value", data)

    def _cmd(self, method: str, path: str, body: dict | None = None) -> Any:
        self.ensure_started()
        return self._raw(method, f"/session/{self.sid}{path}", body)

    # -- navigation --------------------------------------------------------- #
    def navigate(self, url: str, timeout: float = 20.0, settle: bool = False) -> str:
        """Navigate, and wait at most `timeout` seconds for the NEW document.

        Servo's WebDriver `POST /url` holds the session until the load completes,
        and a page that never reaches `complete` (a preload or analytics request
        that never settles) holds it for the engine's page-load timeout of five
        minutes. So navigation starts from script with `window.location.assign`,
        which returns at once, and the wait below is ours and bounded.

        The URL cannot say when the new document has arrived: re-opening the
        page you are on leaves it unchanged, and the old document still reports
        `complete`. So the current document is marked with a token first, and
        the navigation has committed once the live document no longer carries
        it. A fragment-only change (same page, new `#anchor`) never replaces the
        document, so it counts as committed at once.

        Returns the new document's readyState: `complete`; `interactive` once
        its DOM has been still for _INTERACTIVE_QUIET_S, because Servo leaves
        many real pages `interactive` for good (a web font or beacon that never
        finishes) and waiting there for `complete` only burns the timeout; or
        whatever state the page reached by the deadline. Raises TimeoutError
        if no new document arrived at all. On commit a best-effort
        JS error collector is injected (see get_errors). When `settle` is true we
        additionally wait_for_load() so SPAs that mutate the DOM after
        readyState=complete (e.g. hydration) have settled before we return —
        handy when the immediate next read is <title>/content.

        An engine this browser owns is first restarted if its memory passed
        `memory_cap_mb`; `last_restart` then says so (see _restart_if_over_cap).
        """
        self._restart_if_over_cap()
        token = uuid.uuid4().hex
        # The page's own URL parser decides whether this is a fragment-only
        # change, so host case, default ports and relative URLs compare the way
        # the navigation will treat them.
        prev, fragment_only = self.eval_js(
            "document.__servoAgentNav = arguments[0];"
            "let fragmentOnly = false;"
            "try {"
            "  const to = new URL(arguments[1], document.URL), at = new URL(document.URL);"
            "  fragmentOnly = to.hash !== '' && to.href.split('#')[0] === at.href.split('#')[0];"
            "} catch (_) {}"
            "return [document.URL, fragmentOnly];",
            [token, url],
        )
        self.eval_js("window.location.assign(arguments[0]); return true", [url])
        deadline = time.monotonic() + timeout
        state = "unknown"
        committed = False
        last_error: RuntimeError | None = None
        shape: list | None = None
        shape_since = 0.0
        while True:
            try:
                same_document, state, *now_shape = self.eval_js(
                    "return [document.__servoAgentNav === arguments[0], "
                    "document.readyState, document.getElementsByTagName('*').length, "
                    "document.body ? document.body.scrollHeight : 0]",
                    [token],
                )
                last_error = None
            except RuntimeError as exc:
                # The old document can go away mid-command while the new one
                # commits. That is the navigation happening; look again.
                same_document, state, now_shape, last_error = True, "unknown", None, exc
            # Once a new document has been seen, a later failed poll does not
            # undo that: the navigation committed.
            committed = committed or fragment_only or not same_document
            now = time.monotonic()
            if committed and state == "complete":
                break
            if committed and state == "interactive":
                if now_shape != shape:
                    shape, shape_since = now_shape, now
                elif now - shape_since >= self._INTERACTIVE_QUIET_S:
                    break
            else:
                shape = None
            if now >= deadline:
                break
            time.sleep(0.2)
        if not committed:
            raise TimeoutError(
                f"navigation to {url!r} did not commit within {timeout}s (still on {prev!r})"
            ) from last_error
        self._install_error_collector()
        if settle:
            remaining = max(1.0, deadline - time.monotonic())
            state = self.wait_for_load(timeout=remaining)
        return state

    def _install_error_collector(self) -> None:
        """Inject the JS error collector into the current document (idempotent)."""
        try:
            self.eval_js(_ERROR_COLLECTOR_JS)
        except Exception:  # noqa: BLE001 — diagnostics are best-effort, never fatal
            pass

    def wait_for_load(self, timeout: float = 15.0, quiet: float = 0.5,
                      poll: float = 0.1) -> str:
        """Wait for the page to *settle*, not merely reach readyState=complete.

        Polls until `document.readyState === 'complete'` AND the DOM has been
        quiescent — no childList mutations and a stable element count / scroll
        height — for `quiet` seconds (default ~500ms). This catches SPA
        frameworks that finish hydrating after the initial load event, which is
        when reading <title>/content too early returns the pre-hydration shell.

        Returns the final readyState ('complete' on success). A page that is
        still `interactive` but whose DOM has not changed for
        _SETTLE_INTERACTIVE_QUIET_S returns 'interactive' then, rather than waiting
        out the timeout for a load that may never finish. Falls back to the
        last observed readyState if `timeout` elapses first (does not raise, so
        a slow page still yields whatever has rendered).
        """
        deadline = time.monotonic() + timeout
        # Sample (elementCount, scrollHeight); DOM is "quiet" when this is stable.
        sig_js = (
            "return [document.getElementsByTagName('*').length, "
            "(document.body ? document.body.scrollHeight : 0)]"
        )
        last_sig: Any = None
        quiet_since: float | None = None
        state = "unknown"
        while time.monotonic() < deadline:
            state = self.eval_js("return document.readyState") or "unknown"
            sig = self.eval_js(sig_js)
            now = time.monotonic()
            settling = state in ("complete", "interactive")
            if settling and sig == last_sig:
                needed = quiet if state == "complete" else self._SETTLE_INTERACTIVE_QUIET_S
                if quiet_since is None:
                    quiet_since = now
                elif now - quiet_since >= needed:
                    return state
            else:
                quiet_since = now if settling else None
            last_sig = sig
            time.sleep(poll)
        return state

    def title(self) -> str:
        return self._cmd("GET", "/title")

    def current_url(self) -> str:
        return self._cmd("GET", "/url")

    def reload(self) -> None:
        self._cmd("POST", "/refresh")

    def back(self) -> None:
        self._cmd("POST", "/back")

    # -- scripting ---------------------------------------------------------- #
    def eval_js(self, script: str, args: list | None = None) -> Any:
        return self._cmd("POST", "/execute/sync", {"script": script, "args": args or []})

    def outer_html(self) -> str:
        return self.eval_js("return document.documentElement.outerHTML")

    def read_html(self) -> str:
        """outerHTML with relative hrefs/srcs absolutized, so distilled links work."""
        return self.eval_js(
            "for (const a of document.querySelectorAll('a[href]')) "
            "a.setAttribute('href', a.href);"
            "for (const e of document.querySelectorAll('img[src],source[src]')) "
            "e.setAttribute('src', e.src);"
            "return document.documentElement.outerHTML;"
        )

    # -- elements ----------------------------------------------------------- #
    def find_all(self, selector: str) -> list[str]:
        els = self._cmd("POST", "/elements", {"using": "css selector", "value": selector})
        return [e[W3C_ELEMENT_KEY] for e in els]

    def element_text(self, el_id: str) -> str:
        return self._cmd("GET", f"/element/{el_id}/text")

    def click_selector(self, selector: str) -> None:
        ids = self.find_all(selector)
        if not ids:
            raise RuntimeError(f"no element matches {selector!r}")
        self._cmd("POST", f"/element/{ids[0]}/click")

    def type_selector(self, selector: str, text: str) -> None:
        ids = self.find_all(selector)
        if not ids:
            raise RuntimeError(f"no element matches {selector!r}")
        self._cmd("POST", f"/element/{ids[0]}/value", {"text": text})

    # -- T2: waiting / scrolling ------------------------------------------- #
    def wait_for_selector(self, selector: str, timeout: float = 10.0,
                          visible: bool = False) -> int:
        """Poll until >=1 element matches (optionally is visible). Returns count."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if visible:
                n = self.eval_js(
                    "return [...document.querySelectorAll(arguments[0])]"
                    ".filter(e => e.offsetWidth || e.offsetHeight || "
                    "e.getClientRects().length).length",
                    [selector],
                )
            else:
                n = len(self.find_all(selector))
            if n:
                return int(n)
            time.sleep(0.2)
        raise TimeoutError(f"selector {selector!r} not present after {timeout}s")

    def scroll(self, to: str = "bottom") -> None:
        """Scroll the page: 'bottom', 'top', a CSS selector, or a 'y' pixel value."""
        if to == "bottom":
            self.eval_js("window.scrollTo(0, document.body.scrollHeight)")
        elif to == "top":
            self.eval_js("window.scrollTo(0, 0)")
        elif to.lstrip("-").isdigit():
            self.eval_js("window.scrollTo(0, arguments[0])", [int(to)])
        else:
            self.eval_js(
                "const el = document.querySelector(arguments[0]);"
                "if (el) el.scrollIntoView({block:'center'});",
                [to],
            )

    # -- T2: extraction ----------------------------------------------------- #
    def extract_links(self, selector: str = "a") -> list[dict[str, str]]:
        """All links under `selector` as {text, href} with absolute hrefs."""
        return self.eval_js(
            "return [...document.querySelectorAll(arguments[0])]"
            ".filter(a => a.href)"
            ".map(a => ({text: (a.innerText||a.textContent||'').trim(), href: a.href}))",
            [selector],
        )

    def extract_table(self, selector: str = "table") -> list[dict[str, str]]:
        """First table matching `selector` → list of row dicts keyed by header.

        Falls back to positional keys (col0, col1, …) when no <th> header row.
        """
        return self.eval_js(
            r"""
            const t = document.querySelector(arguments[0]);
            if (!t) return [];
            const rows = [...t.rows].map(r => [...r.cells].map(c => c.innerText.trim()));
            if (!rows.length) return [];
            let header = rows[0], body = rows.slice(1);
            const hasTh = t.querySelector('thead th, tr th');
            if (!hasTh) { header = rows[0].map((_, i) => 'col' + i); body = rows; }
            return body.map(cells => {
              const o = {};
              header.forEach((h, i) => { o[h || ('col' + i)] = cells[i] ?? ''; });
              return o;
            });
            """,
            [selector],
        )

    # -- T2: forms ---------------------------------------------------------- #
    def fill_form(self, fields: dict[str, str], submit: str | None = None) -> None:
        """Type each value into its CSS selector; optionally click `submit`."""
        for selector, value in fields.items():
            self.type_selector(selector, value)
        if submit:
            self.click_selector(submit)
            self.eval_js("return document.readyState")  # nudge

    # -- T2: diagnostics ---------------------------------------------------- #
    def get_errors(self) -> list[dict[str, Any]]:
        """Best-effort: return JS errors collected on the current page.

        Returns a list of {type, message, source, line, col}, where `type` is
        'error' (uncaught exception), 'unhandledrejection' (rejected promise), or
        'resource' (a failed sub-resource load). The collector is installed on
        navigate() the moment the new document commits.

        LIMITATION: WebDriver runs *after* the document loads, so errors thrown
        during the very first parse/execution — before the collector is injected
        — can be missed. This catches anything that throws once the page is live
        (timers, event handlers, async work, late module evaluation, rejected
        promises), which covers most "this SPA crashed to its error boundary"
        triage. For guaranteed first-byte coverage you'd need native console
        capture in the engine, which Servo's WebDriver does not offer.
        """
        # Ensure the collector exists even if the page was reached without
        # navigate() (e.g. a manual eval_js redirect); harmless if already there.
        self._install_error_collector()
        errs = self.eval_js(
            "return Array.isArray(window.__servoAgentErrors) "
            "? window.__servoAgentErrors : []"
        )
        return errs or []

    # -- capture ------------------------------------------------------------ #
    def screenshot(self, path: str, width: int | None = None,
                   height: int | None = None, full_page: bool = False) -> str:
        """Capture a PNG of the current page; returns the absolute file path.

        Default behavior is unchanged: capture at the current window size.

        - `width`/`height`: resize the WebDriver window (set_window_rect) before
          capture. Servo's screenshot is the window surface, so the PNG comes out
          at the new window's inner size.
        - `full_page`: best-effort whole-document capture. Servo lays out the
          full document regardless of viewport, so we read the content height
          (max of body/documentElement scrollHeight) and grow the window tall
          enough to fit it (clamped to _MAX_FULLPAGE_PX so a pathological page
          can't request a gigantic surface), then capture. This approximates a
          full-page shot without scroll-stitching; very tall pages are clamped.

        `last_screenshot` then holds the PNG's width and height and, for a
        full-page shot, the page's height and whether the shot was cut short.
        """
        self.last_screenshot = None
        content_h: int | None = None
        if width is not None or height is not None or full_page:
            self.ensure_started()
            cur = self._cmd("GET", "/window/rect")
            w = int(width) if width is not None else int(cur.get("width") or 1024)
            h = int(height) if height is not None else int(cur.get("height") or 768)
            if full_page:
                # Lay out at the target width first, then measure true content height.
                self._cmd("POST", "/window/rect", {"width": w, "height": h})
                content_h = int(self.eval_js(
                    "return Math.max("
                    "document.body ? document.body.scrollHeight : 0,"
                    "document.documentElement ? document.documentElement.scrollHeight : 0,"
                    "document.body ? document.body.offsetHeight : 0)"
                ) or h)
                # Pad for window chrome (the surface is a bit shorter than the
                # window) so the bottom row isn't clipped; then clamp.
                h = min(self._MAX_FULLPAGE_PX, content_h + 80)
            self._cmd("POST", "/window/rect", {"width": w, "height": h})
        png = base64.b64decode(self._cmd("GET", "/screenshot"))
        Path(path).write_bytes(png)
        shot: dict[str, Any] = {"width": None, "height": None}
        if png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) >= 24:
            shot["width"] = int.from_bytes(png[16:20], "big")
            shot["height"] = int.from_bytes(png[20:24], "big")
        if full_page:
            shot["page_height"] = content_h
            shot["cut_short"] = (None if shot["height"] is None or content_h is None
                                 else shot["height"] < content_h)
        self.last_screenshot = shot
        return str(Path(path).resolve())

    def status(self) -> dict[str, Any]:
        return {
            "binary": str(self.binary) if self.binary else None,
            "engine_version": self.engine_version,
            "started": self.sid is not None,
            "headless": self.headless,
            "port": self.port,
            "url": self.current_url() if self.sid else None,
            "memory_mb": self.memory_mb(),
            "memory_cap_mb": self.memory_cap_mb,  # 0 = restarts turned off
        }
