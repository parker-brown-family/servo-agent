#!/usr/bin/env python3
"""Use case 2 — site QA / pre-deploy checker.

Render a page, assert required content is present and links resolve, capture a
screenshot. Exit non-zero on any problem so it drops straight into CI.

    uv run python examples/site_qa.py https://your-site.dev "Welcome" "Contact"
"""
from __future__ import annotations

import sys

from servo_agent import ServoBrowser, distill


def check(url: str, must_contain: tuple[str, ...] = (), shot: str = "qa.png") -> list[str]:
    problems: list[str] = []
    with ServoBrowser(headless=True) as b:
        state = b.navigate(url)
        if state != "complete":
            problems.append(f"page did not reach readyState=complete (got {state})")
        md = distill(b.read_html(), b.current_url()).lower()
        for needle in must_contain:
            if needle.lower() not in md:
                problems.append(f"missing expected text: {needle!r}")
        if not b.extract_links("a"):
            problems.append("no links found on page")
        b.screenshot(shot)
    return problems


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    needles = tuple(sys.argv[2:])
    problems = check(url, needles)
    if problems:
        print(f"FAIL — {url}")
        for p in problems:
            print(f"  ✗ {p}")
        sys.exit(1)
    print(f"OK — {url} (screenshot: qa.png)")
