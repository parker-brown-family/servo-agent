"""Console entrypoint: `servo-agent serve` (MCP) | `servo-agent selftest [url]`."""
from __future__ import annotations

import sys

HELP = """servo-agent

Usage:
  servo-agent serve
  servo-agent serve --http [host:port]
  servo-agent mcp
  servo-agent selftest [url]
  servo-agent events [--tail N] [--tool NAME] [--errors] [--since ISO]
  servo-agent --help

Commands:
  serve          Run the MCP server over stdio (default).
  serve --http   Run the MCP server as an HTTP daemon (default 127.0.0.1:8765).
  mcp            Alias for serve.
  selftest       Drive a real page through Servo, read_page, and screenshot.
  events         Inspect the tool-call feedback log (JSON; `events --help`).

Env:
  SERVOSHELL        path to the servoshell binary (else auto-discovered).
  SERVO_WEBDRIVER   host:port of a running engine to attach to (else spawns one).
  SERVO_AGENT_LOG   tool-call event log path (else ~/.servo-agent/events.jsonl);
                    set to 'off' to disable logging.
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

    if cmd == "events":
        from .events import events_cli

        return events_cli(argv[1:])

    if cmd in ("serve", "mcp"):
        from .server import serve

        if "--http" in argv:
            i = argv.index("--http")
            nxt = argv[i + 1] if i + 1 < len(argv) else ""
            addr = nxt if nxt and not nxt.startswith("-") else "127.0.0.1:8765"
            host, _, port = addr.partition(":")
            serve(transport="streamable-http", host=host or "127.0.0.1", port=int(port or 8765))
        else:
            serve()
        return 0

    print(f"unknown command {cmd!r}; use 'serve' or 'selftest [url]'", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
