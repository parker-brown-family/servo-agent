# Contributing

## Dev setup

```bash
uv sync --extra dev      # install runtime + dev deps (pytest, ruff)
uv run pytest            # unit tests always run; integration auto-skips w/o a binary
uv run ruff check .      # lint
```

Python ≥ 3.10. Ruff is configured (line length 100, rules `E,F,I,UP,B`) in
`pyproject.toml`; keep `ruff check .` clean before opening a PR.

## Test layout

Tests live in `tests/`:

- `test_distill.py` — distillation is a pure function, so these run **offline**,
  everywhere, with no engine.
- `test_browser.py` — drives a real `servoshell`; marked `integration`.
- `test_server.py` — MCP server wiring.
- `conftest.py` — shared fixtures, including the `browser` fixture.
- `fixtures/sample.html` — a deterministic page served as a `file://` URL, so
  integration tests need no network.

**Integration tests auto-skip when no binary is found.** The session-scoped
`browser` fixture calls `find_servoshell()` and, if it returns `None`,
`pytest.skip`s the whole integration suite. That means `uv run pytest` is green
on a machine that has only checked out the harness — you don't need a built
engine to contribute to the pure-Python parts.

To run the integration tests, build or point at a `servoshell`:

```bash
# build the sibling servo fork...
./mach build -d --media-stack dummy
# ...or point at an existing binary
export SERVOSHELL=/path/to/servoshell
uv run pytest
```

Discovery order is `$SERVOSHELL` → `PATH` → a sibling `servo/` checkout — the
same as the runtime.

## House rules

- **No AI attribution in commits or PRs.** Do not add `Co-Authored-By: Claude …`
  or "Generated with …" trailers to commit messages or PR bodies. Commits are
  authored by a human identity.
- **Keep `distill` pure.** No engine, no network — it must stay unit-testable
  offline. Engine-dependent logic belongs in `ServoBrowser`.
- **Match the existing style.** Agent-shaped primitives on `ServoBrowser`; the
  MCP server, CLI, and self-test stay thin wrappers over it.
- **Lint and test before pushing.** `uv run ruff check .` and `uv run pytest`.
