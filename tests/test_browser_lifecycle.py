"""Unit tests for ServoBrowser's lifecycle, navigation and transport — no real engine.

Regression for the "wedged on a dead servoshell" bug: once a session id was
cached, ensure_started() returned early forever, so a crashed servoshell left
every command failing with "connection refused" until the MCP server restarted.
Also covers bounded navigation (issue #2), the JSON body every WebDriver POST
must carry (issue #4), and finding the engine from a project that installs
servo-agent.
These stub the engine so they run in plain `pytest` (no servoshell build).
"""
from __future__ import annotations

import pytest

import servo_agent.browser as browser_mod
from servo_agent.browser import ServoBrowser


class _FakeProc:
    """Minimal stand-in for subprocess.Popen — poll() reports alive/dead."""

    pid = -1  # no such process, so its memory reads as unknown

    def __init__(self, alive: bool) -> None:
        self._alive = alive

    def poll(self):  # None == still running (subprocess.Popen contract)
        return None if self._alive else 1


def _stub_launch(monkeypatch, browser: ServoBrowser, *, new_sid: str = "fresh") -> dict:
    """Stub the (re)launch path so ensure_started() needs no real engine."""
    spawned = {"count": 0}

    def fake_popen(*_a, **_k):
        spawned["count"] += 1
        return _FakeProc(alive=True)

    monkeypatch.setattr(browser_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(browser, "_free_port", lambda: 49999)
    monkeypatch.setattr(browser, "_wait_port", lambda *_a, **_k: None)
    monkeypatch.setattr(browser, "_raw", lambda *_a, **_k: {"sessionId": new_sid})
    return spawned


def _browser_with_binary(tmp_path) -> ServoBrowser:
    binary = tmp_path / "servoshell"
    binary.write_text("#!/bin/true\n")
    return ServoBrowser(binary=binary)


def test_respawns_after_owned_engine_dies(monkeypatch, tmp_path) -> None:
    b = _browser_with_binary(tmp_path)
    b.sid, b.proc, b.port = "stale", _FakeProc(alive=False), 55545  # crashed engine
    spawned = _stub_launch(monkeypatch, b, new_sid="fresh")

    b.ensure_started()

    assert spawned["count"] == 1, "a dead engine must be respawned"
    assert b.sid == "fresh", "a fresh session must replace the stale one"


def test_keeps_live_session_without_respawning(monkeypatch, tmp_path) -> None:
    b = _browser_with_binary(tmp_path)
    b.sid, b.proc = "keep", _FakeProc(alive=True)
    spawned = _stub_launch(monkeypatch, b, new_sid="should-not-be-used")

    b.ensure_started()

    assert spawned["count"] == 0, "a live engine must not be relaunched"
    assert b.sid == "keep", "a live session id must be preserved"


def test_trusts_external_engine_without_a_proc(monkeypatch, tmp_path) -> None:
    # An attached/external engine has no owned proc to poll — its sid is trusted.
    b = _browser_with_binary(tmp_path)
    b.sid, b.proc, b.external = "external", None, True
    spawned = _stub_launch(monkeypatch, b, new_sid="should-not-be-used")

    b.ensure_started()

    assert spawned["count"] == 0
    assert b.sid == "external"


class _FakePage:
    """Answers navigate()'s scripts like a tab whose next document arrives late.

    `arrives_after` is how many readiness polls still see the OLD document;
    `None` means the new document never arrives. The old document always
    reports `complete`, which is exactly what made the URL a useless signal.
    `growing` makes the new document's DOM change on every poll.
    """

    def __init__(self, url: str, *, arrives_after: int | None, new_state: str = "complete",
                 growing: bool = False, grows_for: int | None = None):
        self.url = url
        self.arrives_after = arrives_after
        self.new_state = new_state
        self.growing = growing
        self.grows_for = grows_for  # polls during which the DOM keeps changing
        self.token: str | None = None
        self.assigned: str | None = None
        self.polls = 0
        self.clock = {"now": 0.0}

    def eval_js(self, script: str, args: list | None = None):
        if script.startswith("document.__servoAgentNav = "):
            self.token = args[0]
            target = args[1]
            fragment_only = "#" in target and target.split("#")[0] == self.url.split("#")[0]
            return [self.url, fragment_only]
        if script.startswith("window.location.assign"):
            self.assigned = args[0]
            return True
        if "__servoAgentNav ===" in script:
            self.polls += 1
            if self.arrives_after is not None and self.polls > self.arrives_after:
                changing = self.growing or (self.grows_for is not None
                                            and self.polls <= self.grows_for)
                elements = 40 + (self.polls if changing else self.grows_for or 0)
                return [False, self.new_state, elements, 900]  # new document: no token
            return [args[0] == self.token, "complete", 12, 300]  # still the old document
        return "ok"  # the error collector


def _navigating_browser(monkeypatch, tmp_path, page: _FakePage) -> ServoBrowser:
    b = _browser_with_binary(tmp_path)
    b.sid, b.proc, b.base = "session", _FakeProc(alive=True), "http://127.0.0.1:1"
    monkeypatch.setattr(b, "eval_js", page.eval_js)

    def no_raw_webdriver(*args, **_kwargs):
        raise AssertionError(f"navigate() must not call WebDriver directly: {args}")

    monkeypatch.setattr(b, "_cmd", no_raw_webdriver)  # in particular, no POST /url
    clock = page.clock

    def tick() -> float:
        clock["now"] += 0.25
        return clock["now"]

    monkeypatch.setattr(browser_mod.time, "monotonic", tick)
    monkeypatch.setattr(browser_mod.time, "sleep", lambda _seconds: None)
    return b


def test_navigation_starts_from_script_not_post_url(monkeypatch, tmp_path) -> None:
    """POST /url holds the session until load completes, so it must not be used."""
    page = _FakePage("about:blank", arrives_after=0)
    b = _navigating_browser(monkeypatch, tmp_path, page)

    assert b.navigate("https://example.com/") == "complete"
    assert page.assigned == "https://example.com/"


def test_reopening_the_same_url_waits_for_the_new_document(monkeypatch, tmp_path) -> None:
    """Same URL, old document still `complete`: only the token tells them apart."""
    page = _FakePage("https://example.com/", arrives_after=3)
    b = _navigating_browser(monkeypatch, tmp_path, page)

    assert b.navigate("https://example.com/") == "complete"
    assert page.polls == 4, "returned while the old document was still live"


def test_still_interactive_page_returns_without_waiting_out_the_timeout(
    monkeypatch, tmp_path
) -> None:
    """servo.org/about: readable in ~2 s, `interactive` forever (fonts never finish)."""
    page = _FakePage("about:blank", arrives_after=0, new_state="interactive")
    b = _navigating_browser(monkeypatch, tmp_path, page)

    assert b.navigate("https://servo.org/about/", timeout=20.0) == "interactive"
    quiet = browser_mod.ServoBrowser._INTERACTIVE_QUIET_S
    assert quiet <= page.clock["now"] < quiet + 2.0, "should stop once the DOM is still"


def test_a_page_rendering_after_it_is_readable_is_waited_for(monkeypatch, tmp_path) -> None:
    """Issue #11's guard: the shorter quiet must still let a client-rendered page finish.

    The DOM changes for six polls (1.5 s on the fake clock) after the document
    arrives, then holds still; navigate() returns only once it has been still.
    """
    page = _FakePage("about:blank", arrives_after=0, new_state="interactive", grows_for=6)
    b = _navigating_browser(monkeypatch, tmp_path, page)

    assert b.navigate("https://app.example/", timeout=20.0) == "interactive"
    assert page.polls > 6, "returned while the page was still rendering"
    quiet = browser_mod.ServoBrowser._INTERACTIVE_QUIET_S
    assert page.clock["now"] < 1.5 + quiet + 1.0, "should stop soon after the DOM goes still"


def test_interactive_page_still_changing_waits_until_the_deadline(monkeypatch, tmp_path) -> None:
    """A DOM that keeps changing is still loading; give it the whole timeout."""
    page = _FakePage("about:blank", arrives_after=0, new_state="interactive", growing=True)
    b = _navigating_browser(monkeypatch, tmp_path, page)

    assert b.navigate("https://hcvideo.app/", timeout=6.0) == "interactive"
    assert page.clock["now"] >= 6.0


def _settling_browser(monkeypatch, tmp_path, states: list[str]) -> tuple[ServoBrowser, dict]:
    """A browser whose page reports `states` in turn (the last repeats), DOM still."""
    b = _browser_with_binary(tmp_path)
    seq = iter(states)
    current = {"state": states[0]}

    def fake_eval(script: str, args: list | None = None):
        if "readyState" in script:
            current["state"] = next(seq, current["state"])
            return current["state"]
        return [40, 900]  # element count, scrollHeight: unchanged

    clock = {"now": 0.0}

    def tick() -> float:
        clock["now"] += 0.1
        return clock["now"]

    monkeypatch.setattr(b, "eval_js", fake_eval)
    monkeypatch.setattr(browser_mod.time, "monotonic", tick)
    monkeypatch.setattr(browser_mod.time, "sleep", lambda _seconds: None)
    return b, clock


def test_wait_for_load_stops_on_a_still_interactive_page(monkeypatch, tmp_path) -> None:
    b, clock = _settling_browser(monkeypatch, tmp_path, ["interactive"])

    assert b.wait_for_load(timeout=15.0) == "interactive"
    assert clock["now"] < 5.0, "a still DOM at `interactive` should not wait out 15 s"


def test_wait_for_load_waits_out_a_loading_page(monkeypatch, tmp_path) -> None:
    b, clock = _settling_browser(monkeypatch, tmp_path, ["loading"])

    assert b.wait_for_load(timeout=3.0) == "loading"
    assert clock["now"] >= 3.0


def test_wait_for_load_still_prefers_complete(monkeypatch, tmp_path) -> None:
    b, _clock = _settling_browser(monkeypatch, tmp_path, ["interactive", "complete"])

    assert b.wait_for_load(timeout=15.0) == "complete"


def test_navigation_that_never_commits_raises(monkeypatch, tmp_path) -> None:
    """Returning the old page's `complete` would be a confident wrong answer."""
    page = _FakePage("https://example.com/a", arrives_after=None)
    b = _navigating_browser(monkeypatch, tmp_path, page)

    with pytest.raises(TimeoutError, match="did not commit"):
        b.navigate("https://example.com/b", timeout=2.0)


def test_a_failed_poll_after_commit_does_not_undo_it(monkeypatch, tmp_path) -> None:
    """The new document arrived; an error on the last poll must not read as 'never'."""
    page = _FakePage("about:blank", arrives_after=0, new_state="interactive", growing=True)
    b = _navigating_browser(monkeypatch, tmp_path, page)
    polls_before_failing = 3

    def flaky_eval(script: str, args: list | None = None):
        if "__servoAgentNav ===" in script and page.polls >= polls_before_failing:
            page.polls += 1
            raise RuntimeError("POST /execute/sync -> 500 javascript error: document gone")
        return page.eval_js(script, args)

    monkeypatch.setattr(b, "eval_js", flaky_eval)

    assert b.navigate("https://example.com/", timeout=3.0) == "unknown"


def test_fragment_only_navigation_keeps_the_document(monkeypatch, tmp_path) -> None:
    """`#anchor` on the current page scrolls; no new document ever arrives."""
    page = _FakePage("https://example.com/guide", arrives_after=None)
    b = _navigating_browser(monkeypatch, tmp_path, page)

    assert b.navigate("https://example.com/guide#install", timeout=2.0) == "complete"
    assert page.polls == 1


class _Resp:
    status_code = 200

    def __init__(self, value) -> None:
        self._value = value

    def json(self):
        return {"value": self._value}


def test_parameterless_posts_send_an_empty_json_object(monkeypatch, tmp_path) -> None:
    """W3C requires every POST body to be a JSON object; Servo 400s an empty one."""
    sent: list[tuple[str, str, object]] = []

    def fake_request(method, url, json=None, timeout=None):
        sent.append((method, url.removeprefix("http://127.0.0.1:1/session/s"), json))
        if url.endswith("/elements"):
            return _Resp([{browser_mod.W3C_ELEMENT_KEY: "el-1"}])
        return _Resp(None)

    monkeypatch.setattr(browser_mod.requests, "request", fake_request)
    b = _browser_with_binary(tmp_path)
    b.sid, b.proc, b.base = "s", _FakeProc(alive=True), "http://127.0.0.1:1"

    b.click_selector("a#next")
    b.back()
    b.reload()
    b._raw("DELETE", "/session/s")

    assert ("POST", "/element/el-1/click", {}) in sent
    assert ("POST", "/back", {}) in sent
    assert ("POST", "/refresh", {}) in sent
    assert all(isinstance(body, dict) for method, _, body in sent if method == "POST")
    assert ("DELETE", "", None) in sent  # DELETE has no body to parse


def test_launch_gives_the_engine_a_throwaway_profile(monkeypatch, tmp_path) -> None:
    """Without --temporary-storage every servoshell shares ~/.config/servo/default."""
    launched: list[list[str]] = []

    def fake_popen(cmd, **_k):
        launched.append(cmd)
        return _FakeProc(alive=True)

    b = _browser_with_binary(tmp_path)
    monkeypatch.setattr(browser_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(b, "_free_port", lambda: 49999)
    monkeypatch.setattr(b, "_wait_port", lambda *_a, **_k: None)
    monkeypatch.setattr(b, "_raw", lambda *_a, **_k: {"sessionId": "s"})
    monkeypatch.delenv("SERVO_WEBDRIVER", raising=False)

    b.ensure_started()

    cmd = launched[0]
    assert "--temporary-storage" in cmd and "--headless" in cmd
    assert cmd[cmd.index("--webdriver") + 1] == "49999" and cmd[-1] == "about:blank"
    # A headless window grows to twice the screen: 10,000 lets a full page reach 20,000 px.
    assert "--screen-size=2048x10000" in cmd


class _StubbornProc:
    """A servoshell that catches SIGTERM and never exits, as Servo 0.7 does headless."""

    def __init__(self) -> None:
        self.waits: list[float | None] = []
        self.killed = False

    def poll(self):
        return -9 if self.killed else None

    def terminate(self) -> None:
        pass  # caught, and the graceful shutdown never finishes

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if not self.killed:
            raise browser_mod.subprocess.TimeoutExpired("servoshell", timeout)
        return -9


class _PoliteProc(_StubbornProc):
    """A servoshell that exits when asked through Servo's shutdown route."""

    def __init__(self) -> None:
        super().__init__()
        self.asked = False

    def poll(self):
        return 0 if self.asked else None

    def terminate(self) -> None:
        raise AssertionError("an engine that quit through the route needs no signal")

    def wait(self, timeout=None):
        self.waits.append(timeout)
        return 0


def test_shutdown_asks_servo_to_quit_through_its_own_route(monkeypatch, tmp_path) -> None:
    b = _browser_with_binary(tmp_path)
    proc = _PoliteProc()
    b.proc, b.base, b.sid = proc, "http://127.0.0.1:1", "s"
    deleted: list[str] = []

    def fake_delete(url, timeout=None):
        deleted.append(url)
        proc.asked = True

    monkeypatch.setattr(browser_mod.requests, "delete", fake_delete)

    b.shutdown()

    assert deleted == ["http://127.0.0.1:1/session/s/servo/shutdown"]
    assert b.proc is None and b.sid is None


def test_shutdown_kills_an_engine_that_ignores_the_route_and_sigterm(monkeypatch,
                                                                    tmp_path) -> None:
    b = _browser_with_binary(tmp_path)
    proc = _StubbornProc()
    b.proc, b.base, b.sid = proc, "http://127.0.0.1:1", "s"
    monkeypatch.setattr(browser_mod.requests, "delete", lambda *_a, **_k: None)

    b.shutdown()

    assert proc.killed, "an engine that ignores the route and SIGTERM must be killed"
    grace = ServoBrowser._TERM_GRACE_S
    assert grace <= 1.0 and proc.waits[:2] == [grace, grace]
    assert len(proc.waits) == 3, "the killed process is reaped, not left a zombie"
    assert b.proc is None


def test_shutdown_leaves_an_attached_engine_running(monkeypatch, tmp_path) -> None:
    b = _browser_with_binary(tmp_path)
    b.external, b.base, b.sid = True, "http://127.0.0.1:1", "s"
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(b, "_raw", lambda method, path, *_a: sent.append((method, path)))
    monkeypatch.setattr(browser_mod.requests, "delete",
                        lambda *_a, **_k: pytest.fail("never shut down someone else's engine"))

    b.shutdown()

    assert sent == [("DELETE", "/session/s")]


def test_navigate_restarts_an_engine_over_its_memory_cap_and_says_so(monkeypatch, tmp_path) -> None:
    """Issue #14: Servo 0.7 climbed to 5.3 GB over 100 pages in one window."""
    page = _FakePage("about:blank", arrives_after=0)
    b = _navigating_browser(monkeypatch, tmp_path, page)
    b.memory_cap_mb = 1024
    calls: list[str] = []
    monkeypatch.setattr(b, "memory_mb", lambda: 1500)
    monkeypatch.setattr(b, "shutdown", lambda: calls.append("shutdown"))
    monkeypatch.setattr(b, "ensure_started", lambda: calls.append("start"))

    assert b.navigate("https://example.com/") == "complete"

    assert calls == ["shutdown", "start"]
    assert b.last_restart["pss_mb"] == 1500 and b.last_restart["cap_mb"] == 1024
    assert "cookies" in b.last_restart["lost"]

    monkeypatch.setattr(b, "memory_mb", lambda: 600)
    b.navigate("https://example.com/next")
    assert b.last_restart is None, "a navigation that restarted nothing must not say it did"


@pytest.mark.parametrize("cap, used", [(0, 5000), (1024, None)])
def test_no_restart_when_the_cap_is_off_or_memory_is_unknown(monkeypatch, tmp_path,
                                                              cap, used) -> None:
    page = _FakePage("about:blank", arrives_after=0)
    b = _navigating_browser(monkeypatch, tmp_path, page)
    b.memory_cap_mb = cap
    monkeypatch.setattr(b, "memory_mb", lambda: used)
    monkeypatch.setattr(b, "shutdown", lambda: pytest.fail("must not restart"))

    b.navigate("https://example.com/")

    assert b.last_restart is None


def test_memory_cap_comes_from_the_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SERVO_AGENT_MEMORY_CAP_MB", "0")
    assert _browser_with_binary(tmp_path).memory_cap_mb == 0
    monkeypatch.delenv("SERVO_AGENT_MEMORY_CAP_MB")
    assert _browser_with_binary(tmp_path).memory_cap_mb == ServoBrowser.DEFAULT_MEMORY_CAP_MB


def test_an_attached_engine_has_no_memory_reading(tmp_path) -> None:
    b = _browser_with_binary(tmp_path)
    b.external = True
    assert b.memory_mb() is None


def test_engine_version_is_read_from_the_session_user_agent(monkeypatch, tmp_path) -> None:
    b = _browser_with_binary(tmp_path)
    _stub_launch(monkeypatch, b)
    agent = "Mozilla/5.0 (X11; Linux x86_64; rv:153.0) Servo/0.7.0 Firefox/153.0"
    monkeypatch.setattr(b, "_raw", lambda *_a, **_k: {
        "sessionId": "s", "capabilities": {"browserVersion": "0.0.1", "userAgent": agent}})
    monkeypatch.delenv("SERVO_WEBDRIVER", raising=False)

    b.ensure_started()

    assert b.engine_version == "0.7.0"


def _png(width: int, height: int) -> bytes:
    return (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + width.to_bytes(4, "big")
            + height.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00")


@pytest.mark.parametrize("page_height, cut", [(6040, False), (30000, True)])
def test_full_page_screenshot_reports_its_size_and_any_cut(monkeypatch, tmp_path,
                                                            page_height, cut) -> None:
    import base64

    b = _browser_with_binary(tmp_path)
    b.sid, b.proc = "s", _FakeProc(alive=True)
    window = {"width": 1024, "height": 740}

    def fake_cmd(method, path, body=None):
        if path == "/window/rect":
            if method == "POST":
                window.update(body)
            return dict(window)
        if path == "/screenshot":
            return base64.b64encode(_png(window["width"], window["height"])).decode()
        raise AssertionError(path)

    monkeypatch.setattr(b, "_cmd", fake_cmd)
    monkeypatch.setattr(b, "eval_js", lambda *_a, **_k: page_height)

    b.screenshot(str(tmp_path / "shot.png"), width=800, full_page=True)

    shot = b.last_screenshot
    assert shot["width"] == 800 and shot["page_height"] == page_height
    assert shot["height"] == min(page_height + 80, ServoBrowser._MAX_FULLPAGE_PX)
    assert shot["cut_short"] is cut


_SERVO_TIMEOUT = ("GET /session/s/screenshot -> 500 timeout: Timed out waiting to take "
                  "screenshot. Test likely didn't finish.")


def _capturing_browser(monkeypatch, tmp_path, *, fails: int, pending: list[str]):
    """A browser whose screenshot times out `fails` times, with `pending` unfinished images."""
    import base64

    b = _browser_with_binary(tmp_path)
    b.sid, b.proc = "s", _FakeProc(alive=True)
    calls = {"screenshot": 0, "dropped": False}

    def fake_cmd(method, path, body=None):
        assert path == "/screenshot", path
        calls["screenshot"] += 1
        if calls["screenshot"] <= fails:
            raise RuntimeError(_SERVO_TIMEOUT)
        return base64.b64encode(_png(1024, 740)).decode()

    def fake_eval(script, args=None):
        if "img.complete" in script:
            calls["dropped"] = True
            return list(pending)
        return "interactive"

    monkeypatch.setattr(b, "_cmd", fake_cmd)
    monkeypatch.setattr(b, "eval_js", fake_eval)
    return b, calls


def test_screenshot_drops_images_that_never_finish_and_tries_again(monkeypatch, tmp_path) -> None:
    """Issue #3: Servo will not capture while any image is still loading."""
    b, calls = _capturing_browser(monkeypatch, tmp_path, fails=1,
                                  pending=["http://site.example/never.png"])

    b.screenshot(str(tmp_path / "shot.png"))

    assert calls == {"screenshot": 2, "dropped": True}
    assert b.last_screenshot["dropped_unfinished_images"] == ["http://site.example/never.png"]


def test_screenshot_with_nothing_to_drop_says_what_servo_waits_on(monkeypatch, tmp_path) -> None:
    b, calls = _capturing_browser(monkeypatch, tmp_path, fails=1, pending=[])

    with pytest.raises(browser_mod.ScreenshotUnavailable, match="font or stylesheet"):
        b.screenshot(str(tmp_path / "shot.png"))
    assert calls["screenshot"] == 1


def test_screenshot_that_fails_again_is_classified(monkeypatch, tmp_path) -> None:
    b, _calls = _capturing_browser(monkeypatch, tmp_path, fails=2, pending=["http://x/a.png"])

    with pytest.raises(browser_mod.ScreenshotUnavailable, match="1 unfinished image"):
        b.screenshot(str(tmp_path / "shot.png"))


def test_other_screenshot_errors_pass_through(monkeypatch, tmp_path) -> None:
    b = _browser_with_binary(tmp_path)
    b.sid, b.proc = "s", _FakeProc(alive=True)

    def broken(*_a, **_k):
        raise RuntimeError("GET /session/s/screenshot -> 404 no such window")

    monkeypatch.setattr(b, "_cmd", broken)
    with pytest.raises(RuntimeError, match="no such window"):
        b.screenshot(str(tmp_path / "shot.png"))


def test_engine_search_order(monkeypatch, tmp_path) -> None:
    """$SERVOSHELL, then PATH, then an installed official build, then a servo/ nearby."""
    paths = {name: tmp_path / name / "servoshell" for name in ("env", "path", "installed")}
    for p in paths.values():
        p.parent.mkdir()
        p.write_text("")
    monkeypatch.setattr(browser_mod, "_servoshell_beside", lambda _start: tmp_path / "beside")
    monkeypatch.setattr(browser_mod, "newest_installed", lambda: paths["installed"])
    monkeypatch.setattr(browser_mod.shutil, "which", lambda _name: str(paths["path"]))
    monkeypatch.setenv("SERVOSHELL", str(paths["env"]))

    assert browser_mod.find_servoshell() == paths["env"]
    monkeypatch.delenv("SERVOSHELL")
    assert browser_mod.find_servoshell() == paths["path"]
    monkeypatch.setattr(browser_mod.shutil, "which", lambda _name: None)
    assert browser_mod.find_servoshell() == paths["installed"]
    monkeypatch.setattr(browser_mod, "newest_installed", lambda: None)
    assert browser_mod.find_servoshell() == tmp_path / "beside"


def test_an_unpacked_release_or_release_build_beside_is_preferred(tmp_path) -> None:
    here = tmp_path / "project" / "browser.py"
    debug = tmp_path / "servo" / "target" / "debug" / "servoshell"
    release = tmp_path / "servo" / "target" / "release" / "servoshell"
    unpacked = tmp_path / "servo" / "servoshell"
    for p in (debug, release):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")

    assert browser_mod._servoshell_beside(here) == release
    unpacked.write_text("")
    assert browser_mod._servoshell_beside(here) == unpacked


def test_finds_a_servo_checkout_beside_an_installing_project(tmp_path) -> None:
    """servo-reader installs servo-agent into its .venv; walk up to the sibling."""
    binary = tmp_path / "servo" / "target" / "debug" / "servoshell"
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    installed = (
        tmp_path / "servo-reader" / ".venv" / "lib" / "python3.12" / "site-packages"
        / "servo_agent" / "browser.py"
    )

    assert browser_mod._servoshell_beside(installed) == binary


def test_no_servo_checkout_means_none(tmp_path) -> None:
    assert browser_mod._servoshell_beside(tmp_path / "project" / "browser.py") is None
