#!/usr/bin/env python3
"""Adapter: a cron/`schedule`-skill routine that watches a page value.

Designed to be the command a scheduled agent runs. Reads a watch spec, extracts
a value (CSS text or a JS expression), diffs against the last run, and prints a
single-line verdict. Exit code 1 == changed (so a routine can branch / notify).

    uv run python integrations/schedule_watch.py watch.json

watch.json:
    {"url": "https://site/pricing", "selector": ".price"}            # by selector
    {"url": "https://site",          "js": "return document.title"}  # by JS expression
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from servo_agent import ServoBrowser

STATE_DIR = Path(__file__).parent / ".schedule-state"


def probe(spec: dict) -> str | None:
    with ServoBrowser(headless=True) as b:
        b.navigate(spec["url"])
        if "js" in spec:
            return str(b.eval_js(spec["js"]))
        selector = spec.get("selector", "h1")
        try:
            b.wait_for_selector(selector, timeout=10)
        except TimeoutError:
            return None
        ids = b.find_all(selector)
        return b.element_text(ids[0]) if ids else None


def run(spec: dict) -> int:
    value = probe(spec)
    STATE_DIR.mkdir(exist_ok=True)
    key = hashlib.sha1(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16]
    state_file = STATE_DIR / f"{key}.json"
    previous = json.loads(state_file.read_text())["value"] if state_file.exists() else None
    changed = value != previous
    state_file.write_text(json.dumps({"spec": spec, "value": value}))
    verdict = "CHANGED" if changed else "unchanged"
    print(f"[{verdict}] {spec['url']} :: {value!r}" + (f" (was {previous!r})" if changed else ""))
    return 1 if changed else 0


if __name__ == "__main__":
    spec = json.loads(open(sys.argv[1]).read()) if len(sys.argv) > 1 else {"url": "https://example.com"}
    raise SystemExit(run(spec))
