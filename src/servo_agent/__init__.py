"""servo-agent — an agent-controllable browser over the Servo engine's WebDriver.

Public API:
    ServoBrowser   — drive servoshell over W3C WebDriver (lifecycle + primitives).
    distill        — rendered HTML → clean, token-efficient markdown.
    find_servoshell — locate the engine binary.
    build_mcp/serve — the `servo-agent` MCP server.
"""
from __future__ import annotations

from .browser import ServoBrowser, ServoNotBuilt, find_servoshell
from .distill import distill

__all__ = ["ServoBrowser", "ServoNotBuilt", "find_servoshell", "distill", "__version__"]
__version__ = "0.1.0"
