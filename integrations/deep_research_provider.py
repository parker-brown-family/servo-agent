#!/usr/bin/env python3
"""Adapter: a clean source-fetcher for the `deep-research` skill.

Replaces raw `WebFetch` (raw/JS-blocked HTML) with Servo-rendered, distilled
markdown. Use `fetch_sources()` from Python, or the CLI to emit JSON the skill
can consume.

    uv run python integrations/deep_research_provider.py URL1 URL2 ...
    echo -e "URL1\\nURL2" | uv run python integrations/deep_research_provider.py -
"""
from __future__ import annotations

import json
import sys

from servo_agent import ServoBrowser, distill


def fetch_sources(urls: list[str], max_chars: int = 6000) -> list[dict]:
    """Return [{url, title, markdown, links}] — one entry per source (errors captured)."""
    results: list[dict] = []
    with ServoBrowser(headless=True) as b:
        for url in urls:
            try:
                b.navigate(url)
                results.append({
                    "url": b.current_url(),
                    "title": b.title(),
                    "markdown": distill(b.read_html(), b.current_url(), max_chars),
                    "links": [link["href"] for link in b.extract_links("main a")][:30],
                })
            except Exception as e:  # noqa: BLE001
                results.append({"url": url, "error": str(e)})
    return results


def _read_urls(argv: list[str]) -> list[str]:
    if argv == ["-"]:
        return [ln.strip() for ln in sys.stdin if ln.strip()]
    return argv


if __name__ == "__main__":
    urls = _read_urls(sys.argv[1:]) or ["https://example.com"]
    print(json.dumps(fetch_sources(urls), indent=2))
