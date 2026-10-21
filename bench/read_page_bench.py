#!/usr/bin/env python3
"""Benchmark: raw rendered HTML vs distilled markdown across real sites.

Measures the reduction distillation achieves on the post-render DOM. The
markdown column is distilled WITHOUT read_page's default 12,000-character cap,
so the ratio is the distillation's and not the cap's; the last column shows
what read_page actually returns with its default cap.
Reproducible: spawns its own headless servoshell via ServoBrowser.

    SERVOSHELL=/path/to/servoshell uv run python bench/read_page_bench.py
"""
from __future__ import annotations

import sys
import time

from servo_agent import ServoBrowser, distill

SITES = [
    "https://example.com",
    "https://en.wikipedia.org/wiki/Web_browser",
    "https://news.ycombinator.com",
    "https://playwright.dev/docs/intro",
    "https://www.rfc-editor.org/rfc/rfc2616",
]


def human(n: int) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.1f}GB"


READ_PAGE_CAP = 12_000  # read_page's default max_chars


def main(urls: list[str]) -> int:
    rows = []
    with ServoBrowser(headless=True) as b:
        for url in urls:
            try:
                b.navigate(url)
                time.sleep(0.5)
                raw = b.eval_js("return document.documentElement.outerHTML.length") or 0
                md = distill(b.read_html(), b.current_url(), max_chars=10**9)
                ratio = (raw / len(md)) if md else 0
                rows.append((url, int(raw), len(md), ratio))
            except Exception as e:  # noqa: BLE001
                rows.append((url, 0, 0, 0))
                print(f"  ! {url}: {e}", file=sys.stderr)

    print(f"\n{'Site':<40} {'raw HTML':>10} {'markdown':>10} {'reduction':>10} "
          f"{'read_page':>16}")
    print("-" * 90)
    tot_raw = tot_md = 0
    for url, raw, md, ratio in rows:
        site = url.replace("https://", "")[:38]
        sent = human(min(md, READ_PAGE_CAP)) + (" (capped)" if md > READ_PAGE_CAP else "")
        print(f"{site:<40} {human(raw):>10} {human(md):>10} {ratio:>9.0f}× {sent:>16}")
        tot_raw += raw
        tot_md += md
    overall = (tot_raw / tot_md) if tot_md else 0
    print("-" * 90)
    print(f"{'TOTAL':<40} {human(tot_raw):>10} {human(tot_md):>10} {overall:>9.0f}×")
    print(f"\nDistillation turned {human(tot_raw)} of rendered HTML into "
          f"{human(tot_md)} of markdown, {overall:.0f}× smaller in total. read_page "
          f"returns at most {READ_PAGE_CAP:,} characters unless max_chars is raised.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or SITES))
