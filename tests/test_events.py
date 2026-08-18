"""Unit tests for the tool-call event log. No engine required."""
from __future__ import annotations

import inspect
import json

import pytest

from servo_agent.distill import _distill
from servo_agent.events import (
    EventLog,
    _clip_args,
    _clip_val,
    events_cli,
    make_logger,
    read_events,
    record_meta,
    summarize,
)


class _Proc:
    def __init__(self, pid: int) -> None:
        self.pid = pid


class _FakeBrowser:
    """Stands in for ServoBrowser — only the attrs the logger reads."""

    def __init__(self, pid: int | None = 111, external: bool = False) -> None:
        self.proc = _Proc(pid) if pid is not None else None
        self.external = external


# --------------------------------------------------------------------------- #
# EventLog: path resolution + write/read
# --------------------------------------------------------------------------- #

def test_from_env_explicit_path(tmp_path, monkeypatch) -> None:
    p = tmp_path / "ev.jsonl"
    monkeypatch.setenv("SERVO_AGENT_LOG", str(p))
    assert EventLog.from_env().path == p


@pytest.mark.parametrize("val", ["off", "0", "none", "", "FALSE"])
def test_from_env_disabled(monkeypatch, val) -> None:
    monkeypatch.setenv("SERVO_AGENT_LOG", val)
    assert EventLog.from_env().path is None


def test_from_env_default(monkeypatch) -> None:
    monkeypatch.delenv("SERVO_AGENT_LOG", raising=False)
    path = EventLog.from_env().path
    assert path is not None and path.name == "events.jsonl"


def test_write_creates_dir_and_appends(tmp_path) -> None:
    p = tmp_path / "nested" / "ev.jsonl"
    log = EventLog(p)
    log.write({"tool": "a", "ok": True})
    log.write({"tool": "b", "ok": False})
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    assert [json.loads(line)["tool"] for line in lines] == ["a", "b"]


def test_disabled_log_writes_nothing(tmp_path) -> None:
    log = EventLog(None)
    log.write({"tool": "a"})  # must not raise
    assert not list(tmp_path.iterdir())


# --------------------------------------------------------------------------- #
# Arg clipping / redaction
# --------------------------------------------------------------------------- #

def test_clip_long_string_truncated() -> None:
    out = _clip_val("x" * 300)
    assert out.startswith("x" * 200) and out.endswith("(+100)") and len(out) < 300


def test_clip_dict_redacts_string_values() -> None:
    assert _clip_val({"#pw": "hunter2", "n": 3}) == {"#pw": "<7 chars>", "n": 3}


def test_clip_args_binds_defaults() -> None:
    def fn(selector: str, timeout: float = 10.0) -> str:
        return ""

    sig = inspect.signature(fn)
    assert _clip_args(sig, ("a",), {}) == {"selector": "a", "timeout": 10.0}


# --------------------------------------------------------------------------- #
# The instrument decorator
# --------------------------------------------------------------------------- #

def test_logged_preserves_signature_and_name() -> None:
    # FastMCP builds the tool schema from the signature — it MUST survive wrapping.
    logged = make_logger(_FakeBrowser(), EventLog(None))

    def open_url(url: str, settle: bool = False) -> str:
        return "ok"

    wrapped = logged("open_url")(open_url)
    assert wrapped.__name__ == "open_url"
    assert inspect.signature(wrapped) == inspect.signature(open_url)


def test_logged_records_success_and_meta(tmp_path) -> None:
    log = EventLog(tmp_path / "ev.jsonl")
    logged = make_logger(_FakeBrowser(pid=111), log)

    @logged("read_page")
    def read_page(max_chars: int = 12000) -> str:
        record_meta(extractor="trafilatura", ratio=201.5)
        return "x" * 42

    assert read_page() == "x" * 42
    ev = read_events(log.path)[-1]
    assert ev["tool"] == "read_page"
    assert ev["ok"] is True
    assert ev["bytes"] == 42
    assert ev["extractor"] == "trafilatura" and ev["ratio"] == 201.5
    assert ev["args"] == {"max_chars": 12000}
    assert isinstance(ev["ms"], (int, float))
    assert ev["engine"]["external"] is False and ev["engine"]["pid"] == 111


def test_logged_records_error_and_reraises(tmp_path) -> None:
    log = EventLog(tmp_path / "ev.jsonl")
    logged = make_logger(_FakeBrowser(), log)

    @logged("click")
    def click(selector: str) -> str:
        raise ValueError("no such element")

    with pytest.raises(ValueError):
        click("#gone")
    ev = read_events(log.path)[-1]
    assert ev["ok"] is False
    assert ev["error_type"] == "ValueError" and "no such element" in ev["error"]


def test_logged_flags_respawn(tmp_path) -> None:
    log = EventLog(tmp_path / "ev.jsonl")
    fb = _FakeBrowser(pid=1)
    logged = make_logger(fb, log)

    @logged("open_url")
    def open_url(url: str) -> str:
        fb.proc = _Proc(2)  # engine died + respawned mid-call
        return "ok"

    open_url("https://example.com")
    assert read_events(log.path)[-1]["engine"]["respawned"] is True


def test_logging_failure_never_breaks_the_call(tmp_path) -> None:
    # An unwritable path must not stop the tool from returning.
    log = EventLog(tmp_path / "ev.jsonl")
    logged = make_logger(_FakeBrowser(), log)

    @logged("status")
    def status() -> str:
        return "fine"

    log.path = tmp_path  # a directory — open('a') will fail
    assert status() == "fine"


# --------------------------------------------------------------------------- #
# read_events filters + summarize
# --------------------------------------------------------------------------- #

def _seed(path) -> None:
    rows = [
        {"ts": "2026-06-18T00:00:01Z", "tool": "open_url", "ok": True, "ms": 100},
        {"ts": "2026-06-18T00:00:02Z", "tool": "read_page", "ok": True, "ms": 50,
         "extractor": "trafilatura", "ratio": 200.0},
        {"ts": "2026-06-18T00:00:03Z", "tool": "read_page", "ok": True, "ms": 90,
         "extractor": "fallback", "ratio": 12.0},
        {"ts": "2026-06-18T00:00:04Z", "tool": "click", "ok": False, "ms": 30,
         "error": "boom", "error_type": "ValueError"},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_read_events_filters(tmp_path) -> None:
    p = tmp_path / "ev.jsonl"
    _seed(p)
    assert len(read_events(p)) == 4
    assert {e["tool"] for e in read_events(p, tool="read_page")} == {"read_page"}
    assert [e["tool"] for e in read_events(p, errors_only=True)] == ["click"]
    assert len(read_events(p, since="2026-06-18T00:00:03Z")) == 2
    assert len(read_events(p, limit=1)) == 1


def test_read_events_tolerant_of_garbage(tmp_path) -> None:
    p = tmp_path / "ev.jsonl"
    p.write_text('{"tool":"a","ok":true}\nnot json\n\n', encoding="utf-8")
    assert [e["tool"] for e in read_events(p)] == ["a"]


def test_read_events_missing_file() -> None:
    assert read_events("/no/such/log.jsonl") == []


def test_summarize(tmp_path) -> None:
    p = tmp_path / "ev.jsonl"
    _seed(p)
    s = summarize(read_events(p))
    assert s["total"] == 4 and s["ok"] == 3 and s["errors"] == 1
    assert s["error_rate"] == 0.25
    assert s["by_tool"]["read_page"] == {"calls": 2, "errors": 0}
    assert s["by_tool"]["click"]["errors"] == 1
    assert s["distill"]["samples"] == 2 and s["distill"]["ratio_avg"] == 106.0
    assert s["distill"]["extractors"] == {"trafilatura": 1, "fallback": 1}
    assert s["latency_ms"]["max"] == 100
    assert s["recent_errors"][-1]["error"] == "boom"


def test_summarize_empty() -> None:
    s = summarize([])
    assert s["total"] == 0 and s["error_rate"] == 0.0
    assert s["latency_ms"]["p50"] is None


# --------------------------------------------------------------------------- #
# CLI surface
# --------------------------------------------------------------------------- #

def test_events_cli_summary(tmp_path, capsys) -> None:
    p = tmp_path / "ev.jsonl"
    _seed(p)
    assert events_cli(["--path", str(p)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["total"] == 4 and out["log"] == str(p)


def test_events_cli_tail(tmp_path, capsys) -> None:
    p = tmp_path / "ev.jsonl"
    _seed(p)
    assert events_cli(["--path", str(p), "--tail", "2"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 2 and json.loads(lines[-1])["tool"] == "click"


def test_events_cli_errors_filter(tmp_path, capsys) -> None:
    p = tmp_path / "ev.jsonl"
    _seed(p)
    events_cli(["--path", str(p), "--tail", "10", "--errors"])
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["tool"] == "click"


def test_events_cli_disabled(monkeypatch, capsys) -> None:
    monkeypatch.setenv("SERVO_AGENT_LOG", "off")
    assert events_cli([]) == 0
    assert "disabled" in json.loads(capsys.readouterr().out)["error"]


# --------------------------------------------------------------------------- #
# distill metadata (feeds read_page events)
# --------------------------------------------------------------------------- #

def test_distill_meta_reports_extractor_and_ratio() -> None:
    html = "<html><body>" + "<p>word</p>" * 50 + "</body></html>"
    md, meta = _distill(html, max_chars=12000)
    assert meta["extractor"] in {"trafilatura", "fallback"}
    assert meta["in_chars"] == len(html)
    assert meta["out_chars"] == len(md)
    assert meta["ratio"] > 0 and meta["truncated"] is False


def test_distill_meta_flags_truncation() -> None:
    body = "<p>filler sentence here</p>" * 200
    html = f"<html><body><article>{body}</article></body></html>"
    md, meta = _distill(html, max_chars=100)
    assert meta["truncated"] is True and len(md) > 100  # marker appended past cap
