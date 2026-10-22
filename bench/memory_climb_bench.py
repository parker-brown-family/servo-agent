#!/usr/bin/env python3
"""Benchmark: the engine's memory over many navigations in one session (issue #14).

Opens the same four pages in turn, N times in all, in one ServoBrowser, and
records the engine's PSS after every page, plus every restart the memory cap
caused. Servo's memory climbs with every page in one window: 0.7.0 went from
334 MB to 5,279 MB over 100 navigations on 2026-10-22, so ServoBrowser
restarts the engine before the next page once it passes `memory_cap_mb`.
Linux only (PSS is read from /proc).

    SERVOSHELL=/path/to/servoshell uv run python bench/memory_climb_bench.py [N] [cap_mb]

`cap_mb` 0 turns the restarts off, which measures the engine's own climb.
"""
from __future__ import annotations

import json
import sys
import time

from servo_agent import ServoBrowser

PAGES = [
    "https://servo.org/about/",
    "https://en.wikipedia.org/wiki/Web_browser",
    "https://playwright.dev/docs/intro",
    "https://news.ycombinator.com/",
]


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    cap = int(sys.argv[2]) if len(sys.argv) > 2 else ServoBrowser.DEFAULT_MEMORY_CAP_MB
    rows = []
    with ServoBrowser(headless=True, memory_cap_mb=cap) as b:
        for i in range(n):
            url = PAGES[i % len(PAGES)]
            t0 = time.monotonic()
            state = b.navigate(url)
            rows.append({
                "i": i + 1, "url": url, "open_s": round(time.monotonic() - t0, 2),
                "state": state, "pss_mb": b.memory_mb(),
                "restarted_from_mb": (b.last_restart or {}).get("pss_mb"),
            })
            print(json.dumps(rows[-1]), file=sys.stderr, flush=True)
        version = b.engine_version
    known = [r["pss_mb"] for r in rows if r["pss_mb"] is not None]
    print(json.dumps({
        "engine": version, "binary": str(b.binary), "navigations": n, "cap_mb": cap,
        "peak_pss_mb": max(known) if known else None,
        "last_pss_mb": known[-1] if known else None,
        "restarts": sum(r["restarted_from_mb"] is not None for r in rows),
        "rows": rows,
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
