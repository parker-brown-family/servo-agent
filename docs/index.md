# servo-agent

**An agent-controllable browser, built on the [Servo](https://servo.org) engine.**

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

The agent talks MCP (or the Python API) to `servo-agent`. `servo-agent` speaks
W3C WebDriver to a `servoshell` process it launches and manages. The post-render
DOM comes back, and `read_page` distills it to markdown before the agent ever
sees it.

## Why

Most "agent browsing" stacks puppeteer Chromium over CDP: heavyweight, hard to
instrument, and easy to bot-detect. Servo is a **memory-safe, embeddable engine
you can own end to end**. Because it already speaks WebDriver, an agent is
immediately on familiar ground — and because you control the engine, you can
extend it at the source (see the [roadmap](roadmap.md)).

The payoff is `read_page`: an agent reads distilled content, not tag soup.

| Page | Raw HTML | Distilled markdown |
|---|---|---|
| Wikipedia article | ~372 KB | ~2 KB |
| Hacker News front page | ~40 KB | clean story list w/ links |
| MDN doc | ~102 KB | ~2 KB, no nav/sidebar chrome |

## When to use it

- You want an agent to **read the live web** — pages that need JavaScript to
  render, distilled to the content that matters.
- You want a browsing primitive you **own and can instrument**, rather than a
  remote-controlled Chromium you can't see into.
- You need **structured extraction** (`extract_table`, `extract_links`) or
  **interaction** (`click`, `type_text`, `fill_form`) as part of an agent loop.
- You're doing **site QA**, **page watching**, or **scrape fallback** where a
  real rendering engine beats a raw HTTP fetch.

If all you need is a static HTML fetch with no JS, a plain HTTP client is lighter.
`servo-agent` earns its keep when the page is rendered, interactive, or both.

## Next

- [Quick start](quickstart.md) — install, self-test, wire into a client.
- [Architecture](architecture.md) — how the WebDriver wrapping and `read_page`
  pipeline actually work.
- [API reference](api.md) — `ServoBrowser`, `distill`, the CLI, and MCP tools.
- [Use cases](use-cases.md) — six concrete jobs it's built for.
- [Roadmap](roadmap.md) — the four-track plan, including the in-tree bet.

## License

Apache-2.0. Servo itself is a separate project under MPL-2.0; `servo-agent`
talks to it over WebDriver and does not vendor its code.
