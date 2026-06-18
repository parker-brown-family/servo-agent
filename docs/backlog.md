# Backlog — from the first real-task evaluation (T1)

A real multi-page research run (Selenium/Playwright/Puppeteer/Lightpanda across
Wikipedia, Docusaurus SPAs, and GitHub) surfaced this prioritized list. **The
engine rendered everything faithfully; nearly all rough edges are harness-level.**

## P0 — unblock the toolbelt
- [ ] **Permission allowlist** — in non-interactive/subagent contexts, `find`,
  `extract_links`, `extract_table`, `eval_js`, `wait_for_selector` get denied by
  the MCP permission policy, leaving only `open_url` + `read_page`. Add the
  `servo-agent` tools to the Claude Code / Codex allowlist so an agent can
  actually navigate and extract. *(Config, not product code.)*

## P1 — harden `read_page` distillation (deterministic, testable)
- [ ] Inline anchors get **reordered past punctuation** → dangling `for .`
  (link text moved after the period).
- [ ] **Footnote superscripts** (`[1]`,`[12]`) interleave into prose, splitting
  sentences — strip or relocate to a references block.
- [ ] **Nested-list `- ` injected mid-sentence** (`in modern- web applications`).
- [ ] **Table cells with only a link dropped** (Wikipedia infobox "Repository"
  rendered empty).
- [ ] **Docusaurus `:::note` / `:::` admonition markers leak** raw into output.
- [ ] Tabbed code blocks (npm/yarn/pnpm/Bun) flattened with no active-tab signal *(minor)*.

→ One focused pass on `src/servo_agent/distill.py` (+ fixtures covering each case
in `tests/test_distill.py`).

## P2 — new tooling over WebDriver (T2)
- [ ] **`networkidle` / load-settle wait** — `<title>` sometimes read before SPA
  hydration; navigation should optionally wait for the page to settle.
- [ ] **Console / network-error capture** — when a page's JS crashes, there's no
  way to see *what* threw (needed to triage engine gaps; see P3).
- [ ] **Screenshot options** — width/height/full-page (currently fixed 1024-wide).

## P3 — real engine gap (T3)
- [ ] **`lightpanda.io` (Next.js SPA) crashes to its React error boundary** in
  Servo — a genuine web-platform gap. Needs the console-capture tool (P2) to
  identify the throwing API, then upstream/in-tree work. The *only* finding that
  isn't harness-level.

## Related
- Native page-read endpoint design → [`rfc-001-native-read-endpoint.md`](rfc-001-native-read-endpoint.md).
- Verdict: invest in **read_page polish + waits/diagnostics** first (highest
  leverage, all in this repo); the engine is solid.
