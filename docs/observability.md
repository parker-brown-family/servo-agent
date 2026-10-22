# Observability — the tool-call event log

Every MCP tool call is recorded to a structured JSONL log. This is the product's
**feedback loop**: it makes "how is the harness actually being used, and where does
it hurt?" a queryable question instead of a guess. The intended consumer is an
**agent**, not a human dashboard — an agent reads the log (or runs
`servo-agent events`) and rolls the data into [T1 findings](roadmap.md).

## Why log at the server

Other layers can see *that* a tool was called — an MCP client transcript records
`mcp__servo-agent__read_page`, for instance. But only the server sees *why a call
was good or bad*: which distill extractor fired, the compression ratio, a
`read_page` that quietly fell back to BeautifulSoup, a WebDriver error, an engine
respawn, latency. That internal state is exactly what catches bugs and steers
the distiller — so the log lives in the server, where it is also
**client-agnostic**: stdio (Claude/Codex), the HTTP daemon, and library use are
all captured the same way.

## Where it lives

| | |
|---|---|
| Default path | `~/.servo-agent/events.jsonl` |
| Override | `SERVO_AGENT_LOG=/path/to/events.jsonl` |
| Disable | `SERVO_AGENT_LOG=off` (also `0`, `none`, empty) |

The writer is std-lib only and **never fatal** — if logging fails (bad path, full
disk), the tool call still returns. String arguments are clipped to 200 chars and
`dict` arguments (e.g. `fill_form` values) are redacted to key + length, so the log
never becomes a credential sink.

## Event shape

One JSON object per line:

```json
{"ts":"2026-06-18T20:27:20.848Z","tool":"read_page","ok":true,"ms":312.4,
 "args":{"max_chars":12000},"bytes":1850,"engine":{"external":false,"pid":4242},
 "extractor":"trafilatura","in_chars":372000,"out_chars":1850,"ratio":201.1,
 "truncated":false}
```

| Field | Meaning |
|---|---|
| `ts` | UTC ISO-8601 timestamp |
| `tool` | tool name (`read_page`, `click`, …) |
| `ok` | `false` if the tool raised |
| `ms` | wall-clock latency |
| `args` | clipped/redacted call arguments |
| `bytes` | size of the returned string (when the tool returns text) |
| `engine` | `{external, pid, respawned?}` — engine state at call time |
| `error` / `error_type` | message + exception class, only when `ok:false` |
| `extractor` / `ratio` / `in_chars` / `out_chars` / `truncated` | `read_page` only — distillation detail |
| `offset` / `total_chars` / `next_offset` | `read_page` only — which part of a long page was read, and where the next starts (`null` after the last) |
| `engine_restarted` / `restart_pss_mb` | `open_url` only — the engine passed its memory cap and was restarted first |

## Digging it out

`servo-agent events` is the agent-facing query surface (JSON output):

```bash
servo-agent events                 # rolled-up digest (rates, latency, distill ratios)
servo-agent events --tail 50       # last 50 raw events, oldest first (JSONL)
servo-agent events --tool read_page   # filter to one tool
servo-agent events --errors        # only failed calls
servo-agent events --since 2026-06-18T00:00:00Z
servo-agent events --path /other/log.jsonl
```

The summary digest:

```json
{
  "total": 128, "ok": 124, "errors": 4, "error_rate": 0.031,
  "by_tool": {"read_page": {"calls": 60, "errors": 0}, "click": {"calls": 12, "errors": 3}},
  "latency_ms": {"p50": 120.0, "p95": 410.0, "max": 980.0},
  "distill": {"samples": 60, "ratio_avg": 88.4, "ratio_min": 9.1,
              "extractors": {"trafilatura": 52, "fallback": 8}},
  "recent_errors": [{"ts": "…", "tool": "click", "error": "…", "type": "TimeoutError"}]
}
```

## From log to product improvement

A practical loop:

1. **Watch error rate + the `fallback` extractor count.** A spike in `fallback`
   means trafilatura is losing on real pages — a `read_page` quality signal.
2. **Watch `ratio_min`.** A near-1.0 ratio is a page where distillation barely
   helped (chrome-heavy or mis-extracted) — a candidate for a distiller fix.
3. **Scan `recent_errors` by `tool`.** Repeated `wait_for_selector` timeouts or
   `click` "element not found" point at selector/timing gaps.
4. **Turn findings into the [T1 shape](roadmap.md)** and route them to the
   `servo-agent` project, classifying each as engine (upstream Servo), external
   tooling, or docs/test.

Because the log is plain JSONL, an agent can also read it directly and correlate
events with whatever task it was running — no special tooling required.
