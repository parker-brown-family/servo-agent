# Integrations

Adapters that wire `servo-agent` into the Brown Family Sports agent skills.
Each is runnable standalone and importable as a function.

| File | Wires into | Entry point |
|---|---|---|
| `deep_research_provider.py` | `deep-research` | `fetch_sources(urls) -> [{url,title,markdown,links}]` |
| `verify_site.py` | `verify` / CI | `verify(spec) -> report`; exit 1 on failure |
| `schedule_watch.py` | `schedule` | `run(spec) -> int`; exit 1 == changed |

## deep-research

Use Servo-rendered, distilled markdown as the source fetcher instead of raw
`WebFetch`. Drop this into the skill's fetch step:

```python
from integrations.deep_research_provider import fetch_sources
sources = fetch_sources(candidate_urls, max_chars=6000)   # clean markdown per source
```

## verify

Point the `verify` skill (or CI) at a JSON spec of expectations:

```bash
uv run python integrations/verify_site.py verify-spec.json   # exit code gates the deploy
```

## schedule

Make this the command a scheduled routine runs; exit code signals change so the
routine can notify only when something moved:

```bash
uv run python integrations/schedule_watch.py watch.json
```

> All adapters need a built `servoshell` (see the top-level README). They share
> the same lazy-launch lifecycle, so there's nothing to start or stop.
