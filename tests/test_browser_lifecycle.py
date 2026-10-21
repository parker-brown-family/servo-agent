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
                 growing: bool = False):
        self.url = url
        self.arrives_after = arrives_after
        self.new_state = new_state
        self.growing = growing
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
                elements = 40 + (self.polls if self.growing else 0)
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
