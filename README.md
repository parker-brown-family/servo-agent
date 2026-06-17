# servo-agent

**An agent-controllable browser, built on the [Servo](https://servo.org) engine.**

![servo-agent — a robot giving life to a web page](web/assets/hero.png)

<sub>Product page ([`web/`](web/)): the **`/pc`** kiosk ("Easy as 1-2-3" animation) + the **`/info`** page (use cases, quickstart).</sub>

`servo-agent` turns a Servo build into a browser an LLM agent can drive — and,
crucially, _read_. It wraps Servo's built-in **W3C WebDriver** server (a control
surface LLMs already understand) and adds the one thing agents actually need:
`read_page`, which distills the **post-render DOM** into clean markdown that is
typically **~100–200× smaller than the raw HTML**.

It runs headless, manages the engine lifecycle for you, and ships as an **MCP
server** so you can drop it straight into Claude Code, Codex, or any MCP client.

```text
            ┌──────────────┐   W3C WebDriver    ┌────────────────┐
  agent ──▶ │  servo-agent │ ─────────────────▶ │   servoshell   │ ──▶ the web
  (MCP)     │  (this repo) │ ◀───────────────── │  (Servo engine)│
            └──────────────┘   DOM → markdown    └────────────────┘
```

## Why

Most "agent browsing" stacks puppeteer Chromium over CDP: heavyweight, hard to
instrument, and easy to bot-detect. Servo is a **memory-safe, embeddable engine
you can own end to end**. Because it already speaks WebDriver, an agent is
immediately on familiar ground — and because you control the engine, you can
extend it at the source (see the [roadmap](docs/roadmap.md)).

The payoff is `read_page`: an agent reads distilled content, not tag soup.

| Page | Raw HTML | Distilled markdown |
|---|---|---|
| Wikipedia article | ~372 KB | ~2 KB |
| Hacker News front page | ~40 KB | clean story list w/ links |
| MDN doc | ~102 KB | ~2 KB, no nav/sidebar chrome |

## Install

```bash
uv tool install servo-agent          # or: pipx install servo-agent
```

You also need a built `servoshell`. Either put it on `PATH`, set `$SERVOSHELL`,
or check out the [Servo](https://github.com/servo/servo) repo next to this one and:

```bash
./mach build -d --media-stack dummy  # -> target/debug/servoshell
```

`servo-agent` auto-discovers the binary via `$SERVOSHELL` → `PATH` → a sibling
`servo/` checkout.

## Quick start

```bash
# Prove the whole stack end-to-end (spawns its own headless engine):
servo-agent selftest https://news.ycombinator.com

# Run as an MCP server (stdio):
servo-agent serve
```

Library use:

```python
from servo_agent import ServoBrowser, distill

with ServoBrowser(headless=True) as b:
    b.navigate("https://example.com")
    print(distill(b.read_html(), b.current_url()))   # clean markdown
    rows = b.extract_table("table#stats")            # structured data
    b.screenshot("shot.png")
```

## Tools (MCP)

| Tool | Purpose |
|---|---|
| `open_url` | Navigate; returns title/url once the new document has committed. |
| `read_page` | Post-render DOM → clean markdown (the value-add). |
| `find` / `wait_for_selector` | Query / wait for elements by CSS selector. |
| `click` / `type_text` / `fill_form` | Interaction. |
| `scroll` | Scroll to bottom/top, a selector, or a pixel offset. |
| `extract_links` / `extract_table` | Structured extraction → JSON. |
| `eval_js` | Run JavaScript, get JSON back. |
| `screenshot` / `status` | Capture / introspect. |

## Wire into an MCP client

**Claude Code**

```bash
claude mcp add servo-agent -s user -- \
  uv run --project /path/to/servo-agent servo-agent serve
```

**Codex** (`~/.codex/config.toml`)

```toml
[mcp_servers.servo-agent]
command = "uv"
args = ["run", "--project", "/path/to/servo-agent", "servo-agent", "serve"]
```

> MCP tools are injected at client startup — restart after adding/changing the
> server. Validate harness edits without a restart via `servo-agent selftest`.

## Use cases

Worked, runnable examples live in [`examples/`](examples/) and the integration
adapters in [`integrations/`](integrations/):

- **Research source-reader** — distilled markdown for multi-source research.
- **Site QA / pre-deploy checker** — render, screenshot, assert content & links.
- **Page watcher** — poll a page, extract a value, alert on change.
- **Bot-walled scrape fallback** — a JS-rendering engine you own.
- **Structured data extraction** — `extract_table` into a pipeline.
- **Universal "read the live web"** primitive for any agent task.

See [docs/use-cases.md](docs/use-cases.md) for the full write-up.

## Develop

```bash
uv sync --extra dev
uv run pytest            # unit tests always run; integration auto-skips w/o a binary
uv run ruff check .
```

## License

Apache-2.0. Servo itself is a separate project under MPL-2.0; `servo-agent`
talks to it over WebDriver and does not vendor its code.
