#!/usr/bin/env python3
"""Use case 4 — bot-walled scrape fallback: a JS-rendering engine you own.

When a cheap HTTP fetch gets blocked or returns an empty JS shell, render the
page in Servo, scroll to trigger lazy content, and emit distilled markdown +
links as JSON.

    uv run python examples/scrape_fallback.py https://js-heavy.example
"""
from __future__ import annotations

import json
import sys

from servo_agent import ServoBrowser, distill


def scrape(url: str) -> dict:
    with ServoBrowser(headless=True) as b:
        b.navigate(url)
        b.scroll("bottom")   # nudge lazy/infinite content into the DOM
        return {
            "url": b.current_url(),
            "title": b.title(),
            "markdown": distill(b.read_html(), b.current_url()),
            "links": b.extract_links("a")[:50],
        }


if __name__ == "__main__":
    print(json.dumps(scrape(sys.argv[1] if len(sys.argv) > 1 else "https://example.com"), indent=2))
