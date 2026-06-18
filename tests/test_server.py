"""The MCP server builds and registers the expected agent tools."""
from __future__ import annotations

import asyncio

from servo_agent.server import build_mcp

EXPECTED_TOOLS = {
    "open_url", "read_page", "find", "wait_for_selector", "wait_for_load",
    "get_errors", "click", "type_text", "fill_form", "scroll", "extract_links",
    "extract_table", "eval_js", "screenshot", "status",
}


def test_build_mcp_constructs() -> None:
    mcp = build_mcp()
    assert mcp is not None


def test_all_tools_registered() -> None:
    mcp = build_mcp()
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    missing = EXPECTED_TOOLS - names
    assert not missing, f"missing tools: {missing}"
