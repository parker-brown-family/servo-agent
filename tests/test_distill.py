"""Unit tests for DOM → markdown distillation. No engine required."""
from __future__ import annotations

import re

from servo_agent.distill import (
    _clean_markdown,
    _distill,
    _fallback_markdown,
    _insert_implied_tbody,
    _prepare_html,
    _recover_empty_anchors,
    _unsplittable,
    distill,
)

# A block of filler paragraphs long enough that trafilatura treats the surrounding
# markup as a real article (it ignores tiny snippets). Lets the integration-style
# tests exercise the trafilatura path, not just the bs4 fallback.
_FILLER = "".join(
    f"<p>Filler paragraph number {i} with enough words to make the article body "
    f"substantial and classifiable by the extractor as real content worth keeping "
    f"here today.</p>"
    for i in range(8)
)
_WIKI = "https://en.wikipedia.org/wiki/Python"


def _article(inner: str) -> str:
    return f'<html><body><div class="mw-parser-output">{inner}{_FILLER}</div></body></html>'


# --------------------------------------------------------------------------- #
# Existing behaviour — must stay green.
# --------------------------------------------------------------------------- #
def test_fallback_strips_nav_and_cookie_noise(sample_html: str) -> None:
    md = _fallback_markdown(sample_html).lower()
    assert "primary article body" in md          # main content kept
    assert "accept all cookies" not in md         # consent banner stripped
    assert "nav menu" not in md                   # nav chrome stripped
    assert "footer chrome" not in md              # footer stripped


def test_fallback_keeps_main_links(sample_html: str) -> None:
    md = _fallback_markdown(sample_html)
    assert "https://example.com/one" in md or "Result One" in md


def test_distill_returns_markdown(sample_html: str) -> None:
    md = distill(sample_html, url="https://test.local/sample")
    assert "Primary Title" in md
    assert len(md) > 0


def test_distill_truncates() -> None:
    big = "<main>" + "<p>lorem ipsum dolor sit amet </p>" * 2000 + "</main>"
    md = distill(big, max_chars=200)
    part, marker = md.split("\n\n…[", 1)
    assert len(part) <= 200
    # servo-reader 0.4 recognises truncation by this prefix and an ending of "chars]".
    assert marker.startswith("truncated at ") and md.endswith("chars]")
    assert re.search(r"the next part starts at offset \d+ of \d+ chars\]$", md)


def test_distill_handles_empty() -> None:
    assert isinstance(distill("", url=""), str)


# --------------------------------------------------------------------------- #
# Bug 1 — inline anchor reordered past punctuation (dangling `for .`).
# --------------------------------------------------------------------------- #
def test_clean_fixes_anchor_glued_after_space_period() -> None:
    # The eval's canonical artifact: `for .[verification](…)` — period orphaned
    # before the link. Expect the period relocated to after the link text.
    md = _clean_markdown(
        "needs additional citations for .[verification](https://x/V) Please help."
    )
    assert "for [verification](https://x/V)." in md
    assert "for ." not in md
    assert "for .[" not in md


def test_clean_fixes_anchor_period_then_space_lowercase_link() -> None:
    md = _clean_markdown("reliable sources for. [verification](https://x/V) tail")
    assert "for [verification](https://x/V)." in md


def test_clean_relocates_dangling_period_full_pipeline() -> None:
    html = _article(
        '<p>This article needs additional citations for'
        '<sup>.</sup> <a href="/wiki/Verifiability">verification</a></p>'
    )
    md = distill(html, url=_WIKI)
    # No orphaned "for ." and the link is followed by its period.
    assert "for [verification]" in md
    assert "for . " not in md and "for .[" not in md


def test_clean_leaves_healthy_link_punctuation_untouched() -> None:
    # A real sentence-ending link and a capitalised new-sentence link must NOT move.
    md = _clean_markdown("See [docs](https://x). Read the manual. [Appendix](https://x) ok.")
    assert "[docs](https://x). Read" in md
    assert "manual. [Appendix](https://x)" in md


def test_clean_leaves_legit_comma_link_untouched() -> None:
    md = _clean_markdown("end of clause, [link](https://x) more")
    assert md == "end of clause, [link](https://x) more"


# --------------------------------------------------------------------------- #
# Bug 2 — footnote / citation superscripts split prose.
# --------------------------------------------------------------------------- #
def test_clean_strips_bare_citation_superscript() -> None:
    md = _clean_markdown("Python is popular among [5] programmers worldwide.")
    assert "[5]" not in md
    assert "popular among programmers worldwide." in md


def test_clean_strips_bracketed_number_link_citation() -> None:
    md = _clean_markdown("widely used[[12]](https://en.wikipedia.org/p#cite_note-12) in science")
    assert "[12]" not in md and "[[12]]" not in md
    assert "cite_note" not in md
    assert "widely used in science" in md


def test_clean_strips_double_bracket_superscript() -> None:
    md = _clean_markdown("popular among [[5]] programmers")
    assert "[[5]]" not in md and "[5]" not in md
    assert "popular among programmers" in md


def test_clean_strips_cite_anchor_link_superscript() -> None:
    md = _clean_markdown("a claim[12](https://site/page#cite_note-12) and more")
    assert "[12]" not in md
    assert "a claim and more" in md


def test_clean_preserves_real_inline_links() -> None:
    md = _clean_markdown("see [docs](https://x) and the [API](https://y) reference")
    assert "[docs](https://x)" in md
    assert "[API](https://y)" in md


def test_clean_preserves_code_index_brackets() -> None:
    # `array [0]` / `index [3]` look like footnotes but are code — must survive.
    for src in ("the array [0] element", "index [3] of the list", "row [42] header"):
        assert "[" in _clean_markdown(src), src


def test_clean_strips_superscript_after_punctuation() -> None:
    # Live Wikipedia form: `Python 3.5, [39] capabilities` — the superscript follows
    # a comma+space, not a word char.
    md = _clean_markdown("Beginning with Python 3.5, [39] capabilities were added.")
    assert "[39]" not in md
    assert "Python 3.5, capabilities were added." in md


def test_clean_strips_superscript_after_paren_and_period() -> None:
    md = _clean_markdown("the result (computed).[91]*Process* continues")
    assert "[91]" not in md
    assert "(computed)." in md


def test_clean_strips_wikipedia_editorial_tags() -> None:
    md = _clean_markdown("As of 2026[[update]] the foundation[citation needed] supports it.")
    assert "[update]" not in md and "[[update]]" not in md
    assert "[citation needed]" not in md
    assert "the foundation supports it." in md


def test_clean_strips_orphaned_cite_link() -> None:
    # After the visible [12] is stripped, `](…#cite_note-12)` must not be left behind.
    md = _clean_markdown("a documented claim[12](https://en.wikipedia.org/p#cite_note-12) here")
    assert "cite_note" not in md
    assert "](http" not in md
    assert "a documented claim here" in md


def test_clean_strips_orphaned_url_from_editorial_link() -> None:
    # `[[update]]` rendered as an edit link: after the text is stripped, the bare
    # `(…&action=edit)` target must not remain.
    # Exact live form: the edit URL itself contains a balanced `(programming_language)`
    # paren pair, which must not truncate the strip and orphan `&action=edit)`.
    md = _clean_markdown(
        "As of 2026[[update]]"
        "(https://en.wikipedia.org/w/index.php?title=Python_(programming_language)&action=edit)"
        "[Python Software Foundation](https://en.wikipedia.org/wiki/Python_Software_Foundation) "
        "supports it."
    )
    assert "action=edit" not in md
    assert "index.php" not in md
    assert "[Python Software Foundation]" in md  # real link survives intact


def test_clean_preserves_version_numbers() -> None:
    md = _clean_markdown("Python 3.10 and release [10] are different")
    assert "Python 3.10" in md            # version untouched
    assert "release [10]" not in md       # standalone superscript stripped


def test_clean_strips_superscripts_full_pipeline() -> None:
    html = _article(
        '<p>Python is popular among<sup class="reference">'
        '<a href="#cite_note-5">[5]</a></sup> programmers and widely used'
        '<sup class="reference"><a href="#cite_note-12">[12]</a></sup> in science.</p>'
    )
    md = distill(html, url=_WIKI)
    assert "[5]" not in md and "[12]" not in md
    assert "popular among programmers" in md


# trafilatura >= 2.2 keeps <sup> as literal HTML in its markdown and escapes the
# brackets in link text (`<sup>[\[5\]](…#cite_note-5)</sup>`), so citations are
# removed from the HTML, before extraction, where their structure still shows.
def test_distill_strips_live_wikipedia_reference_markup() -> None:
    # Live Parsoid forms (2026-10): a numbered reference and a [citation needed] tag.
    html = _article(
        "<p>Python is popular among programmers"
        '<sup class="mw-ref reference" id="cite_ref-19"><a href="#cite_note-19">'
        '<span class="mw-reflink-text"><span class="cite-bracket">[</span>17'
        '<span class="cite-bracket">]</span></span></a></sup> and the foundation'
        '<sup class="noprint Inline-Template Template-Fact">[<i>'
        '<a href="https://en.wikipedia.org/wiki/Wikipedia:Citation_needed">'
        "citation needed</a></i>]</sup> supports it.</p>"
    )
    md = distill(html, url=_WIKI)
    assert "<sup" not in md
    assert "17" not in md and "cite_note" not in md
    assert "citation needed" not in md.lower()
    assert "popular among programmers and the foundation supports it." in md


def test_prepare_drops_footnote_link_superscripts() -> None:
    # Pandoc / GitHub-style footnote references: a superscript whose links all
    # point at a footnote anchor.
    out = _prepare_html(
        '<p>One<sup id="fnref1"><a href="#fn1" role="doc-noteref">1</a></sup> and'
        ' two<sup><a href="#user-content-fn-2" data-footnote-ref="">2</a></sup>.</p>'
    )
    assert "<sup" not in out
    assert "One and two." in out


def test_distill_keeps_content_superscripts() -> None:
    # An exponent is content, not a citation. trafilatura 2.1 flattens it to `mc2`;
    # 2.2+ keeps the tag. Either way the 2 must survive.
    md = distill(_article("<p>The relation E = mc<sup>2</sup> links mass and energy.</p>"),
                 url=_WIKI)
    assert re.search(r"mc(?:<sup>)?2", md)


def test_prepare_unwraps_punctuation_only_superscript() -> None:
    out = _prepare_html('<p>citations for<sup>.</sup> <a href="/v">verification</a></p>')
    assert "for. <a" in out


# --------------------------------------------------------------------------- #
# Bug 3 — nested-list markers leak mid-sentence.
# --------------------------------------------------------------------------- #
def test_clean_removes_inline_leaked_bullet() -> None:
    md = _clean_markdown("used in modern- web applications across the board")
    assert "modern- web" not in md
    assert "modern web applications" in md


def test_clean_keeps_hyphenated_compounds() -> None:
    for word in ("well-known", "state-of-the-art", "open-source", "real-time"):
        md = _clean_markdown(f"a {word} thing")
        assert word in md, word


def test_clean_rejoins_split_midsentence_list() -> None:
    # trafilatura/markdownify split an inline mid-sentence list into its own block.
    md = _clean_markdown(
        "Used in modern\n\n- web applications and services\n\nacross the board today."
    )
    assert "Used in modern web applications and services across the board today." in md
    assert "\n- web applications" not in md


def test_clean_preserves_genuine_lists() -> None:
    # Multi-item list after a properly terminated sentence must stay a list.
    src = "Features include:\n\n- fast startup\n- memory safety\n- strong typing\n\nMore text."
    md = _clean_markdown(src)
    assert "- fast startup" in md
    assert "- memory safety" in md
    assert "- strong typing" in md


def test_clean_preserves_single_item_list_after_sentence() -> None:
    src = "Here is the only option.\n\n- the single option\n\nDone."
    md = _clean_markdown(src)
    assert "- the single option" in md


def test_clean_heals_inline_bullet_full_pipeline() -> None:
    html = _article(
        "<p>The language is used in modern<ul><li>web applications</li></ul></p>"
    )
    md = distill(html, url=_WIKI)
    assert "modern- web" not in md  # no glued bullet leaked into prose


# --------------------------------------------------------------------------- #
# Bug 4 — table cell containing only a link is dropped.
# --------------------------------------------------------------------------- #
def test_recover_empty_anchor_fills_href_text() -> None:
    html = '<a class="external" href="https://github.com/python/cpython"></a>'
    out = _recover_empty_anchors(html)
    assert "github.com/python/cpython" in out


def test_recover_empty_anchor_ignores_in_page_and_texted_links() -> None:
    html = (
        '<a href="#section">jump</a>'           # has text — untouched
        '<a href="#cite_note-1"></a>'           # in-page anchor — skipped
        '<a href="javascript:void(0)"></a>'     # non-navigational — skipped
    )
    out = _recover_empty_anchors(html)
    assert ">jump<" in out
    assert "#cite_note-1" in out  # still empty, not filled with a useless fragment


def test_fallback_recovers_link_only_table_cell() -> None:
    html = (
        '<main><table class="infobox"><tbody>'
        '<tr><th>Repository</th><td>'
        '<a class="external text" href="https://github.com/python/cpython"></a>'
        "</td></tr>"
        "<tr><th>License</th><td>PSF</td></tr>"
        "</tbody></table></main>"
    )
    md = _fallback_markdown(html)
    assert "github.com/python/cpython" in md
    # The Repository cell is no longer empty.
    assert "| Repository |  |" not in md


def test_recover_empty_anchor_skips_absolutized_in_page_anchor() -> None:
    # read_html() absolutizes `#cite_note-1` in the page before distill sees it; it
    # is still an in-page anchor and must not be filled with its own URL.
    page = "https://en.wikipedia.org/wiki/Python"
    out = _recover_empty_anchors(f'<a href="{page}#cite_note-1"></a>', url=page)
    assert "></a>" in out


def test_recover_empty_anchor_text_uses_resolved_href() -> None:
    out = _recover_empty_anchors('<a href="/python/cpython"></a>', url="https://github.com/")
    assert ">github.com/python/cpython<" in out


def test_distill_recovers_link_only_cell_full_pipeline() -> None:
    html = _article(
        '<table class="infobox"><tbody>'
        '<tr><th>Repository</th><td>'
        '<a class="external text" href="https://github.com/python/cpython"></a>'
        "</td></tr>"
        "<tr><th>License</th><td>PSF</td></tr>"
        "</tbody></table>"
    )
    md = distill(html, url=_WIKI)
    assert "github.com/python/cpython" in md
    assert "| Repository | |" not in md  # not collapsed empty


# --------------------------------------------------------------------------- #
# Bug 5 — Docusaurus admonition markers leak raw.
# --------------------------------------------------------------------------- #
def test_clean_unwraps_admonition_markers() -> None:
    md = _clean_markdown(":::note\n\nYou need Node 18+ installed.\n\n:::")
    assert ":::" not in md
    assert "You need Node 18+ installed." in md
    assert "**Note:**" in md


def test_clean_unwraps_admonition_with_title() -> None:
    md = _clean_markdown(":::warning Be careful here\nThis is risky.\n:::")
    assert ":::" not in md
    assert "**Be careful here:**" in md
    assert "This is risky." in md


def test_clean_unwraps_admonitions_full_pipeline() -> None:
    html = (
        '<html><body><div class="markdown"><h1>Setup</h1>'
        '<div class="admonition admonition-note"><div class="admonition-content">'
        "<p>:::note</p><p>You need Node 18+ installed first.</p><p>:::</p>"
        f"</div></div>{_FILLER}</div></body></html>"
    )
    md = distill(html, url="https://docusaurus.io/docs")
    assert ":::" not in md
    assert "You need Node 18+ installed first." in md


# --------------------------------------------------------------------------- #
# Bug 6 — relative links resolved against the domain root instead of the page.
# distill() is also fed raw HTTP HTML (servo-reader) that read_html() never
# absolutized; trafilatura alone turned `#sec` into https://host#sec.
# --------------------------------------------------------------------------- #
_PAGE = "https://book.example.org/embedding/overview.html"
_RELATIVE_LINKS = (
    '<p>Read <a href="building.html">the build guide</a> and then '
    '<a href="#sec">this section</a> before embedding.</p>'
)


def test_distill_resolves_relative_links_against_the_page() -> None:
    md = distill(_article(_RELATIVE_LINKS), url=_PAGE)
    assert "(https://book.example.org/embedding/building.html)" in md
    assert "(https://book.example.org/embedding/overview.html#sec)" in md
    assert "(https://book.example.org/building.html)" not in md
    assert "https://book.example.org#sec" not in md


def test_fallback_resolves_relative_links_against_the_page() -> None:
    md = _fallback_markdown(f"<main>{_RELATIVE_LINKS}</main>", _PAGE)
    assert "(https://book.example.org/embedding/building.html)" in md
    assert "(https://book.example.org/embedding/overview.html#sec)" in md


def test_distill_honours_base_href() -> None:
    html = (
        '<html><head><base href="https://cdn.example.org/docs/"></head><body><main>'
        '<p>See <a href="guide.html">the guide</a> for the setup steps.</p>'
        "</main></body></html>"
    )
    md = distill(html, url=_PAGE)
    assert "(https://cdn.example.org/docs/guide.html)" in md


# --------------------------------------------------------------------------- #
# Cleanup must never damage ordinary content.
# --------------------------------------------------------------------------- #
def test_clean_preserves_links_with_parens_in_url() -> None:
    # The orphan-URL strip must never touch a genuine link whose target contains
    # parentheses (common in Wikipedia titles).
    src = "See [Python](https://en.wikipedia.org/wiki/Python_(programming_language)) docs."
    md = _clean_markdown(src)
    assert "[Python](https://en.wikipedia.org/wiki/Python_(programming_language))" in md


def test_clean_is_noop_on_plain_prose() -> None:
    src = (
        "# Heading\n\n"
        "A normal paragraph with a [real link](https://example.com) and a list:\n\n"
        "- first item\n- second item\n\n"
        "A closing sentence with proper punctuation, parentheses (like this), "
        "and version 3.10 mentioned inline.\n"
    )
    assert _clean_markdown(src) == src


def test_clean_handles_empty_string() -> None:
    assert _clean_markdown("") == ""


# --------------------------------------------------------------------------- #
# Issue #12 — a long page is read in parts, in order, from an offset.
# --------------------------------------------------------------------------- #
_NEXT = re.compile(
    r"\n\n…\[truncated at \d+ chars; the next part starts at offset (\d+) of \d+ chars\]$"
)


def _long_page() -> str:
    paras = "".join(
        f'<p>Paragraph {i} explains <a href="https://example.org/docs/page-{i}">the page '
        f"numbered {i}</a> in enough words that the section reads as running prose.</p>"
        + (f"<pre><code>step_{i}()\nstep_{i}_again()</code></pre>" if i % 7 == 0 else "")
        for i in range(120)
    )
    return f"<html><body><article><h1>A long page</h1>{paras}</article></body></html>"


def _read_in_parts(html: str, max_chars: int) -> list[str]:
    parts, offset = [], 0
    while True:
        md, meta = _distill(html, "https://example.org/long", max_chars=max_chars, offset=offset)
        m = _NEXT.search(md)
        parts.append(md[: m.start()] if m else md)
        if not m:
            assert meta["next_offset"] is None
            return parts
        assert meta["next_offset"] == int(m[1]) > offset
        offset = int(m[1])


def test_read_in_parts_adds_up_to_the_whole_page() -> None:
    html = _long_page()
    whole, meta = _distill(html, "https://example.org/long", max_chars=10**9)
    parts = _read_in_parts(html, max_chars=2000)
    assert len(parts) > 3
    assert "".join(parts) == whole
    assert all(len(p) <= 2000 for p in parts)
    assert meta["total_chars"] == len(whole) and meta["next_offset"] is None


def test_parts_never_end_inside_a_link_or_code_block() -> None:
    html = _long_page()
    whole, _ = _distill(html, "https://example.org/long", max_chars=10**9)
    spans = _unsplittable(whole)
    assert any(whole[s:e].startswith("`") or "```" in whole[s:e] for s, e in spans)
    cut = 0
    for part in _read_in_parts(html, max_chars=1500)[:-1]:
        cut += len(part)
        assert not any(s < cut < e for s, e in spans), whole[cut - 40: cut + 40]


def test_a_page_under_the_cap_reads_the_same_as_before() -> None:
    html = _article("<p>A short page with one paragraph of content.</p>")
    assert distill(html, url=_WIKI) == distill(html, url=_WIKI, offset=0)
    assert "truncated" not in distill(html, url=_WIKI)


def test_offset_past_the_end_says_so_and_negative_offsets_are_refused() -> None:
    html = _long_page()
    md, meta = _distill(html, "https://example.org/long", offset=10**8)
    assert "past the end" in md and meta["next_offset"] is None
    try:
        _distill(html, "https://example.org/long", offset=-1)
    except ValueError:
        pass
    else:
        raise AssertionError("a negative offset must be refused")


# --------------------------------------------------------------------------- #
# Bug 7 (issue #13) — rows served without <tbody> lose every link on a plain
# download; a browser inserts the <tbody>, so the Servo path kept them.
# --------------------------------------------------------------------------- #
def test_plain_download_of_a_table_listing_keeps_every_story_link() -> None:
    from fixtures.table_listing import STORIES, listing_html

    md = distill(listing_html(), url="https://news.example/", max_chars=10**9)
    for i in range(1, STORIES + 1):
        assert f"[Story number {i} about rendering engines](https://example.org/story/{i})" in md


def test_implied_tbody_wraps_bare_rows_and_leaves_sections_alone() -> None:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(
        "<table><thead><tr><th>h</th></tr></thead><tr><td>1</td></tr>\n<tr><td>2</td></tr>"
        "<tfoot><tr><td>f</td></tr></tfoot></table>"
        "<table><tbody><tr><td>already</td></tr></tbody></table>",
        "html.parser",
    )
    assert _insert_implied_tbody(soup)
    first, second = soup.find_all("table", recursive=False)
    assert [c.name for c in first.children if c.name] == ["thead", "tbody", "tfoot"]
    assert len(first.tbody.find_all("tr")) == 2
    assert len(second.find_all("tbody")) == 1
    assert not _insert_implied_tbody(soup)  # nothing left to wrap
