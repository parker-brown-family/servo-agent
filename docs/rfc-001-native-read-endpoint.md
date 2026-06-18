# RFC-001 — Native page-read endpoint (Track T3)

> Status: **implemented (v1)**. The `POST /servo/agent/read` extension is live on
> the Servo fork (branch `t3/native-read`) and verified end-to-end; the
> `servo-agent` client exposes it via `ServoBrowser.read_native()` and the
> `read_native` MCP tool (with a 404 fallback to `read_page`). Adds native
> page-content extraction without the slow `execute_script(outerHTML)` round-trip.

## Goal

`POST /session/{id}/servo/agent/read` → returns the current page's main content
computed **natively in the engine**:

```jsonc
{
  "url": "…", "title": "…",
  "text": "…",                         // InnerText of the main-content root
  "headings": [{ "level": 2, "text": "…" }],
  "links":    [{ "text": "…", "href": "…" }]
}
```

This mirrors Servo's existing `/servo/prefs/*` extension for HTTP registration
and the `GetPageSource` / `GetElementText` handlers for the script-thread
round-trip. **Key finding:** the needed primitives already exist in the `script`
crate and are used by current handlers — `HTMLElement.InnerText()` (layout-aware
visible text), `Document.Title()`, `QuerySelectorAll`, `GetElementsByTagName`,
`Element.GetAttribute` — so no JS eval / `outerHTML` serialization is required.

## Why

`read_page` today serializes `document.documentElement.outerHTML` over WebDriver
and distills it in Python. That's a large payload + a JS round-trip per read.
A native endpoint returns just the distilled content, far smaller and faster,
and lets us improve extraction at the source (the T3 differentiation bet).

## Implementation (engine fork — `components/…`, paths repo-relative)

1. **`shared/embedder/webdriver.rs`** — add shared `AgentPageContent` /
   `AgentHeading` / `AgentLink` structs (`Serialize + Deserialize`, they cross
   the IPC boundary) and a `WebDriverScriptCommand::GetAgentPageContent(reply)`
   variant next to `GetPageSource`.
2. **`script/webdriver_handlers.rs`** — new `handle_get_agent_page_content(cx,
   documents, pipeline, reply)`: pick the main root (`main` → `article` → body),
   `InnerText()` for text, `querySelectorAll("h1..h6")` for the heading outline,
   `getElementsByTagName("a")` + `GetAttribute("href")` for links (skip empty /
   `javascript:`, dedup), `Title()` + `url()`. One synchronous pass (rooting-safe,
   mirrors `handle_get_text` / `handle_find_elements_css_selector`).
3. **`script/script_thread.rs`** — dispatch arm routing `GetAgentPageContent` to
   the handler (next to the `GetPageSource` arm).
4. **`webdriver_server/lib.rs`** — `AgentReadParameters`,
   `ServoExtensionRoute::AgentRead` + route row + `command()` arm,
   `ServoExtensionCommand::AgentRead` + `parameters_json` arm,
   `handle_agent_read` (model on `handle_get_page_source`), and the dispatch arm
   in the `WebDriverCommand::Extension` match. Returns
   `WebDriverResponse::Generic(ValueResponse(serde_json::to_value(content)?))`.
5. **Constellation** — verify-only: `handle_webdriver_msg` forwards
   `ScriptCommand` generically; no change expected.

Build & verify: `./mach build -d --media-stack dummy`, then `curl` the endpoint
and `servo-agent selftest`.

## servo-agent (Python) side

Add `ServoBrowser.read_native()` hitting `/servo/agent/read`, and make the
`read_page` MCP tool prefer it, **falling back to the current
`execute_script` extraction on 404** (older servoshell). Gate on a one-time
capability probe or catch the 404.

```python
def read_native(self, timeout=10):
    r = requests.post(f"{self.base}/session/{self.sid}/servo/agent/read",
                      json={}, timeout=timeout)
    r.raise_for_status()
    return r.json()["value"]
```

## Risks / notes

- **Rooting/GC:** keep extraction in one synchronous pass; don't stash unrooted
  pointers (mirror existing handlers).
- **`InnerText` forces a reflow** — fine on a settled page (WebDriver reads after
  load), far cheaper than a JS round-trip; revisit if perf shows up.
- **Accessibility tree:** real computed roles are unimplemented upstream
  (Servo issue #43734). v1 derives the outline from heading tags + landmarks, not
  a true a11y tree. (v2.)
- **Markdown:** v1 ships clean text + structured headings/links; true HTML→md
  serialization is v2.
- **Repo coordination:** all engine edits are additive at well-localized sites in
  5 existing files — land in one branch to avoid clobbering the enum/match blocks
  (watch for concurrent work in the fork).

## Effort

- v1 (text + title + headings + links): **~1.5–2.5 days** (most of it the one
  handler + slow incremental builds on the large tree).
- v2 (markdown serialization + landmark outline): **+1–2 days**.
- Python `read_native()` + fallback: **~0.5 day**.
