# Examples

Runnable, single-purpose scripts — one per use case. All need a built
`servoshell` (see the top-level README) and run inside the project env:

```bash
uv run python examples/<name>.py [args]
```

| Script | Use case |
|---|---|
| `universal_read.py` | Any URL → clean markdown (the core primitive). |
| `research_read.py` | Read many sources as markdown → JSON (research). |
| `site_qa.py` | Render, assert content + links, screenshot; exit code for CI. |
| `watch_page.py` | Extract a value, alert on change (cron-friendly). |
| `scrape_fallback.py` | JS-render a bot-walled page → markdown + links. |
| `extract_table_demo.py` | HTML table → JSON / CSV. |
