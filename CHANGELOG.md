# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

servo-agent now runs on Servo's official builds. It was built and measured
against our June 2026 fork of Servo; this release is tested against Servo 0.7.0
and Servo's nightly build of 2026-10-22.

### Added
- `servo-agent install-servo [--version X.Y.Z]` downloads Servo's official build
  for Linux (x86_64 or aarch64), checks it against the SHA-256 the release
  publishes, and installs it under `~/.local/share/servo-agent/engines/`.
  `find_servoshell()` looks there after `$SERVOSHELL` and `PATH`, and also finds an
  unpacked release in a `servo/` directory nearby.
- `read_page(offset=…)`: a long page comes in parts. Each part ends outside any
  link or code block, all but the last end in a marker naming the next offset,
  and in order they add up to the whole page (#12).
- A memory cap: before each navigation, an engine servo-agent started whose
  PSS has passed `SERVO_AGENT_MEMORY_CAP_MB` (default 700; 0 = off) is
  restarted, and `open_url` reports `engine_restarted`. Servo 0.7.0 climbed
  from 334 MB to 5.3 GB over 100 pages in one window (#14).
  `bench/memory_climb_bench.py` measures it.
- `screenshot` answers with the image's size, and for a full page with the page's
  height and whether the shot was cut short. `status` reports the engine version
  and its memory.

### Changed
- The MCP server is written against mcp 2 (`MCPServer`); the dependency is
  `mcp>=2.3,<3` (#6).
- Every engine servo-agent starts gets a temporary profile
  (`--temporary-storage`) instead of sharing `~/.config/servo/default` with every
  other servoshell on the machine.
- Engines are stopped through Servo's own `/servo/shutdown` WebDriver route, with
  SIGTERM and then a kill as the fallback. Servo 0.7 catches SIGTERM and never
  exits when headless, so every shutdown used to wait five seconds and kill it.
- A full-page screenshot reaches 20,000 px: the engine is started with a tall
  `--screen-size`, because Servo's default headless screen cut it at 2,960 px
  with nothing said.
- `open_url` returns once a page that never fires `load` has had a still DOM for
  half a second, not two (#11). `wait_for_load` still gives such a page two.
- The engine's WebDriver port is polled every 50 ms at start-up, not every 500 ms.

### Fixed
- A screenshot of a readable page with an image that never arrives timed out
  (Servo waits for every image, then gives up after 10 s). The unfinished images
  are now dropped and the capture retried once, `screenshot` lists them, and a
  page that still can't be captured raises `ScreenshotUnavailable` with the reason
  (#3).
- A plain download of a page whose table rows have no `<tbody>` (Hacker News,
  many forums and listings) lost every link in `distill`; the `<tbody>` is now
  inserted the way a browser's parser does (#13).

### Removed
- `read_native()` and the `read_native` MCP tool. The `/servo/agent/read`
  endpoint they called only ever existed on our Servo fork, which is retired;
  `read_page` does the reading.

## [0.2.0] - 2026-10-21

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

[Unreleased]: https://github.com/parker-brown-family/servo-agent/compare/v0.2.0...main
[0.2.0]: https://github.com/parker-brown-family/servo-agent/releases/tag/v0.2.0
[0.1.0]: https://github.com/parker-brown-family/servo-agent/tree/ea40ccf
