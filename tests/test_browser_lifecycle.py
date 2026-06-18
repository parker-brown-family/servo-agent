"""Unit tests for ServoBrowser.ensure_started() self-healing — no real engine.

Regression for the "wedged on a dead servoshell" bug: once a session id was
cached, ensure_started() returned early forever, so a crashed servoshell left
every command failing with "connection refused" until the MCP server restarted.
These stub the launch path so they run in plain `pytest` (no servoshell build).
"""
from __future__ import annotations

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
