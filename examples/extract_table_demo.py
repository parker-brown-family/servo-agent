#!/usr/bin/env python3
"""Use case 5 — structured data extraction: an HTML table → JSON (+ optional CSV).

    uv run python examples/extract_table_demo.py https://site/stats "table#data" out.csv
"""
from __future__ import annotations

import csv
import json
import sys

from servo_agent import ServoBrowser


def extract(url: str, selector: str = "table") -> list[dict]:
    with ServoBrowser(headless=True) as b:
        b.navigate(url)
        b.wait_for_selector(selector, timeout=10)
        return b.extract_table(selector)


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    selector = sys.argv[2] if len(sys.argv) > 2 else "table"
    rows = extract(url, selector)
    print(json.dumps(rows, indent=2))
    if len(sys.argv) > 3 and rows:
        with open(sys.argv[3], "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\n# wrote {len(rows)} rows -> {sys.argv[3]}", file=sys.stderr)
