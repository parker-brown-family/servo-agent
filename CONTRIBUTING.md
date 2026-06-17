# Contributing to servo-agent

Thanks for your interest! `servo-agent` is an agent-controllable browser built
on the [Servo](https://servo.org) engine. Contributions of all kinds are
welcome — bug reports, docs, tests, new tools, and engine-side work.

## Ground rules

- Be kind. This project follows the [Code of Conduct](CODE_OF_CONDUCT.md).
- Keep changes focused; one logical change per pull request.
- Add or update tests for behavior changes.
- Run the checks below before opening a PR.

## Dev setup

You need [`uv`](https://docs.astral.sh/uv/) and a built `servoshell` (see the
[README](README.md) for the one-line build). Then:

```bash
uv sync --extra dev
uv run pytest            # unit tests always run; engine integration auto-skips without a binary
uv run ruff check .
```

Point the harness at a specific engine binary with `SERVOSHELL=/path/to/servoshell`.

### Project layout

```
src/servo_agent/   ServoBrowser (WebDriver client + tools), distill, MCP server, CLI
tests/             pytest — unit (no engine) + integration (marked, auto-skip)
examples/          one runnable script per use case
integrations/      adapters into agent skills (deep-research / verify / schedule)
web/               the static product page (/pc kiosk, /info)
docs/              mkdocs documentation
```

## Tests

- **Unit** tests (e.g. `tests/test_distill.py`, `tests/test_cli.py`) run anywhere
  and gate CI.
- **Integration** tests (`tests/test_browser.py`) are marked `integration` and
  drive a real `servoshell` against a local `file://` fixture; they auto-skip
  when no binary is found. Run them explicitly with `uv run pytest -m integration`.

## Pull requests

1. Fork and branch from `main`.
2. Make your change with tests and docs.
3. Ensure `uv run pytest` and `uv run ruff check .` pass.
4. Open a PR using the template; describe the change and how you verified it.

CI runs lint + unit tests on every PR. Maintainers may run the integration suite
on a runner with a built engine.

## Reporting bugs / requesting features

Use the [issue templates](https://github.com/parker-brown-family/servo-agent/issues/new/choose).
For security issues, see [SECURITY.md](SECURITY.md) — please do **not** open a
public issue.

## License

By contributing, you agree that your contributions are licensed under the
project's [Apache-2.0](LICENSE) license.
