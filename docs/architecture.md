# Architecture

`servo-agent` is a thin, agent-shaped layer over Servo's built-in W3C WebDriver
server. It owns the engine lifecycle, smooths over a navigation race, and
distills the rendered DOM into markdown. Everything funnels through one class —
`ServoBrowser` — and the MCP server, the self-test, and the examples are thin
wrappers over it.

```text
            ┌──────────────┐   W3C WebDriver    ┌────────────────┐
  agent ──▶ │  servo-agent │ ─────────────────▶ │   servoshell   │ ──▶ the web
  (MCP)     │  (this repo) │ ◀───────────────── │  (Servo engine)│
            └──────────────┘   DOM → markdown    └────────────────┘
```

## Wrapping WebDriver

Servo ships a W3C WebDriver server inside `servoshell`. Start it with:

```bash
servoshell --headless --webdriver <port> about:blank
```

`ServoBrowser` speaks the raw W3C HTTP protocol directly (via `requests`), rather
than pulling in a Selenium client. It opens one session
(`POST /session` with `browserName: servo`) and maps the protocol onto
agent-shaped primitives:

- `navigate` → `POST /session/{id}/url`
- `eval_js` → `POST /session/{id}/execute/sync`
- `find_all` → `POST /session/{id}/elements` (CSS selector)
- `click`/`type` → `POST /session/{id}/element/{el}/click` and `/value`
- `screenshot` → `GET /session/{id}/screenshot`

Element references use the W3C key `element-6066-11e4-a52e-4f735466cecf`. Several
agent conveniences (`scroll`, `wait_for_selector`, `extract_links`,
`extract_table`) are implemented as `execute/sync` scripts rather than extra
protocol calls, so they work against stock Servo today.

## Lifecycle

The engine is launched **lazily** and cleaned up automatically:

1. **Free port.** On first use, `ServoBrowser._free_port()` binds `127.0.0.1:0`
   to grab an unused port from the OS, so concurrent instances never collide.
2. **Spawn.** `servoshell --headless --webdriver <port> about:blank` is started
   as a subprocess (stdout/stderr to `DEVNULL`). The wrapper waits for the
   WebDriver port to accept connections (up to 30 s) before opening a session.
3. **Use.** Every command calls `ensure_started()` first, so navigation,
   scripting, and extraction all just work whether you used the context manager
   or called a method directly.
4. **Cleanup.** `shutdown()` deletes the WebDriver session, then `terminate()`s
   the process (escalating to `kill()` after 5 s). The context manager calls it
   on `__exit__`. The MCP server registers a single shared browser with
   `atexit`, so the engine is torn down when the server process exits.

This means a freshly constructed `ServoBrowser` holds no process — nothing is
spawned until you navigate (or enter the context manager). One process, one
session, per `ServoBrowser`.

## The navigation race

Servo's WebDriver `POST /url` can return **before** the new document has replaced
the old one. Polling `document.readyState` alone races: the *previous* page still
reports `complete`, so a naive wait sees "complete" and reads stale content.

`navigate(url, timeout=20.0)` fixes this by waiting for the new document to
actually **commit**, not just for a `complete` readyState:

1. Record the current `document.URL` before navigating.
2. Issue `POST /url`.
3. Poll until **both** hold: `readyState == "complete"` **and** the live
   `document.URL` has become the target (or at least changed away from the
   previous URL and isn't `about:blank`).

It returns the final `readyState`. The fragment (`#…`) is stripped and trailing
slashes normalized when comparing URLs, so anchor-only differences don't cause a
false miss.

## The `read_page` pipeline

`read_page` (and the library equivalent `distill(b.read_html(), b.current_url())`)
turns the rendered page into clean markdown in two stages.

### 1. `read_html()` — capture + absolutize

`read_html()` runs a small script in the page that rewrites every relative
`a[href]` and `img/source[src]` to its absolute form **before** serializing
`document.documentElement.outerHTML`. This matters because distillation happens
out-of-engine: once the HTML leaves the page, relative links would be
unresolvable. Absolutizing in-page guarantees the markdown's links still work.

### 2. `distill()` — DOM → markdown

`distill(html, url="", max_chars=12000)` is a **pure function** (no engine
required, fully unit-testable offline). It tries the best extractor first and
falls back:

1. **trafilatura** — article-shaped pages. Extracts to markdown with links and
   formatting preserved (`favor_recall=True`). This is the primary path for
   content pages.
2. **BeautifulSoup + markdownify fallback** — used when trafilatura returns
   nothing or under ~40 characters (thin or utility pages). It:
   - drops never-content tags (`script`, `style`, `nav`, `header`, `footer`,
     `aside`, `form`, `button`, `dialog`, `iframe`, `svg`, …),
   - drops ARIA landmark roles (`navigation`, `banner`, `contentinfo`,
     `search`, `dialog`),
   - decomposes elements whose `id`/`class` contains noise tokens (`cookie`,
     `consent`, `gdpr`, `banner`, `sidebar`, `popup`, `newsletter`, `promo`,
     `breadcrumb`, …),
   - prefers `<main>`/`<article>`/`<body>` as the root, then converts to ATX
     markdown.

The result is whitespace-collapsed and truncated to `max_chars` with a marker if
it overflows. That two-tier strategy is what produces the ~100–200× reduction:
the agent sees content, not chrome.
