# API reference

Everything funnels through `ServoBrowser`; `distill` is a standalone pure
function; the CLI and MCP server are thin wrappers.

## Top-level imports

```python
from servo_agent import ServoBrowser, distill, find_servoshell, ServoNotBuilt
```

| Name | Kind | Summary |
|---|---|---|
| `ServoBrowser` | class | One `servoshell` process + one WebDriver session. |
| `distill` | function | Rendered HTML → clean, token-efficient markdown. |
| `find_servoshell` | function | Locate the engine binary, or `None`. |
| `ServoNotBuilt` | exception | Raised when no binary can be found. |

## `ServoBrowser`

```python
ServoBrowser(binary: str | Path | None = None, headless: bool = True)
```

Lazily starts `servoshell` on a free port; usable as a context manager
(`with ServoBrowser() as b:`), which tears the engine down on exit. If `binary`
is omitted, it is discovered via `find_servoshell()`.

### Navigation

| Method | Signature | Returns | Notes |
|---|---|---|---|
| `navigate` | `navigate(url, timeout=20.0)` | `str` (final `readyState`) | Waits for the **new** document to commit, not just `readyState`. |
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
| `screenshot` | `screenshot(path)` | `str` (abs path) | Writes a PNG; returns its absolute path. |
| `status` | `status()` | `dict` | `{binary, started, headless, port, url}`. |

## `distill`

```python
distill(html: str, url: str = "", max_chars: int = 12000) -> str
```

Rendered HTML → clean markdown. Tries trafilatura first (article pages), then a
BeautifulSoup + markdownify noise-stripping fallback. `url` helps trafilatura
resolve/classify; output is truncated to `max_chars` with a marker if it
overflows. Pure function — no engine required.

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

Discovery order: `$SERVOSHELL` → `PATH` → a sibling `servo/` fork checkout at
`../servo/target/{debug,release}/servoshell`. Returns `None` if nothing is found.

## CLI

```bash
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
| `open_url` | `open_url(url)` | `{title, url, readyState}` |
| `read_page` | `read_page(max_chars=12000)` | distilled markdown |
| `find` | `find(selector)` | `{selector, count, sample}` (first ≤10 texts) |
| `wait_for_selector` | `wait_for_selector(selector, timeout=10.0, visible=False)` | `{selector, present, count}` or `{present: false, error}` |
| `click` | `click(selector)` | `{clicked, url}` |
| `type_text` | `type_text(selector, text)` | `{typed_into, chars}` |
| `fill_form` | `fill_form(fields, submit="")` | `{filled, submitted, url}` |
| `scroll` | `scroll(to="bottom")` | `{scrolled}` |
| `extract_links` | `extract_links(selector="a")` | `[{text, href}, …]` |
| `extract_table` | `extract_table(selector="table")` | `[{…}, …]` |
| `eval_js` | `eval_js(script)` | `{result}` |
| `screenshot` | `screenshot(path="servo-shot.png")` | `{path}` (absolute) |
| `status` | `status()` | engine/session status dict |
