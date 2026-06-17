"""End-to-end self-test — drives a real page through the whole stack, no MCP client."""
from __future__ import annotations

import json

from .browser import ServoBrowser
from .distill import distill


def _hdr(t: str) -> None:
    print(f"\n\033[1m▶ {t}\033[0m")


def run_selftest(url: str = "https://news.ycombinator.com") -> int:
    with ServoBrowser(headless=True) as b:
        _hdr("open_url")
        state = b.navigate(url)
        print(f"  title = {b.title()!r}")
        print(f"  url   = {b.current_url()!r}  readyState={state}")

        _hdr("wait_for_selector('a') + extract_links")
        b.wait_for_selector("a", timeout=10)
        links = b.extract_links("a")
        print(f"  {len(links)} links; first = {links[0] if links else None}")

        _hdr("eval_js — page facts")
        facts = b.eval_js(
            "return {h: document.querySelectorAll('h1,h2,h3').length, "
            "p: document.querySelectorAll('p').length, ua: navigator.userAgent}"
        )
        print(f"  {json.dumps(facts)}")

        _hdr("read_page — DOM → markdown digest")
        html = b.read_html()
        md = distill(html, b.current_url(), max_chars=2000)
        print(f"  raw {len(html):,} chars → markdown {len(md):,} chars "
              f"({100 * len(md) / max(len(html), 1):.1f}% of raw)")
        print("\n".join("  | " + ln for ln in md[:800].splitlines()))

        _hdr("screenshot")
        print(f"  wrote {b.screenshot('servo-selftest.png')}")

    print("\n\033[1;32m✓ self-test passed\033[0m")
    return 0
