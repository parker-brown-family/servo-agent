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


def test_screenshot_of_a_page_whose_image_never_arrives(browser, tmp_path) -> None:
    # Issue #3: Servo will not capture a page while an image is still loading, and
    # times out after 10 s. ServoBrowser drops the unfinished image and retries.
    import http.server
    import threading
    import time

    class NeverArrives(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — the stdlib's name
            if self.path.startswith("/never/"):
                time.sleep(60)
                return
            body = (b"<!doctype html><html><body><h1>readable</h1>"
                    b"<img src='/never/arrives.png'></body></html>")
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), NeverArrives)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        browser.navigate(f"http://127.0.0.1:{server.server_address[1]}/page.html")
        t0 = time.monotonic()
        shot = tmp_path / "_pending.png"
        browser.screenshot(str(shot))
        assert time.monotonic() - t0 < 20
        assert _png_size(shot.read_bytes())[0] > 0
        dropped = browser.last_screenshot.get("dropped_unfinished_images")
        # A Servo that stops waiting on images captures at once and drops nothing.
        assert dropped is None or dropped[0].endswith("/never/arrives.png")
    finally:
        server.shutdown()


def test_screenshot_full_page_reaches_the_bottom_of_a_tall_page(browser, tmp_path) -> None:
    # Servo's default headless screen let a window grow to 2,960 px, so a 6,000 px
    # page came back cut in half with nothing said (2026-10-22). The engine is now
    # launched with a taller screen, and the shot says whether it was cut.
    page = tmp_path / "taller.html"
    page.write_text("<html><body style='margin:0'>" + "".join(
        f"<div style='height:500px'>block {i}</div>" for i in range(12)) + "</body></html>",
        encoding="utf-8")
    browser.navigate(page.resolve().as_uri())

    shot = tmp_path / "_taller.png"
    browser.screenshot(str(shot), width=600, full_page=True)

    assert _png_size(shot.read_bytes())[1] >= 6000
    assert browser.last_screenshot["page_height"] >= 6000
    assert browser.last_screenshot["cut_short"] is False


def _fixture_url(name: str) -> str:
    from pathlib import Path

    return (Path(__file__).parent / "fixtures" / name).resolve().as_uri()


def test_click_follows_a_link_and_the_destination_reads(browser) -> None:
    # Issue #4: the engine rejected the click request itself (empty body → 400).
    browser.navigate(_fixture_url("link_source.html"))
    browser.click_selector("a#next")
    assert browser.title() == "Link Destination — servo-agent tests"
    assert "The click arrived" in browser_read(browser)


def test_back_returns_to_the_previous_page(browser) -> None:
    browser.navigate(_fixture_url("link_source.html"))
    browser.navigate(_fixture_url("link_destination.html"))
    browser.back()
    assert browser.title() == "Link Source — servo-agent tests"


def test_reload_replaces_the_document(browser) -> None:
    browser.navigate(_fixture_url("link_source.html"))
    browser.eval_js("document.__staleMarker = true; return 1")
    browser.reload()
    assert browser.eval_js("return document.__staleMarker === undefined")


@pytest.mark.xfail(
    reason=(
        "Servo engine bug (#5): the window a click navigated away from keeps "
        "WebDriver's load-status sender, so after back() a refresh receives a "
        "stray NavigationStart and answers 500"
    ),
    strict=False,
)
def test_reload_after_click_and_back() -> None:
    from servo_agent.browser import ServoBrowser

    # Its own engine: the failure leaves the session's load-status channel dirty.
    with ServoBrowser(headless=True) as b:
        b.navigate(_fixture_url("link_source.html"))
        b.click_selector("a#next")
        b.back()
        b.reload()
        assert b.title() == "Link Source — servo-agent tests"


def test_reopening_the_same_url_reads_the_new_document(browser, sample_url: str) -> None:
    # The old document reports the same URL and `complete`; a navigate() that
    # trusted those returned before the new one arrived, and the next read hit
    # a document mid-teardown.
    browser.navigate(sample_url)
    browser.eval_js("document.__staleMarker = true; return 1")
    for _ in range(5):
        browser.navigate(sample_url)
        assert browser.eval_js("return document.__staleMarker === undefined")
        assert browser.element_text(browser.find_all("h1")[0]) == "Primary Title"


def test_fragment_navigation_keeps_the_document(browser, sample_url: str) -> None:
    # `#anchor` on the page you are on scrolls; no new document arrives, so the
    # token never disappears and navigate() must recognise the case up front.
    import time

    browser.navigate(sample_url)
    browser.eval_js("document.__sameDocument = true; return 1")
    started = time.monotonic()
    assert browser.navigate(sample_url + "#data", timeout=10) == "complete"
    assert time.monotonic() - started < 5
    assert browser.eval_js("return document.__sameDocument === true")


def browser_read(browser) -> str:
    from servo_agent.distill import distill

    return distill(browser.read_html(), browser.current_url())
