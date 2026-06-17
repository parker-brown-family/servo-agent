#!/usr/bin/env python3
"""Use case 3 — page watcher: extract a value and alert on change (cron-friendly).

Stores the last-seen value next to the script; prints CHANGED/UNCHANGED and exits
non-zero on change so a scheduler/cron can branch on it.

    uv run python examples/watch_page.py https://site/status "#status-badge"
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from servo_agent import ServoBrowser

STATE_DIR = Path(__file__).parent / ".watch-state"


def current_value(url: str, selector: str) -> str | None:
    with ServoBrowser(headless=True) as b:
        b.navigate(url)
        try:
            b.wait_for_selector(selector, timeout=10)
        except TimeoutError:
            return None
        ids = b.find_all(selector)
        return b.element_text(ids[0]) if ids else None


def main(url: str, selector: str) -> int:
    value = current_value(url, selector)
    STATE_DIR.mkdir(exist_ok=True)
    key = hashlib.sha1(f"{url}::{selector}".encode()).hexdigest()[:16]
    state_file = STATE_DIR / f"{key}.json"
    previous = json.loads(state_file.read_text())["value"] if state_file.exists() else None
    changed = value != previous
    state_file.write_text(json.dumps({"url": url, "selector": selector, "value": value}))
    print(json.dumps({"changed": changed, "value": value, "previous": previous}))
    return 1 if changed else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: watch_page.py URL [SELECTOR]", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "h1"))
