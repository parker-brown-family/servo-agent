# Roadmap

`servo-agent` advances on four parallel tracks. The short version: drive real
work to find gaps (T1), grow the external tooling (T2), and — the headline bet —
push richer reads **in-tree** inside Servo itself (T3), all while hardening the
package (T4).

## T1 — Drive real tasks

**Status: ongoing.** Use the agent on real browsing/QA/scrape jobs and let the
friction surface the gaps. The other tracks are prioritized by what T1 turns up.

## T2 — Expand external tooling

**Status: shipped (multi-tab next).** The external-tooling layer — things
implemented over stock Servo's WebDriver, no engine changes — now includes:

- `wait_for_selector` — poll for an element (optionally visible). ✅
- `scroll` — to bottom/top, a selector, or a pixel offset. ✅
- `extract_links` — `{text, href}` with absolute hrefs. ✅
- `extract_table` — a `<table>` to row dicts keyed by header. ✅
- `fill_form` — map of `{selector: value}` with optional submit. ✅

**Next on this track: multi-tab** support, so an agent can hold several documents
open at once.

## T3 — In-tree native reads (the research bet)

**Status: planned — the high-leverage track.** Today `read_page` reconstructs
content from the DOM via `execute_script` roundtrips. The in-tree step does it at
the source, inside the engine:

- **Native DOM / accessibility-tree extraction** in Servo's `script` crate —
  walk the live tree in Rust instead of shipping scripts in and HTML out.
- **A WebDriver extension endpoint**, `/session/{id}/servo/agent/read`, that
  mirrors Servo's existing `/servo/prefs/*` extension pattern, so the agent asks
  the engine directly for distilled content.

The payoff is **richer and cheaper** reads — accessibility-aware structure,
fewer roundtrips, less per-call overhead — than the `execute_script` path can
offer. This is the part that justifies owning the engine rather than renting a
remote browser.

## T4 — Preserve & harden

**Status: ongoing (this is part of it).** Packaging, tests, CI, and docs —
including this documentation set. Unit tests run everywhere; integration tests
auto-skip without a built binary (see [Contributing](contributing.md)), so the
suite stays green on a fresh checkout.
