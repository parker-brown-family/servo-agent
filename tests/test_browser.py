"""Integration tests — drive a real servoshell against a local file:// fixture.

Marked `integration`; auto-skipped when no servoshell binary is present.
"""
from __future__ import annotations

import struct

import pytest

pytestmark = pytest.mark.integration


def _png_size(data: bytes) -> tuple[int, int]:
    """Parse a PNG's pixel dimensions from its IHDR chunk."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    width, height = struct.unpack(">II", data[16:24])
    return width, height


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


def test_wait_for_load_returns_complete(browser, sample_url: str) -> None:
    # A static page is already settled; wait_for_load should return promptly.
    browser.navigate(sample_url)
    assert browser.wait_for_load(timeout=5) == "complete"


def test_navigate_settle_returns_complete(browser, sample_url: str) -> None:
    # navigate(settle=True) routes through wait_for_load and still yields complete.
    assert browser.navigate(sample_url, settle=True) == "complete"
    assert browser.title() == "Sample Page — servo-agent tests"


def test_get_errors_returns_list(browser, sample_url: str) -> None:
    # The fixture throws nothing → a clean page reports an empty error list.
    browser.navigate(sample_url)
    errs = browser.get_errors()
    assert isinstance(errs, list)
    assert errs == []


def test_get_errors_captures_thrown(browser, sample_url: str) -> None:
    # An error thrown after the collector is installed is captured + shaped.
    browser.navigate(sample_url)
    browser.eval_js(
        "window.dispatchEvent(new ErrorEvent('error', "
        "{message: 'kaboom', filename: 'unit.js', lineno: 7})); return 1"
    )
    errs = browser.get_errors()
    assert any(
        e.get("message") == "kaboom" and e.get("type") == "error" for e in errs
    ), errs
    one = next(e for e in errs if e.get("message") == "kaboom")
    assert set(one) >= {"type", "message", "source", "line", "col"}


def test_screenshot_default_unchanged(browser, sample_url: str, tmp_path) -> None:
    # Default capture still works and writes a real PNG to the given path.
    browser.navigate(sample_url)
    out = browser.screenshot(str(tmp_path / "default.png"))
    data = (tmp_path / "default.png").read_bytes()
    assert out.endswith("default.png")
    w, h = _png_size(data)
    assert w > 0 and h > 0


def test_screenshot_width_height(browser, sample_url: str, tmp_path) -> None:
    # Explicit width/height resizes the window → PNG matches that width exactly,
    # and the height is in the right ballpark (window chrome trims a little).
    browser.navigate(sample_url)
    browser.screenshot(str(tmp_path / "sized.png"), width=640, height=900)
    w, h = _png_size((tmp_path / "sized.png").read_bytes())
    assert w == 640
    assert 700 <= h <= 900


def test_screenshot_full_page_taller(browser, tmp_path) -> None:
    # On a document taller than the viewport, full_page grows the capture so it
    # is meaningfully taller than a same-width fixed-height shot.
    tall = (
        "<html><body style='margin:0'>"
        + "".join(
            f"<p style='height:50px;margin:0'>row {i}</p>" for i in range(60)
        )
        + "</body></html>"
    )
    page = tmp_path / "tall.html"
    page.write_text(tall, encoding="utf-8")
    browser.navigate(page.resolve().as_uri())

    fixed = tmp_path / "_fixed.png"
    browser.screenshot(str(fixed), width=600, height=400)
    fixed_w, fixed_h = _png_size(fixed.read_bytes())

    full = tmp_path / "_full.png"
    browser.screenshot(str(full), width=600, full_page=True)
    full_w, full_h = _png_size(full.read_bytes())

    assert full_w == fixed_w == 600
    assert full_h > fixed_h
    assert full_h >= 2000  # ~60 rows * 50px, minus chrome, comfortably exceeded


def test_read_native(browser, sample_url: str) -> None:
    # Native /servo/agent/read; skip on a servoshell that predates the endpoint.
    browser.navigate(sample_url)
    out = browser.read_native()
    if out is None:
        import pytest

        pytest.skip("servoshell lacks the native /servo/agent/read endpoint")
    assert out["title"] == "Sample Page — servo-agent tests"
    assert "Primary Title" in out["text"]
    assert any(h["text"] == "Primary Title" for h in out["headings"])
    assert any("example.com" in link["href"] for link in out["links"])


def browser_read(browser) -> str:
    from servo_agent.distill import distill

    return distill(browser.read_html(), browser.current_url())
