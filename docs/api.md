# API reference

Everything funnels through `ServoBrowser`; `distill` is a standalone pure
function; the CLI and MCP server are thin wrappers.

## Top-level imports

```python
from servo_agent import ServoBrowser, distill, find_servoshell, ServoNotBuilt, ScreenshotUnavailable
```

| Name | Kind | Summary |
|---|---|---|
| `ServoBrowser` | class | One `servoshell` process + one WebDriver session. |
| `distill` | function | Rendered HTML → clean, token-efficient markdown. |
| `find_servoshell` | function | Locate the engine binary, or `None`. |
| `ServoNotBuilt` | exception | Raised when no binary can be found. |
| `ScreenshotUnavailable` | exception | Servo would not capture the page; the message says what it waited on. |

## `ServoBrowser`

```python
ServoBrowser(binary: str | Path | None = None, headless: bool = True,
             memory_cap_mb: int | None = None)
```

Lazily starts `servoshell` on a free port; usable as a context manager
(`with ServoBrowser() as b:`), which tears the engine down on exit. If `binary`
is omitted, it is discovered via `find_servoshell()`. Every engine it starts
gets a temporary profile (`--temporary-storage`) and a screen tall enough for
20,000 px full-page shots, and is stopped through Servo's own
`/servo/shutdown` WebDriver route.

`memory_cap_mb` (default `$SERVO_AGENT_MEMORY_CAP_MB`, else 700; 0 = off): before
each `navigate`, an engine this browser started whose PSS has passed the cap is
restarted, and `last_restart` describes it (cookies and history are lost). Servo
0.7.0's memory climbed from 334 MB to 5.3 GB over 100 pages in one window.
`memory_mb()` reads the engine's PSS (Linux; `None` when unknown) and
`engine_version` is the Servo version from the session's user agent.

### Navigation

| Method | Signature | Returns | Notes |
|---|---|---|---|
| `navigate` | `navigate(url, timeout=20.0, settle=False)` | `str` (final `readyState`) | Bounded wait for the **new** document; `interactive` once a page that never completes has had a still DOM for half a second; raises `TimeoutError` if nothing commits. May restart the engine first (see `memory_cap_mb`). |
| `title` | `title()` | `str` | Current document title. |
| `current_url` | `current_url()` | `str` | Live document URL. |
| `reload` | `reload()` | `None` | `POST /refresh`. |
| `back` | `back()` | `None` | History back. |

### Scripting & HTML

| Method | Signature | Returns | Notes |
|---|---|---|---|
| `eval_js` | `eval_js(script, args=None)` | JSON value | Use `return …`; `args` map to `arguments[0]`, etc. |
| `outer_html` | `outer_html()` | `str` | `documentElement.outerHTML`. |
| `read_html` | `read_html()` | `str` | `outerHTML` with relative `href`/`src` absolutized — feed this to `distill`. |

### Elements

| Method | Signature | Returns | Notes |
|---|---|---|---|
| `find_all` | `find_all(selector)` | `list[str]` | W3C element ids for a CSS selector. |
| `element_text` | `element_text(id)` | `str` | Visible text of an element by id. |
| `click_selector` | `click_selector(selector)` | `None` | Clicks the first match; raises if none. |
| `type_selector` | `type_selector(selector, text)` | `None` | Types into the first match; raises if none. |

### Waiting & scrolling

| Method | Signature | Returns | Notes |
|---|---|---|---|
| `wait_for_selector` | `wait_for_selector(selector, timeout=10.0, visible=False)` | `int` (count) | Polls until ≥1 match (optionally visible). Raises `TimeoutError` on timeout. |
| `scroll` | `scroll(to="bottom")` | `None` | `to` ∈ `"bottom"`, `"top"`, a CSS selector, or a pixel `y` value (e.g. `"800"`). |

### Extraction

| Method | Signature | Returns | Notes |
|---|---|---|---|
| `extract_links` | `extract_links(selector="a")` | `list[{text, href}]` | Absolute hrefs. |
| `extract_table` | `extract_table(selector="table")` | `list[dict]` | First matching table → row dicts keyed by `<th>`; falls back to `col0, col1, …`. |

### Forms & capture

| Method | Signature | Returns | Notes |
|---|---|---|---|
| `fill_form` | `fill_form(fields, submit=None)` | `None` | `fields`: `{selector: value}`; optionally clicks `submit`. |
| `screenshot` | `screenshot(path, width=None, height=None, full_page=False)` | `str` (abs path) | Writes a PNG; `last_screenshot` then holds `{width, height}` and, for a full page, `{page_height, cut_short}`. If Servo times out waiting on images that never finish, they are dropped and the capture retried (`dropped_unfinished_images`); otherwise `ScreenshotUnavailable` says what Servo was waiting on. |
| `status` | `status()` | `dict` | `{binary, engine_version, started, headless, port, url, memory_mb, memory_cap_mb}`. |

## `distill`

```python
distill(html: str, url: str = "", max_chars: int = 12000, offset: int = 0) -> str
```

Rendered HTML → clean markdown. Tries trafilatura first (article pages), then a
BeautifulSoup + markdownify noise-stripping fallback. `url` helps trafilatura
resolve/classify. A page longer than `max_chars` comes in parts: each part
ends just before a paragraph or line break outside any link or code block, and
all but the last end in a marker, `…[truncated at N chars; the next part starts
at offset M of T chars]`. Pass `offset=M` for the next part; in order, the parts
add up to the whole page. Rows served without a `<tbody>` (Hacker News, many
forums) get one inserted first, as a browser would, so a plain download keeps
their links. Pure function — no engine required.

```python
from servo_agent import ServoBrowser, distill

with ServoBrowser() as b:
    b.navigate("https://example.com")
    md = distill(b.read_html(), b.current_url(), max_chars=4000)
```

## `find_servoshell`

```python
find_servoshell() -> Path | None
```

Discovery order: `$SERVOSHELL` → `servoshell` on `PATH` → the newest engine
installed by `servo-agent install-servo` → the nearest `servo/servoshell` (an
unpacked release) or `servo/target/{release,debug}/servoshell` beside the
installed package or any directory above it (from a source checkout, the sibling
`../servo`). Returns `None` if nothing is found.

## CLI

```bash
servo-agent install-servo [--version X.Y.Z]  # install Servo's official build (Linux)
servo-agent serve              # run the MCP server over stdio
servo-agent selftest [url]     # drive a real page end-to-end (default: Hacker News)
```

`serve` (alias `mcp`) starts the MCP server. `selftest` spawns its own headless
engine and walks the full pipeline; exit `0` on success.

## MCP tools

Exposed by `servo-agent serve`. Every tool returns JSON (as a string); a shared,
lazily-started browser backs all of them and is torn down at process exit.

| Tool | Signature | Returns |
|---|---|---|
| `open_url` | `open_url(url, settle=False)` | `{title, url, readyState}`, plus `engine_restarted: {reason, pss_mb, cap_mb, lost}` when the engine was restarted first |
| `read_page` | `read_page(max_chars=12000, offset=0)` | distilled markdown; a long page in parts, each but the last ending in a marker naming the next `offset` |
| `find` | `find(selector)` | `{selector, count, sample}` (first ≤10 texts) |
| `wait_for_selector` | `wait_for_selector(selector, timeout=10.0, visible=False)` | `{selector, present, count}` or `{present: false, error}` |
| `wait_for_load` | `wait_for_load(timeout=15.0)` | `{readyState, settled}` |
| `get_errors` | `get_errors()` | `{count, errors: [{type, message, source, line, col}]}` |
| `click` | `click(selector)` | `{clicked, url}` |
| `type_text` | `type_text(selector, text)` | `{typed_into, chars}` |
| `fill_form` | `fill_form(fields, submit="")` | `{filled, submitted, url}` |
| `scroll` | `scroll(to="bottom")` | `{scrolled}` |
| `extract_links` | `extract_links(selector="a")` | `[{text, href}, …]` |
| `extract_table` | `extract_table(selector="table")` | `[{…}, …]` |
| `eval_js` | `eval_js(script)` | `{result}` |
| `screenshot` | `screenshot(path="servo-shot.png", width=0, height=0, full_page=False)` | `{path, width, height}`, plus `{page_height, cut_short}` for a full page and `dropped_unfinished_images` when Servo was waiting on images that never finished |
| `status` | `status()` | engine/session status dict |
