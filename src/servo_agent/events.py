"""Structured tool-call event log — the product feedback loop.

Every MCP tool call is recorded as one JSON line: which tool, clipped args,
latency, success/error, result size, engine state (external/respawned), and
tool-specific enrichment (distill extractor + compression ratio, native-read
availability). The consumer is **agentic**, not a human dashboard: an agent reads
the JSONL directly, or runs `servo-agent events` to get a rolled-up summary it can
turn into T1 findings.

Design constraints:
- **std-lib only** (no new dependencies) and **never fatal** — a logging failure
  must never break a tool call.
- **client-agnostic** — wired into the MCP server, so it captures stdio
  (Claude/Codex), the HTTP daemon, and library use alike.
- **read-side safe** — string args are clipped and `dict` args (e.g. form values)
  are redacted to key + length, so the log can't become a credential sink.

Log location: ``$SERVO_AGENT_LOG`` (a path), else ``~/.servo-agent/events.jsonl``.
Set ``SERVO_AGENT_LOG=off`` (or ``0``/``none``/empty) to disable entirely.
"""
from __future__ import annotations

import functools
import inspect
import json
import math
import os
import threading
from collections.abc import Callable
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# A per-call scratchpad a tool body can enrich via record_meta(); the instrument
# wrapper drains it into the event. ContextVar so it's isolated per call even if
# FastMCP runs sync tools on worker threads.
_META: ContextVar[dict | None] = ContextVar("servo_agent_event_meta", default=None)

_CLIP = 200  # max chars kept per string arg before truncation


def record_meta(**fields: Any) -> None:
    """Attach tool-specific fields to the in-flight event (no-op outside a call)."""
    bag = _META.get()
    if bag is not None:
        bag.update(fields)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _clip_val(v: Any) -> Any:
    """Shrink/redact one arg value for the log."""
    if isinstance(v, str):
        return v if len(v) <= _CLIP else v[:_CLIP] + f"…(+{len(v) - _CLIP})"
    if isinstance(v, dict):
        # Values may be form input (passwords, PII) — keep shape, drop content.
        return {
            k: (f"<{len(x)} chars>" if isinstance(x, str) else _clip_val(x))
            for k, x in v.items()
        }
    if isinstance(v, (list, tuple)):
        return [_clip_val(x) for x in list(v)[:20]]
    return v


def _clip_args(sig: inspect.Signature, args: tuple, kwargs: dict) -> dict:
    bound = sig.bind(*args, **kwargs)
    bound.apply_defaults()
    return {k: _clip_val(v) for k, v in bound.arguments.items()}


class EventLog:
    """Append-only JSONL writer. ``path=None`` means logging is disabled."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> EventLog:
        raw = os.environ.get("SERVO_AGENT_LOG")
        if raw is not None:
            if raw.strip().lower() in ("", "off", "0", "none", "false"):
                return cls(None)
            return cls(Path(raw).expanduser())
        return cls(Path.home() / ".servo-agent" / "events.jsonl")

    def write(self, event: dict) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(event, separators=(",", ":"), ensure_ascii=False)
            with self._lock, self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:  # noqa: BLE001 — logging must never break a tool call
            pass


def make_logger(browser: Any, log: EventLog) -> Callable[[str], Callable]:
    """Build a ``@logged("tool")`` decorator bound to one browser + log.

    Stacks UNDER ``@mcp.tool()`` (so FastMCP still sees the real signature via
    ``functools.wraps``). Records timing, success/error, result size, and engine
    state for every call; tool bodies add detail with :func:`record_meta`.
    """

    def logged(name: str) -> Callable:
        def deco(fn: Callable) -> Callable:
            sig = inspect.signature(fn)

            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                pid_before = browser.proc.pid if getattr(browser, "proc", None) else None
                token = _META.set({})
                start = _monotonic_ms()
                ok, err, etype, result = True, None, None, None
                try:
                    result = fn(*args, **kwargs)
                    return result
                except Exception as e:  # noqa: BLE001 — log then re-raise
                    ok, err, etype = False, str(e), type(e).__name__
                    raise
                finally:
                    elapsed = round(_monotonic_ms() - start, 1)
                    meta = _META.get() or {}
                    _META.reset(token)
                    try:
                        clipped = _clip_args(sig, args, kwargs)
                    except Exception:  # noqa: BLE001
                        clipped = {}
                    pid_after = browser.proc.pid if getattr(browser, "proc", None) else None
                    event: dict[str, Any] = {
                        "ts": _now_iso(),
                        "tool": name,
                        "ok": ok,
                        "ms": elapsed,
                        "args": clipped,
                    }
                    if isinstance(result, str):
                        event["bytes"] = len(result)
                    engine: dict[str, Any] = {"external": bool(getattr(browser, "external", False))}
                    if pid_before != pid_after:
                        engine["respawned"] = True
                    if pid_after is not None:
                        engine["pid"] = pid_after
                    event["engine"] = engine
                    if meta:
                        event.update(meta)
                    if not ok:
                        event["error"] = err
                        event["error_type"] = etype
                    log.write(event)

            return wrapper

        return deco

    return logged


def _monotonic_ms() -> float:
    import time

    return time.perf_counter() * 1000.0


# --------------------------------------------------------------------------- #
# Reading / summarizing — what an agent calls to "dig out" the feedback.
# --------------------------------------------------------------------------- #

def read_events(
    path: Path | str,
    *,
    tool: str | None = None,
    errors_only: bool = False,
    since: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Load events (tolerant: bad/partial lines skipped, missing file → [])."""
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if tool and e.get("tool") != tool:
                    continue
                if errors_only and e.get("ok", True):
                    continue
                if since and str(e.get("ts", "")) < since:
                    continue
                out.append(e)
    except FileNotFoundError:
        return []
    if limit is not None:
        out = out[-limit:]
    return out


def _pct(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return sorted_vals[int(k)]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def _round(v: float | None) -> float | None:
    return round(v, 1) if isinstance(v, (int, float)) else None


def summarize(events: list[dict]) -> dict:
    """Roll events into an agent-readable digest: rates, latency, distill ratios."""
    total = len(events)
    by_tool: dict[str, dict[str, int]] = {}
    recent_errors: list[dict] = []
    latencies: list[float] = []
    ratios: list[float] = []
    extractors: dict[str, int] = {}
    ok_count = 0

    for e in events:
        t = e.get("tool", "?")
        bucket = by_tool.setdefault(t, {"calls": 0, "errors": 0})
        bucket["calls"] += 1
        if e.get("ok", True):
            ok_count += 1
        else:
            bucket["errors"] += 1
            recent_errors.append(
                {"ts": e.get("ts"), "tool": t, "error": e.get("error"),
                 "type": e.get("error_type")}
            )
        ms = e.get("ms")
        if isinstance(ms, (int, float)):
            latencies.append(float(ms))
        ratio = e.get("ratio")
        if isinstance(ratio, (int, float)) and ratio > 0:
            ratios.append(float(ratio))
        ex = e.get("extractor")
        if ex:
            extractors[ex] = extractors.get(ex, 0) + 1

    lat = sorted(latencies)
    return {
        "total": total,
        "ok": ok_count,
        "errors": total - ok_count,
        "error_rate": round((total - ok_count) / total, 3) if total else 0.0,
        "by_tool": {
            k: {"calls": v["calls"], "errors": v["errors"]}
            for k, v in sorted(by_tool.items())
        },
        "latency_ms": {
            "p50": _round(_pct(lat, 0.5)),
            "p95": _round(_pct(lat, 0.95)),
            "max": lat[-1] if lat else None,
        },
        "distill": {
            "samples": len(ratios),
            "ratio_avg": round(sum(ratios) / len(ratios), 1) if ratios else None,
            "ratio_min": round(min(ratios), 1) if ratios else None,
            "extractors": extractors,
        },
        "recent_errors": recent_errors[-10:],
    }


_EVENTS_HELP = """servo-agent events — inspect the tool-call feedback log (JSON out)

Usage:
  servo-agent events                 Summary digest (rates, latency, distill ratios)
  servo-agent events --tail N        Last N raw events, oldest first (JSONL)
  servo-agent events --tool NAME     Filter to one tool
  servo-agent events --errors        Only failed calls
  servo-agent events --since ISO     Only events at/after an ISO timestamp prefix
  servo-agent events --path FILE     Read a specific log (else $SERVO_AGENT_LOG)

The log itself is JSONL at $SERVO_AGENT_LOG or ~/.servo-agent/events.jsonl.
"""


def events_cli(argv: list[str]) -> int:
    """`servo-agent events …` — let an agent dig findings out of the log."""
    if "--help" in argv or "-h" in argv:
        print(_EVENTS_HELP)
        return 0

    def opt(flag: str) -> str | None:
        if flag in argv:
            i = argv.index(flag)
            return argv[i + 1] if i + 1 < len(argv) else ""
        return None

    path_arg = opt("--path")
    path = Path(path_arg).expanduser() if path_arg else EventLog.from_env().path
    if path is None:
        print(json.dumps({"error": "logging disabled (SERVO_AGENT_LOG=off)"}))
        return 0

    tool = opt("--tool") or None
    errors_only = "--errors" in argv
    since = opt("--since") or None
    tail_raw = opt("--tail")

    events = read_events(path, tool=tool, errors_only=errors_only, since=since)

    if tail_raw is not None:
        try:
            n = int(tail_raw)
        except ValueError:
            n = 20
        for e in events[-n:]:
            print(json.dumps(e, separators=(",", ":"), ensure_ascii=False))
        return 0

    digest = summarize(events)
    digest["log"] = str(path)
    print(json.dumps(digest, indent=2))
    return 0
