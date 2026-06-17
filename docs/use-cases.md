# Use cases

Six concrete jobs `servo-agent` is built for. Worked, runnable examples live in
[`examples/`](https://github.com/parker-brown-family/servo-agent/tree/main/examples)
and the integration adapters in
[`integrations/`](https://github.com/parker-brown-family/servo-agent/tree/main/integrations).

## 1. Research source-reader

**The need.** An agent compiling a multi-source research report has to read many
pages, but raw HTML burns the context window on nav bars, scripts, and cookie
banners.

**How it serves it.** `read_page` returns distilled markdown — typically
~100–200× smaller than the raw HTML — so the agent reads the *content* of each
source and can fit far more sources in context.

**Why it beats the alternatives.** Raw `fetch` misses anything JS-rendered;
Chromium-over-CDP gives you the bytes but not the distillation, so you still pay
to strip chrome yourself. Here the rendering and the distillation are one step.

## 2. Site QA / pre-deploy checker

**The need.** Before shipping a web property, confirm a page actually renders,
shows the expected content, and has no broken/missing links.

**How it serves it.** Navigate, `screenshot()` for a visual artifact,
`read_page` to assert on content, and `extract_links()` to verify the link set —
all in a script you can run in CI.

**Why it beats the alternatives.** A raw fetch can't tell you what *rendered*. A
full Chromium harness works but is heavy to stand up; `servo-agent` is a single
process you launch and tear down per check.

## 3. Page watcher

**The need.** Poll a page on a schedule, pull out one value (a price, a status, a
count), and alert when it changes.

**How it serves it.** Cron a tiny script: `navigate`, then `eval_js` or
`extract_table`/`find` to read the value, diff against last run, alert on change.

**Why it beats the alternatives.** Many watch-worthy values only appear after JS
runs, so raw fetch sees nothing. A real engine renders them, and `servo-agent`
keeps the per-poll footprint small.

## 4. Bot-walled scrape fallback

**The need.** A source is hostile to naive scrapers and needs a real,
JS-executing browser to render at all.

**How it serves it.** `servo-agent` is a rendering engine you **own and can
instrument** — Servo executes the page like a browser, and you control the whole
stack rather than renting a remote Chromium.

**Why it beats the alternatives.** Raw fetch is trivially blocked. Owning the
engine means you can adapt at the source instead of fighting a black box. (For
genuinely captcha-walled or login-gated sites, a human-in-the-loop step is still
the right escalation — this is the *rendering* fallback, not a captcha solver.)

## 5. Structured data extraction

**The need.** Turn an HTML `<table>` on a live page into rows your pipeline can
consume.

**How it serves it.** `extract_table(selector)` returns a list of row dicts
keyed by the table's `<th>` headers (falling back to positional `col0, col1, …`
keys when there's no header row) — clean JSON, ready to feed downstream.

**Why it beats the alternatives.** Hand-parsing rendered tables out of raw HTML
is brittle; here the extraction runs *in the rendered page*, after JS has
populated the table.

## 6. Universal "read the live web" primitive

**The need.** Any agent task that needs to read the current web — not a cached or
training-time snapshot — through one consistent, low-token interface.

**How it serves it.** A single MCP server gives every agent `open_url` +
`read_page` (plus find/click/type/extract) over a real engine. Distilled output
keeps token cost down across every call.

**Why it beats the alternatives.** It generalizes the above: instead of bolting
a bespoke browser onto each agent, you wire in one MCP server that any MCP client
can use.
