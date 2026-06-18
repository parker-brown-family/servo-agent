# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Open-source project scaffolding: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`,
  `SECURITY.md`, issue/PR templates, release workflow, `CHANGELOG.md`.
- `servo-agent --help` / `-h` usage output; unknown commands exit `2` with a hint.
- PEP 561 typed marker (`py.typed`) — the package ships type information.
- New tools: `wait_for_load` (waits out SPA hydration), `get_errors` (page JS
  error capture), and `screenshot` width/height/`full_page` options.
- `bench/read_page_bench.py` — reproducible raw-HTML-vs-distilled benchmark
  (~59× average reduction across real sites).
- `read_native()` + `read_native` MCP tool — native in-engine page read via the
  Servo `/servo/agent/read` extension (no JS round-trip), with a `read_page` fallback.
- `serve --http [host:port]` — run the MCP server as an HTTP (streamable-http)
  daemon, so it can be managed as a long-running service.
- `SERVO_WEBDRIVER` env — attach to an already-running servoshell engine instead
  of spawning one (shared-engine deployments, e.g. via `spin`).

### Fixed
- `read_page` distillation: inline anchors no longer reorder past punctuation;
  footnote/citation superscripts and Wikipedia editorial tags are stripped;
  mid-sentence list-marker leaks healed; link-only table cells preserved;
  Docusaurus `:::` admonitions unwrapped. Each fix covered by a focused test.

## [0.1.0] - 2026-06-17

Initial public release.

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

[Unreleased]: https://github.com/parker-brown-family/servo-agent/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/parker-brown-family/servo-agent/releases/tag/v0.1.0
