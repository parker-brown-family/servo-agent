"""MCP server — exposes ServoBrowser as agent-shaped tools over stdio.

A single lazily-started browser instance backs all tools; it is torn down at
process exit. Wired into Claude Code / Codex as the `servo-agent` MCP server.
"""
from __future__ import annotations

import atexit
import json

from .browser import ServoBrowser
from .distill import distill

_BROWSER = ServoBrowser(headless=True)
atexit.register(_BROWSER.shutdown)


def build_mcp():
    """Construct the FastMCP server. Imported lazily so unit tests need no mcp dep."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("servo-agent")

    @mcp.tool()
    def open_url(url: str) -> str:
        """Navigate the Servo engine to a URL. Returns title + final URL once loaded."""
        state = _BROWSER.navigate(url)
        return json.dumps(
            {"title": _BROWSER.title(), "url": _BROWSER.current_url(), "readyState": state}
        )

    @mcp.tool()
    def read_page(max_chars: int = 12000) -> str:
        """Read the CURRENT page as clean, token-efficient markdown (main content)."""
        return distill(_BROWSER.read_html(), _BROWSER.current_url(), max_chars=max_chars)

    @mcp.tool()
    def find(selector: str) -> str:
        """Find elements by CSS selector. Returns count + first few elements' text."""
        ids = _BROWSER.find_all(selector)
        sample = [{"text": (_BROWSER.element_text(i) or "")[:160]} for i in ids[:10]]
        return json.dumps({"selector": selector, "count": len(ids), "sample": sample})

    @mcp.tool()
    def wait_for_selector(selector: str, timeout: float = 10.0, visible: bool = False) -> str:
        """Wait until >=1 element matches a CSS selector (optionally visible)."""
        try:
            n = _BROWSER.wait_for_selector(selector, timeout=timeout, visible=visible)
            return json.dumps({"selector": selector, "present": True, "count": n})
        except TimeoutError as e:
            return json.dumps({"selector": selector, "present": False, "error": str(e)})

    @mcp.tool()
    def click(selector: str) -> str:
        """Click the first element matching a CSS selector."""
        _BROWSER.click_selector(selector)
        return json.dumps({"clicked": selector, "url": _BROWSER.current_url()})

    @mcp.tool()
    def type_text(selector: str, text: str) -> str:
        """Type text into the first element matching a CSS selector."""
        _BROWSER.type_selector(selector, text)
        return json.dumps({"typed_into": selector, "chars": len(text)})

    @mcp.tool()
    def fill_form(fields: dict, submit: str = "") -> str:
        """Fill a form: map of {css_selector: value}; optionally click `submit`."""
        _BROWSER.fill_form(fields, submit or None)
        return json.dumps({"filled": list(fields), "submitted": bool(submit),
                           "url": _BROWSER.current_url()})

    @mcp.tool()
    def scroll(to: str = "bottom") -> str:
        """Scroll the page: 'bottom', 'top', a CSS selector, or a pixel y value."""
        _BROWSER.scroll(to)
        return json.dumps({"scrolled": to})

    @mcp.tool()
    def extract_links(selector: str = "a") -> str:
        """Extract links under a selector as a JSON list of {text, href} (absolute)."""
        return json.dumps(_BROWSER.extract_links(selector))

    @mcp.tool()
    def extract_table(selector: str = "table") -> str:
        """Extract the first matching <table> as a JSON list of row objects."""
        return json.dumps(_BROWSER.extract_table(selector))

    @mcp.tool()
    def eval_js(script: str) -> str:
        """Execute JavaScript in the page (use 'return ...') and get the JSON result."""
        return json.dumps({"result": _BROWSER.eval_js(script)})

    @mcp.tool()
    def screenshot(path: str = "servo-shot.png") -> str:
        """Capture a PNG screenshot of the current page. Returns the absolute path."""
        return json.dumps({"path": _BROWSER.screenshot(path)})

    @mcp.tool()
    def status() -> str:
        """Report engine/session status."""
        return json.dumps(_BROWSER.status())

    return mcp


def serve() -> None:
    build_mcp().run()
