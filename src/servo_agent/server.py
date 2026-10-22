"""MCP server — exposes ServoBrowser as agent-shaped tools over stdio.

A single lazily-started browser instance backs all tools; it is torn down at
process exit. Wired into Claude Code / Codex as the `servo-agent` MCP server.

Every tool call is recorded to a structured JSONL event log (see
:mod:`servo_agent.events`) — the product feedback loop. Inspect it with
`servo-agent events`; disable it with `SERVO_AGENT_LOG=off`.
"""
from __future__ import annotations

import atexit
import json

from .browser import ServoBrowser
from .distill import _distill
from .events import EventLog, make_logger, record_meta

_BROWSER = ServoBrowser(headless=True)
_LOG = EventLog.from_env()
atexit.register(_BROWSER.shutdown)


def build_mcp():
    """Construct the MCP server. Imported lazily so unit tests need no mcp dep."""
    from mcp.server.mcpserver import MCPServer

    mcp = MCPServer("servo-agent")

    # `@logged("tool")` stacks UNDER `@mcp.tool()`: it records timing / success /
    # result size / engine state for each call while preserving the real function
    # signature (functools.wraps), so the tool schema MCPServer derives is unchanged.
    logged = make_logger(_BROWSER, _LOG)

    @mcp.tool()
    @logged("open_url")
    def open_url(url: str, settle: bool = False) -> str:
        """Navigate the Servo engine to a URL. Returns title + final URL once loaded.

        Set `settle=true` to also wait for the DOM to go quiescent (SPA hydration)
        before returning, so the title/content reflect the rendered page.

        If the engine's memory had passed its cap, it is restarted first and the
        answer carries `engine_restarted`: cookies and history are gone, so a
        site that needs a login needs it again.
        """
        state = _BROWSER.navigate(url, settle=settle)
        out = {"title": _BROWSER.title(), "url": _BROWSER.current_url(), "readyState": state}
        if _BROWSER.last_restart:
            out["engine_restarted"] = _BROWSER.last_restart
            record_meta(engine_restarted=True, restart_pss_mb=_BROWSER.last_restart["pss_mb"])
        return json.dumps(out)

    @mcp.tool()
    @logged("read_page")
    def read_page(max_chars: int = 12000, offset: int = 0) -> str:
        """Read the CURRENT page as clean, token-efficient markdown (main content).

        A page longer than `max_chars` comes in parts. Each part but the last ends
        in a marker naming the offset where the next part starts; pass it back as
        `offset` to read on. Parts never split a link or a code block, and in
        order they add up to the whole page.
        """
        md, meta = _distill(_BROWSER.read_html(), _BROWSER.current_url(),
                            max_chars=max_chars, offset=offset)
        record_meta(**meta)
        return md

    @mcp.tool()
    @logged("find")
    def find(selector: str) -> str:
        """Find elements by CSS selector. Returns count + first few elements' text."""
        ids = _BROWSER.find_all(selector)
        sample = [{"text": (_BROWSER.element_text(i) or "")[:160]} for i in ids[:10]]
        return json.dumps({"selector": selector, "count": len(ids), "sample": sample})

    @mcp.tool()
    @logged("wait_for_selector")
    def wait_for_selector(selector: str, timeout: float = 10.0, visible: bool = False) -> str:
        """Wait until >=1 element matches a CSS selector (optionally visible)."""
        try:
            n = _BROWSER.wait_for_selector(selector, timeout=timeout, visible=visible)
            return json.dumps({"selector": selector, "present": True, "count": n})
        except TimeoutError as e:
            return json.dumps({"selector": selector, "present": False, "error": str(e)})

    @mcp.tool()
    @logged("wait_for_load")
    def wait_for_load(timeout: float = 15.0) -> str:
        """Wait for the page to settle: readyState=complete AND a quiescent DOM.

        Stronger than readyState alone — waits out post-load SPA hydration so a
        following read sees the rendered page. Returns the final readyState. A
        page stuck at `interactive` (a font or beacon that never finishes) whose
        DOM stays unchanged returns after ~2 s with settled=false.
        """
        state = _BROWSER.wait_for_load(timeout=timeout)
        return json.dumps({"readyState": state, "settled": state == "complete"})

    @mcp.tool()
    @logged("get_errors")
    def get_errors() -> str:
        """Read JS errors collected on the current page (best-effort).

        Returns {count, errors:[{type,message,source,line,col}]}. Captures uncaught
        exceptions, unhandled promise rejections, and failed resource loads that
        occur after navigation. Errors thrown during the very first page load
        (before the collector is injected) may be missed — use to triage pages
        that crash to an error boundary.
        """
        errors = _BROWSER.get_errors()
        return json.dumps({"count": len(errors), "errors": errors})

    @mcp.tool()
    @logged("click")
    def click(selector: str) -> str:
        """Click the first element matching a CSS selector."""
        _BROWSER.click_selector(selector)
        return json.dumps({"clicked": selector, "url": _BROWSER.current_url()})

    @mcp.tool()
    @logged("type_text")
    def type_text(selector: str, text: str) -> str:
        """Type text into the first element matching a CSS selector."""
        _BROWSER.type_selector(selector, text)
        return json.dumps({"typed_into": selector, "chars": len(text)})

    @mcp.tool()
    @logged("fill_form")
    def fill_form(fields: dict, submit: str = "") -> str:
        """Fill a form: map of {css_selector: value}; optionally click `submit`."""
        _BROWSER.fill_form(fields, submit or None)
        return json.dumps({"filled": list(fields), "submitted": bool(submit),
                           "url": _BROWSER.current_url()})

    @mcp.tool()
    @logged("scroll")
    def scroll(to: str = "bottom") -> str:
        """Scroll the page: 'bottom', 'top', a CSS selector, or a pixel y value."""
        _BROWSER.scroll(to)
        return json.dumps({"scrolled": to})

    @mcp.tool()
    @logged("extract_links")
    def extract_links(selector: str = "a") -> str:
        """Extract links under a selector as a JSON list of {text, href} (absolute)."""
        return json.dumps(_BROWSER.extract_links(selector))

    @mcp.tool()
    @logged("extract_table")
    def extract_table(selector: str = "table") -> str:
        """Extract the first matching <table> as a JSON list of row objects."""
        return json.dumps(_BROWSER.extract_table(selector))

    @mcp.tool()
    @logged("eval_js")
    def eval_js(script: str) -> str:
        """Execute JavaScript in the page (use 'return ...') and get the JSON result."""
        return json.dumps({"result": _BROWSER.eval_js(script)})

    @mcp.tool()
    @logged("screenshot")
    def screenshot(path: str = "servo-shot.png", width: int = 0, height: int = 0,
                   full_page: bool = False) -> str:
        """Capture a PNG screenshot of the current page. Returns its path and size.

        Optional `width`/`height` resize the window before capture (0 = leave as
        is). `full_page=true` grows the window to fit the document for a whole-page
        shot, up to 20,000 px; the answer says whether a taller page was cut short.
        Servo will not capture while an image is still loading: after its 10 s
        limit, images that never finished are dropped and the capture retried, and
        the answer lists them in `dropped_unfinished_images`.
        """
        out = _BROWSER.screenshot(
            path,
            width=width or None,
            height=height or None,
            full_page=full_page,
        )
        return json.dumps({"path": out, **(_BROWSER.last_screenshot or {})})

    @mcp.tool()
    @logged("status")
    def status() -> str:
        """Report engine/session status."""
        return json.dumps(_BROWSER.status())

    return mcp


def serve(transport: str = "stdio", host: str = "127.0.0.1", port: int = 8765) -> None:
    """Run the MCP server. Default stdio (for Claude/Codex); `streamable-http` for a daemon."""
    mcp = build_mcp()
    if transport == "streamable-http":
        mcp.run(transport="streamable-http", host=host, port=port)
    else:
        mcp.run(transport="stdio")
