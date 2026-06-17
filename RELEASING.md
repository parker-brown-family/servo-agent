# Releasing

Releases are automated by `.github/workflows/release.yml`, triggered by a version
tag. PyPI publishing uses [Trusted Publishing][tp] (OIDC) — no API tokens.

## One-time setup (PyPI)

1. Create the `servo-agent` project on PyPI (or reserve the name).
2. Add a **Trusted Publisher** pointing at this repo:
   - Owner: `parker-brown-family`, Repository: `servo-agent`
   - Workflow: `release.yml`, Environment: `pypi`
3. In the GitHub repo, create an environment named `pypi` (Settings →
   Environments) — optionally with required reviewers.

## Cutting a release

1. Update the version in `pyproject.toml` and `src/servo_agent/__init__.py`.
2. Move the `Unreleased` section of `CHANGELOG.md` under a new `vX.Y.Z` heading.
3. Commit, then tag and push:

   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

The workflow builds the wheel + sdist, runs `twine check`, publishes to PyPI, and
creates a GitHub Release with auto-generated notes and the artifacts attached.

## Local dry run

```bash
uv build
uv run --with twine twine check dist/*
```

[tp]: https://docs.pypi.org/trusted-publishers/
