#!/usr/bin/env python3
"""Use case 6 — the universal primitive: any URL → clean markdown on stdout.

    uv run python examples/universal_read.py https://example.com
"""
from __future__ import annotations

import sys

from servo_agent import ServoBrowser, distill


def read(url: str, max_chars: int = 12000) -> str:
    with ServoBrowser(headless=True) as b:
        b.navigate(url)
        return distill(b.read_html(), b.current_url(), max_chars=max_chars)


if __name__ == "__main__":
    print(read(sys.argv[1] if len(sys.argv) > 1 else "https://example.com"))
