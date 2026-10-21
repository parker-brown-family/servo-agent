# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Tool-call event log** — every MCP tool call is recorded as one JSON line
  (tool, clipped/redacted args, latency, ok/error, result size, engine
  external/respawned state, and for `read_page` the distill extractor + compression
  ratio). Built for agentic consumption, not a human dashboard. Inspect with
  `servo-agent events` (summary digest), `--tail N` (raw events), `--tool`,
  `--errors`, `--since`. Log at `$SERVO_AGENT_LOG` (default
  `~/.servo-agent/events.jsonl`); set `SERVO_AGENT_LOG=off` to disable. Logging is
  std-lib only and never fatal — a logging failure can't break a tool call.
- Open-source project scaffolding: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`,
  `SECURITY.md`, issue/PR templates, release workflow, `CHANGELOG.md`.
- `servo-agent --help` / `-h` usage output; unknown commands exit `2` with a hint.
- PEP 561 typed marker (`py.typed`) — the package ships type information.
- New tools: `wait_for_load` (waits out SPA hydration), `get_errors` (page JS
  error capture), and `screenshot` width/height/`full_page` options.
- `bench/read_page_bench.py` — reproducible benchmark of rendered HTML against
  distilled markdown on real sites.
- `read_native()` + `read_native` MCP tool — native in-engine page read via the
  Servo `/servo/agent/read` extension (no JS round-trip), with a `read_page` fallback.
- `serve --http [host:port]` — run the MCP server as an HTTP (streamable-http)
  daemon, so it can be managed as a long-running service.
- `SERVO_WEBDRIVER` env — attach to an already-running servoshell engine instead
  of spawning one (shared-engine deployments, e.g. via `spin`).

### Changed
- `uv.lock` is committed, so `uv sync` in a clone installs the versions CI
  tested. CI runs on the lock across Python 3.10, 3.12 and 3.14, and weekly
  against the newest releases the version ranges allow.
- Dependency floors are the oldest versions the suite passes: `mcp>=1.15,<2`,
  `trafilatura>=2.1,!=2.2.0`, `markdownify>=0.11.6`.
- `navigate()` / `open_url` start navigation from script and do their own bounded
  wait. A navigation that never commits raises `TimeoutError` instead of
  reporting the previous page.
- A page Servo leaves `interactive` (a web font or beacon that never finishes)
  counts as loaded once its DOM has been still for two seconds, in `navigate()`
  and `wait_for_load()`; both report `interactive`.
- `servoshell` discovery also finds a `servo/` checkout beside any directory
  above the installed package, so projects that install servo-agent (such as
  servo-reader) find a sibling engine build.
- The benchmark reports distillation without `read_page`'s 12,000-character cap.
  It used to measure the cap as well, which is where the README's earlier
  "~59× average, 146× peak" came from; uncapped, its five pages shrink 2× to 27×.

### Fixed
- `servo-agent serve` starts from a fresh install again. mcp 2 removed
  `mcp.server.fastmcp`, and without a ceiling every new install resolved it.
- `read_page` no longer leaks `<sup>` citation markup with trafilatura 2.2 and
  later, and relative links resolve against the page instead of the site root.
- `open_url` no longer holds the session on pages that never reach `complete`
  (WebDriver `POST /url` waited up to five minutes), and re-opening the same URL
  reads the new document rather than the one being replaced (#2).
- `click`, `back()` and `reload()` send the JSON object body Servo's WebDriver
  requires; an empty body was rejected with 400 (#4).
- `selftest` reports an unavailable screenshot instead of failing (#3).
- LICENSE is the unmodified Apache License 2.0 text again.
- `read_page` distillation: inline anchors no longer reorder past punctuation;
  footnote/citation superscripts and Wikipedia editorial tags are stripped;
  mid-sentence list-marker leaks healed; link-only table cells preserved;
  Docusaurus `:::` admonitions unwrapped. Each fix covered by a focused test.

## [0.1.0] - 2026-06-17

Initial public source release. It was not tagged or published to PyPI; the
link below points at the commit.

### Added
- `ServoBrowser` — drive a Servo build over its built-in W3C WebDriver
  (lifecycle management + agent primitives).
- `read_page` — distill the post-render DOM to clean markdown (~100–200× smaller
  than raw HTML) via trafilatura with a noise-stripping fallback.
- Tools: `open_url`, `read_page`, `find`, `wait_for_selector`, `click`,
  `type_text`, `fill_form`, `scroll`, `extract_links`, `extract_table`,
  `eval_js`, `screenshot`, `status`.
- `servo-agent` MCP server (stdio) and `servo-agent selftest` CLI.
- Six runnable use-case examples and deep-research / verify / schedule adapters.
- pytest suite (unit + auto-skipping engine integration) and CI.
- Product page (`/pc` kiosk, `/info`).

[Unreleased]: https://github.com/parker-brown-family/servo-agent/compare/ea40ccf...main
[0.1.0]: https://github.com/parker-brown-family/servo-agent/tree/ea40ccf
