"""ServoBrowser — drive our Servo fork over its built-in W3C WebDriver server.

Owns one `servoshell` process + one WebDriver session, launched lazily. Wraps
the W3C protocol in agent-shaped primitives (navigate, read, find, click,
type, extract, wait, scroll) plus the lifecycle plumbing. The MCP server and
the examples are thin layers over this class.
"""
from __future__ import annotations

import base64
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

import requests

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
    """Locate the servoshell binary: $SERVOSHELL, PATH, or a sibling servo fork."""
    env = os.environ.get("SERVOSHELL")
    if env and Path(env).exists():
        return Path(env)
    on_path = shutil.which("servoshell")
    if on_path:
        return Path(on_path)
    # Default: a sibling `servo/` checkout next to this repo (…/servo-agent → …/servo).
    sibling = Path(__file__).resolve().parents[3] / "servo"
    for profile in ("debug", "release"):
        cand = sibling / "target" / profile / "servoshell"
        if cand.exists():
            return cand
    return None


class ServoNotBuilt(RuntimeError):
    """Raised when no servoshell binary can be found."""


class ServoBrowser:
    """One servoshell process + one WebDriver session. Lazy-started, auto-cleaned."""

    # Upper bound for a full_page screenshot window height (px), so a runaway
    # document can't ask the engine for an enormous surface.
    _MAX_FULLPAGE_PX = 20000

    def __init__(self, binary: str | Path | None = None, headless: bool = True) -> None:
        self.binary = Path(binary) if binary else find_servoshell()
        self.headless = headless
        self.proc: subprocess.Popen | None = None
        self.port: int | None = None
        self.base: str | None = None
        self.sid: str | None = None

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
            return
        if not self.binary or not Path(self.binary).exists():
            raise ServoNotBuilt(
                "servoshell binary not found. Build it "
                "(`./mach build -d --media-stack dummy` in the servo fork) or set "
                "$SERVOSHELL to its path."
            )
        self.port = self._free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        cmd = [str(self.binary), "--webdriver", str(self.port), "about:blank"]
        if self.headless:
            cmd.insert(1, "--headless")
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        self._wait_port(self.port)
        caps = {"capabilities": {"alwaysMatch": {"browserName": "servo"}}}
        self.sid = self._raw("POST", "/session", caps)["sessionId"]

    @staticmethod
    def _wait_port(port: int, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    return
            except OSError:
                time.sleep(0.5)
        raise RuntimeError(f"WebDriver port {port} never came up")

    def shutdown(self) -> None:
        if self.sid and self.base:
            try:
                self._raw("DELETE", f"/session/{self.sid}")
            except Exception:  # noqa: BLE001 — best effort
                pass
        self.sid = None
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    # -- raw W3C transport -------------------------------------------------- #
    def _raw(self, method: str, path: str, body: dict | None = None) -> Any:
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
        """Navigate and wait for the NEW document to actually commit.

        Servo's WebDriver POST /url can return before the new document replaces
        the old one, so polling readyState alone races (the previous page still
        reports 'complete'). We also wait for the live document URL to become
        the target before declaring readiness.

        On commit we inject a best-effort JS error collector (see get_errors).
        When `settle` is true we additionally wait_for_load() so SPAs that mutate
        the DOM after readyState=complete (e.g. hydration) have settled before we
        return — handy when the immediate next read is <title>/content.
        """
        prev = self.eval_js("return document.URL")
        self._cmd("POST", "/url", {"url": url})
        deadline = time.monotonic() + timeout
        target = url.split("#", 1)[0].rstrip("/")
        state = "unknown"
        committed = False
        while time.monotonic() < deadline:
            cur = (self.eval_js("return document.URL") or "").split("#", 1)[0].rstrip("/")
            state = self.eval_js("return document.readyState") or "unknown"
            committed = cur == target or (cur != prev and cur != "about:blank")
            if committed and state == "complete":
                break
            time.sleep(0.2)
        if committed:
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

        Returns the final readyState ('complete' on success). Falls back to the
        last observed readyState if `timeout` elapses first (does not raise, so a
        slow page still yields whatever has rendered).
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
            if state == "complete" and sig == last_sig:
                if quiet_since is None:
                    quiet_since = now
                elif now - quiet_since >= quiet:
                    return state
            else:
                quiet_since = now if state == "complete" else None
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

    def read_native(self, timeout: float = 10.0) -> dict[str, Any] | None:
        """Read the page natively via Servo's `/servo/agent/read` extension.

        Returns ``{url, title, text, headings, links}`` computed inside the engine
        (no `execute_script(outerHTML)` round-trip), or ``None`` if the running
        servoshell predates the endpoint (HTTP 404) — callers fall back to
        ``read_html()`` + :func:`servo_agent.distill.distill`.
        """
        self.ensure_started()
        resp = requests.post(
            f"{self.base}/session/{self.sid}/servo/agent/read", json={}, timeout=timeout
        )
        if resp.status_code != 200:
            return None  # 404 → endpoint absent; other errors → fall back gracefully
        return resp.json().get("value")

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
        capture in the engine (tracked separately as T3).
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
        """
        if width is not None or height is not None or full_page:
            self.ensure_started()
            cur = self._cmd("GET", "/window/rect")
            w = int(width) if width is not None else int(cur.get("width") or 1024)
            h = int(height) if height is not None else int(cur.get("height") or 768)
            if full_page:
                # Lay out at the target width first, then measure true content height.
                self._cmd("POST", "/window/rect", {"width": w, "height": h})
                content_h = self.eval_js(
                    "return Math.max("
                    "document.body ? document.body.scrollHeight : 0,"
                    "document.documentElement ? document.documentElement.scrollHeight : 0,"
                    "document.body ? document.body.offsetHeight : 0)"
                ) or h
                # Pad for window chrome (the surface is a bit shorter than the
                # window) so the bottom row isn't clipped; then clamp.
                h = min(self._MAX_FULLPAGE_PX, int(content_h) + 80)
            self._cmd("POST", "/window/rect", {"width": w, "height": h})
        b64 = self._cmd("GET", "/screenshot")
        Path(path).write_bytes(base64.b64decode(b64))
        return str(Path(path).resolve())

    def status(self) -> dict[str, Any]:
        return {
            "binary": str(self.binary) if self.binary else None,
            "started": self.sid is not None,
            "headless": self.headless,
            "port": self.port,
            "url": self.current_url() if self.sid else None,
        }
