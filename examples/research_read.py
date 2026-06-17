#!/usr/bin/env python3
"""Use case 1 — research source-reader: read several URLs as clean markdown.

Distilled markdown is ~100-200x smaller than raw HTML, so an agent can afford to
read many sources per context budget. Emits a JSON array of {url, title, markdown}.

    uv run python examples/research_read.py URL1 URL2 URL3
"""
from __future__ import annotations

import json
import sys

from servo_agent import ServoBrowser, distill


def read_sources(urls: list[str], max_chars: int = 8000) -> list[dict]:
    docs: list[dict] = []
    with ServoBrowser(headless=True) as b:
        for url in urls:
            try:
                b.navigate(url)
                docs.append({
                    "url": b.current_url(),
                    "title": b.title(),
                    "markdown": distill(b.read_html(), b.current_url(), max_chars),
                })
            except Exception as e:  # noqa: BLE001 — one bad source shouldn't kill the run
                docs.append({"url": url, "error": str(e)})
    return docs


if __name__ == "__main__":
    urls = sys.argv[1:] or ["https://example.com"]
    print(json.dumps(read_sources(urls), indent=2))
