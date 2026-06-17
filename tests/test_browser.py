"""Integration tests — drive a real servoshell against a local file:// fixture.

Marked `integration`; auto-skipped when no servoshell binary is present.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_navigate_and_title(browser, sample_url: str) -> None:
    browser.navigate(sample_url)
    assert browser.title() == "Sample Page — servo-agent tests"
    assert browser.current_url().endswith("sample.html")


def test_find_and_text(browser, sample_url: str) -> None:
    browser.navigate(sample_url)
    ids = browser.find_all("h1")
    assert len(ids) == 1
    assert browser.element_text(ids[0]) == "Primary Title"


def test_wait_for_selector(browser, sample_url: str) -> None:
    browser.navigate(sample_url)
    assert browser.wait_for_selector("table#data", timeout=5) >= 1
    with pytest.raises(TimeoutError):
        browser.wait_for_selector("div#never", timeout=1)


def test_extract_table(browser, sample_url: str) -> None:
    browser.navigate(sample_url)
    rows = browser.extract_table("table#data")
    assert rows == [
        {"Name": "Alice", "Points": "120"},
        {"Name": "Bob", "Points": "98"},
    ]


def test_extract_links(browser, sample_url: str) -> None:
    browser.navigate(sample_url)
    hrefs = {link["href"] for link in browser.extract_links("main a")}
    assert "https://example.com/one" in hrefs
    assert "https://example.com/two" in hrefs


def test_read_page_is_clean(browser, sample_url: str) -> None:
    browser.navigate(sample_url)
    md = browser_read(browser)
    assert "Primary Title" in md
    assert "ACCEPT ALL COOKIES" not in md


def browser_read(browser) -> str:
    from servo_agent.distill import distill

    return distill(browser.read_html(), browser.current_url())
