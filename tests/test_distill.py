"""Unit tests for DOM → markdown distillation. No engine required."""
from __future__ import annotations

from servo_agent.distill import _fallback_markdown, distill


def test_fallback_strips_nav_and_cookie_noise(sample_html: str) -> None:
    md = _fallback_markdown(sample_html).lower()
    assert "primary article body" in md          # main content kept
    assert "accept all cookies" not in md         # consent banner stripped
    assert "nav menu" not in md                   # nav chrome stripped
    assert "footer chrome" not in md              # footer stripped


def test_fallback_keeps_main_links(sample_html: str) -> None:
    md = _fallback_markdown(sample_html)
    assert "https://example.com/one" in md or "Result One" in md


def test_distill_returns_markdown(sample_html: str) -> None:
    md = distill(sample_html, url="https://test.local/sample")
    assert "Primary Title" in md
    assert len(md) > 0


def test_distill_truncates() -> None:
    big = "<main>" + "<p>lorem ipsum dolor sit amet </p>" * 2000 + "</main>"
    md = distill(big, max_chars=200)
    assert len(md) <= 200 + 60
    assert "truncated" in md


def test_distill_handles_empty() -> None:
    assert isinstance(distill("", url=""), str)
