#!/usr/bin/env python3
"""Adapter: a pre-deploy verifier for the `verify` skill / CI.

Drives a spec of checks against a URL and exits non-zero on any failure, with a
JSON report. Spec file (JSON):

    {"url": "https://site.dev",
     "must_contain": ["Welcome", "Contact"],
     "must_link_to": ["https://site.dev/pricing"],
     "selector_present": ["nav", "footer"]}

    uv run python integrations/verify_site.py spec.json
"""
from __future__ import annotations

import json
import sys

from servo_agent import ServoBrowser, distill


def verify(spec: dict) -> dict:
    url = spec["url"]
    failures: list[str] = []
    with ServoBrowser(headless=True) as b:
        state = b.navigate(url)
        if state != "complete":
            failures.append(f"readyState={state}")
        md = distill(b.read_html(), b.current_url()).lower()
        for needle in spec.get("must_contain", []):
            if needle.lower() not in md:
                failures.append(f"missing text: {needle!r}")
        hrefs = {link["href"] for link in b.extract_links("a")}
        for href in spec.get("must_link_to", []):
            if href not in hrefs:
                failures.append(f"missing link: {href}")
        for sel in spec.get("selector_present", []):
            if not b.find_all(sel):
                failures.append(f"missing element: {sel}")
        shot = b.screenshot(spec.get("screenshot", "verify.png"))
    return {"url": url, "passed": not failures, "failures": failures, "screenshot": shot}


if __name__ == "__main__":
    spec = json.loads(open(sys.argv[1]).read()) if len(sys.argv) > 1 else {"url": "https://example.com"}
    report = verify(spec)
    print(json.dumps(report, indent=2))
    sys.exit(0 if report["passed"] else 1)
