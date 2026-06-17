"""Console entrypoint: `servo-agent serve` (MCP) | `servo-agent selftest [url]`."""
from __future__ import annotations

import sys

HELP = """servo-agent

Usage:
  servo-agent serve
  servo-agent mcp
  servo-agent selftest [url]
  servo-agent --help

Commands:
  serve          Run the MCP server over stdio.
  mcp            Alias for serve.
  selftest       Drive a real page through Servo, read_page, and screenshot.
"""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "serve"

    if cmd in ("--help", "-h", "help"):
        print(HELP)
        return 0

    if cmd == "selftest":
        from .selftest import run_selftest

        url = argv[1] if len(argv) > 1 else "https://news.ycombinator.com"
        return run_selftest(url)

    if cmd in ("serve", "mcp"):
        from .server import serve

        serve()
        return 0

    print(f"unknown command {cmd!r}; use 'serve' or 'selftest [url]'", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
