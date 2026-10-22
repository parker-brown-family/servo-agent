"""DOM → clean markdown distillation — the value-add of the harness.

Turns a rendered page's HTML into token-efficient markdown an agent can read:
trafilatura for article-shaped pages, a noise-stripping BeautifulSoup +
markdownify fallback for thin/utility pages. Pure functions, no engine
required, so this module is fully unit-testable offline.

Both extractors leave reproducible markdown defects on real pages (Wikipedia,
Docusaurus). Two deterministic cleanup passes harden the output:

* ``_prepare_html`` runs on the *raw HTML* before either extractor: it resolves
  relative links against the page URL (honouring ``<base href>``), removes
  citation superscripts while they are still identifiable by structure, and
  gives a table cell whose only content is a link (e.g. a Wikipedia infobox
  "Repository" row) visible text instead of an empty cell.
* ``_clean_markdown`` runs on the *produced markdown* to fix link/punctuation
  reordering, strip citation superscripts, heal mid-sentence list-marker leaks,
  and unwrap Docusaurus ``:::`` admonition fences.

Every transform is conservative — it targets a specific defect signature and is
covered by a focused unit test in ``tests/test_distill.py``.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urldefrag, urljoin, urlsplit

# Substrings in id/class that mark navigation / consent / promo chrome.
_NOISE_TOKENS = (
    "cookie", "consent", "gdpr", "banner", "navbar", "menu", "sidebar",
    "footer", "header", "popup", "modal", "newsletter", "subscribe",
    "advert", "promo", "social-share", "breadcrumb",
)
# Tags that are never primary content.
_DROP_TAGS = (
    "script", "style", "noscript", "template", "svg", "iframe",
    "nav", "header", "footer", "aside", "form", "button", "dialog",
)
# ARIA landmark roles that are never primary content.
_DROP_ROLES = ("navigation", "banner", "contentinfo", "search", "dialog", "alertdialog")


# --------------------------------------------------------------------------- #
# Raw-HTML repairs — Bugs 2 (at the source), 4 and 6. They run on the parsed page
# *before* either extractor, in one parse, so the trafilatura path (a black box we
# otherwise can't reach into) and the markdownify fallback both benefit.
# ``_prepare_html`` applies all of them.
# --------------------------------------------------------------------------- #
def _fragment(href: str) -> str:
    try:
        return urlsplit(href).fragment
    except ValueError:  # malformed (e.g. a broken IPv6 host) — no fragment
        return ""


# Bug 2, at the source — citation superscripts. Since trafilatura 2.2 the markdown
# serializer keeps <sup> as literal HTML and escapes brackets in link text, so a
# Wikipedia reference arrives as `<sup>[\[5\]](…#cite_note-5)</sup>` and the
# markdown-level strips below no longer match it. In the HTML a citation is still
# identifiable by structure: Wikipedia's reference / editorial-tag classes, links
# that all point at a footnote anchor, or text that is only a bracketed number or
# an editorial tag (`_FN_EDITORIAL`, defined with the markdown strips below). Such
# superscripts are removed; one holding only punctuation is unwrapped to plain
# text. Every other superscript is content (`mc<sup>2</sup>`) and stays.
_CITE_SUP_CLASSES = frozenset({"reference", "noprint", "inline-template"})
_FOOTNOTE_FRAGMENT = re.compile(r"(?:^|[-_])(?:cite|fn|foot|note|endnote|ref)", re.IGNORECASE)
_BRACKETED_NUMBER = re.compile(r"\[\s*\d{1,4}\s*\]")
_PUNCT_ONLY = re.compile(r"[.,;:!?]+")


def _is_citation_sup(sup: Any) -> bool:
    if {c.lower() for c in sup.get("class") or []} & _CITE_SUP_CLASSES:
        return True
    text = sup.get_text(strip=True)
    links = sup.find_all("a", href=True)
    if links and len(text) <= 12 and all(
        a.get("role") == "doc-noteref" or _FOOTNOTE_FRAGMENT.search(_fragment(a["href"]))
        for a in links
    ):
        return True
    return bool(_BRACKETED_NUMBER.fullmatch(text) or _FN_EDITORIAL.fullmatch(text))


def _drop_citation_superscripts(soup: Any) -> bool:
    changed = False
    for sup in soup.find_all("sup"):
        if sup.decomposed:
            continue  # nested inside a superscript already removed
        if _is_citation_sup(sup):
            sup.decompose()
            changed = True
            continue
        text = sup.get_text(strip=True)
        if _PUNCT_ONLY.fullmatch(text):
            sup.replace_with(text)  # `for<sup>.</sup> [link]` reads as `for. [link]`
            changed = True
    return changed


# Bug 4 — table cell whose only content is a link renders empty. An anchor with no
# visible text but a real href gets visible text derived from the href. See tests:
# test_*recovers_link_only_*cell*.
def _fill_empty_anchors(soup: Any, base: str = "", page_url: str = "") -> bool:
    """Give empty ``<a href>`` anchors visible text from their href.

    Wikipedia infobox cells (and similar) often hold a single link whose text
    lives in a child that gets stripped, leaving ``<a href="…"></a>`` — which
    markdownify and trafilatura both render as an empty cell. We fill the anchor
    with a readable form of the href so the cell survives distillation.
    """
    same_document = {urldefrag(u).url for u in (page_url, base) if u}
    changed = False
    for a in soup.find_all("a"):
        if a.get_text(strip=True):
            continue  # already has visible text — leave it alone
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue  # in-page / non-navigational — no useful text to recover
        try:
            target = urljoin(base, href) if base else href
            document, fragment = urldefrag(target)
        except ValueError:
            continue  # malformed href — nothing readable to derive
        if fragment and document in same_document:
            continue  # an in-page anchor that read_html() already absolutized
        a.string = re.sub(r"^[a-z][a-z0-9+.-]*://", "", target).rstrip("/")
        changed = True
    return changed


# Bug 6 — relative links resolved against the domain root. trafilatura resolves a
# relative href against scheme://host only, so on a page at /embedding/overview.html
# `building.html` became https://host/building.html and `#sec` became https://host#sec.
# read_html() absolutizes in the page, but distill() is also fed raw HTTP HTML
# (servo-reader), so resolve here against the full page URL, honouring <base href>
# the way a browser does. Absolute URLs pass through unchanged.
def _document_base(soup: Any, url: str) -> str:
    """The URL relative references resolve against: ``<base href>``, else the page."""
    tag = soup.find("base", href=True)
    if tag is not None:
        try:
            return urljoin(url, tag["href"].strip())
        except ValueError:
            pass
    return url


def _absolutize_links(soup: Any, base: str) -> bool:
    if not base:
        return False
    targets = [(a, "href") for a in soup.find_all("a", href=True)]
    targets += [(e, "src") for e in soup.find_all(["img", "source"], src=True)]
    changed = False
    for tag, attr in targets:
        value = tag[attr]
        try:
            absolute = urljoin(base, value.strip())
        except ValueError:
            continue  # malformed — leave it exactly as the page had it
        if absolute != value:
            tag[attr] = absolute
            changed = True
    return changed


# Bug 7 — table rows with no <tbody> lose every link (issue #13). Hacker News, and
# listings and forums laid out the same way, serve <tr> directly inside <table>.
# A browser's parser inserts the <tbody>, so Servo's DOM has one and read_page kept
# all 211 links on HN's front page; a plain download has none, and trafilatura
# returned the page as loose words with 0 links. Insert the <tbody> the way the
# HTML parser does: each run of rows directly inside a table becomes one section.
def _insert_implied_tbody(soup: Any) -> bool:
    changed = False
    for table in soup.find_all("table"):
        run: list[Any] = []
        for child in [*table.children, None]:  # None flushes the last run
            name = getattr(child, "name", None)
            if name == "tr":
                run.append(child)
                continue
            if child is not None and name is None and not str(child).strip():
                continue  # whitespace between rows stays where it is
            if run:
                body = soup.new_tag("tbody")
                run[0].insert_before(body)
                for row in run:
                    body.append(row.extract())
                run = []
                changed = True
    return changed


def _repair_soup(soup: Any, url: str = "") -> bool:
    """Apply the raw-HTML repairs in place; return whether anything changed."""
    base = _document_base(soup, url)
    changed = _insert_implied_tbody(soup)
    changed |= _drop_citation_superscripts(soup)
    changed |= _fill_empty_anchors(soup, base, url)  # sees the original #fragment hrefs
    changed |= _absolutize_links(soup, base)
    return changed


def _prepare_html(html: str, url: str = "") -> str:
    """Raw HTML → the repaired HTML both extractors read."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    return str(soup) if _repair_soup(soup, url) else html


def _recover_empty_anchors(html: str, url: str = "") -> str:
    """Bug 4 on its own: fill empty ``<a href>`` anchors (see ``_fill_empty_anchors``)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    filled = _fill_empty_anchors(soup, _document_base(soup, url), url)
    return str(soup) if filled else html


def _fallback_markdown(html: str, url: str = "") -> str:
    """Body-level HTML → markdown with nav-chrome / cookie-banner noise removed."""
    from bs4 import BeautifulSoup
    from markdownify import markdownify as mdify

    soup = BeautifulSoup(html, "html.parser")
    try:
        _repair_soup(soup, url)
    except Exception:  # noqa: BLE001 — repairs are best-effort, never fatal
        pass
    for tag in soup(list(_DROP_TAGS)):
        tag.decompose()
    for role in _DROP_ROLES:
        for tag in soup.select(f'[role="{role}"]'):
            tag.decompose()
    for tag in soup.find_all(attrs={"class": True}) + soup.find_all(attrs={"id": True}):
        ident = (" ".join(tag.get("class", [])) + " " + (tag.get("id") or "")).lower()
        if any(tok in ident for tok in _NOISE_TOKENS):
            tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    return mdify(str(root), heading_style="ATX").strip()


# --------------------------------------------------------------------------- #
# Markdown post-processing — Bugs 1, 2, 3, 5.
# --------------------------------------------------------------------------- #

# Bug 1 — an inline link whose preceding sentence punctuation is orphaned, so the
# link text lands *before* the period (`needs additional citations for .[verification]`
# → dangling `for .`). Move the orphaned punctuation to *after* the link text.
# Fires only on the broken signatures (space before punct, punct glued to link, or
# a period + space + lowercase-continuation link); a healthy `word, [link]` or a
# capitalised new-sentence `manual. [Appendix]` is left untouched.
_DANGLE_LINK = re.compile(
    r"(?P<pre>\w)"
    r"(?:"
    r"[ \t]+(?P<pa>[.,;:])[ \t]*"          # A: whitespace before the punctuation
    r"|"
    r"(?P<pb>[.,;:])(?P<gap>[ \t]*)"       # B: punct glued to link / C: punct + space
    r")"
    r"\[(?P<ltext>[^\]\n]+)\]\((?P<url>[^)\s]+)\)"
)


def _fix_dangling_links(md: str) -> str:
    def repl(m: re.Match[str]) -> str:
        link = f"[{m['ltext']}]({m['url']})"
        if m.group("pa") is not None:
            punct = m.group("pa")  # A — orphaned punctuation, always relocate
        else:
            punct = m.group("pb")
            if m.group("gap"):
                # Space after the punctuation: only a sentence period followed by a
                # lowercase-continuation link is the reorder bug; commas/semicolons or
                # a capitalised new-sentence link are healthy and left as-is.
                if punct != "." or not m["ltext"][:1].islower():
                    return m.group(0)
            # gap == "" → punctuation glued directly to the link, always relocate.
        return f"{m['pre']} {link}{punct}"

    return _DANGLE_LINK.sub(repl, md)


# Bug 2 — footnote / citation superscripts (`[1]`, `[12]`, `[[5]]`, those forms
# rendered as a link to a #cite/#fn/#note anchor, and Wikipedia editorial tags such
# as `[update]` / `[citation needed]`) interleave into prose and split sentences.
# Strip them. Real inline links, version numbers (`Python 3.10`), and bracketed code
# indices (numeric brackets right after a word like "array"/"index") are preserved.
# Forms below were confirmed against a live render of the Wikipedia "Python
# (programming language)" article.
_FN_CITE_LINK = re.compile(                                            # [12](…#cite…), [[12]](…)
    r"\[+\d{1,4}\]+\([^)\s]*#(?:cite|fn|foot|note|_note|endnote|ref)[^)\s]*\)",
    re.IGNORECASE,
)
_FN_DOUBLE_BRACKET = re.compile(r"\[\[\d{1,4}\]\]")                     # leftover [[5]]
_FN_EDITORIAL = re.compile(                                            # [update], [citation needed]
    r"\[+(?:update|citation needed|clarification needed|when\??|who\??|why\??|"
    r"dubious[^\]]*|verification needed|page needed|according to whom\??|by whom\??|"
    r"original research[^\]]*|better source needed|further explanation needed)\]+",
    re.IGNORECASE,
)
# A bare [n] superscript attaches after a word, sentence punctuation, or a closing
# bracket/paren/quote on Wikipedia — match all of those as the lead char.
_FN_BARE = re.compile(r"""(?P<lead>[\w.,;:!?)\]"'])[ \t]?\[(?P<n>\d{1,4})\](?!\()""")
# An empty-text link left pointing at a cite/note anchor once its [n] text is stripped.
_FN_EMPTY_CITE_LINK = re.compile(
    r"\]\([^)\s]*#(?:cite|fn|foot|note|_note|endnote)[^)\s]*\)", re.IGNORECASE
)
# A bare `(url)` target with no preceding `]` — what remains when an inline link's
# `[text]` (e.g. a `[[update]]` editorial tag) was removed but its target survived.
# The `(?<!\])` guard keeps real `[text](url)` links intact; the inner group tolerates
# one level of balanced parens so Wikipedia titles like `Python_(programming_language)`
# don't truncate the match and orphan the URL's tail.
_ORPHAN_URL_TARGET = re.compile(r"(?<!\])\(https?://[^()\s]*(?:\([^()\s]*\)[^()\s]*)*\)")
_CODE_INDEX_WORD = re.compile(
    r"(?:index|indices|array|arrays|element|elements|item|items|position|offset|"
    r"byte|bit|line|lines|col|column|row|page|slot|key|arg|args|param|version|"
    r"step|node|level|table|figure|fig|eq|equation)\Z",
    re.IGNORECASE,
)


def _strip_footnotes(md: str) -> str:
    md = _FN_CITE_LINK.sub("", md)
    md = _FN_DOUBLE_BRACKET.sub("", md)
    md = _FN_EDITORIAL.sub("", md)

    def bare(m: re.Match[str]) -> str:
        lead = m.group("lead")
        if lead.isalnum():
            # Only an alphanumeric lead can be a code index (`array [0]`); reconstruct
            # the full preceding word and keep the brackets if it's an indexing term.
            word = re.search(r"(\w+)\Z", md[max(0, m.start("lead") - 24): m.start("lead") + 1])
            if word and _CODE_INDEX_WORD.search(word.group(1)):
                return m.group(0)
        return lead  # drop the [n], keep the leading character

    md = _FN_BARE.sub(bare, md)
    # Stripping a [n] whose markdown was `[n](…#cite…)` leaves an orphaned `](url)`.
    md = _FN_EMPTY_CITE_LINK.sub("", md)
    # Removing a bracketed editorial link's text leaves a bare `(url)` target behind.
    md = _ORPHAN_URL_TARGET.sub("", md)
    return md


# Bug 3a — a nested-list bullet leaked into running text (`in modern- web
# applications`). Remove a hyphen-bullet glued after a word and followed by a
# lowercase word. Hyphenated compounds (`well-known`, `state-of-the-art`) have no
# space after the hyphen and are untouched.
_INLINE_BULLET = re.compile(r"(?<=\w)-[ \t]+(?=[a-z])")

# Bullet at the start of a markdown line.
_LIST_ITEM = re.compile(r"^[ \t]*[-*+][ \t]+(?P<text>\S.*)$")
# A line that ends a sentence (terminal punctuation, optionally quoted/closed).
_SENTENCE_END = re.compile(r"""[.!?:;]["')\]]?\s*$""")


def _heal_list_leaks(md: str) -> str:
    md = _INLINE_BULLET.sub(" ", md)

    # Bug 3b — trafilatura sometimes splits a *mid-sentence* inline list into its own
    # one-item block, leaving an unterminated lead, a lone `- item`, then a lowercase
    # continuation. Rejoin those three fragments into one sentence. Genuine lists
    # (multi-item, or following a terminated sentence) are left intact.
    lines = md.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        item = _LIST_ITEM.match(line)
        if item and out:
            j = len(out) - 1
            while j >= 0 and not out[j].strip():
                j -= 1
            prev = out[j] if j >= 0 else ""
            k = i + 1
            while k < n and not lines[k].strip():
                k += 1
            nxt = lines[k] if k < n else ""
            prev_open = bool(prev.strip()) and not _SENTENCE_END.search(prev) and \
                prev.lstrip()[:1] not in {"#", "|", "-", "*", "+", ">"}
            single = not _LIST_ITEM.match(nxt)          # the bullet block is one item
            nxt_continues = bool(nxt) and nxt[:1].islower()
            if prev_open and single and nxt_continues:
                out[j] = f"{prev.rstrip()} {item['text'].strip()} {nxt.lstrip()}".rstrip()
                del out[j + 1:]
                i = k + 1
                continue
        out.append(line)
        i += 1
    return "\n".join(out)


# Bug 5 — Docusaurus admonition fences (`:::note`, `:::tip Heading`, closing `:::`)
# leak raw into output. Surface the opener as a bold label and drop the bare closer,
# keeping the inner content.
_ADMONITION_TYPES = (
    "note", "tip", "info", "warning", "caution", "danger",
    "important", "success", "secondary", "abstract", "question",
)
_ADMON_OPEN = re.compile(
    rf"^\s*:::+\s*(?P<kind>{'|'.join(_ADMONITION_TYPES)})\b(?P<title>.*)$",
    re.IGNORECASE,
)
_ADMON_CLOSE = re.compile(r"^\s*:::+\s*$")


def _unwrap_admonitions(md: str) -> str:
    out: list[str] = []
    for line in md.split("\n"):
        opener = _ADMON_OPEN.match(line)
        if opener:
            title = opener["title"].strip()
            label = title or opener["kind"].strip().capitalize()
            out.append(f"**{label}:**")
            continue
        if _ADMON_CLOSE.match(line):
            continue  # drop the bare closing fence
        out.append(line)
    return "\n".join(out)


def _clean_markdown(md: str) -> str:
    """Apply the deterministic markdown-defect fixes (Bugs 1, 2, 3, 5).

    Order matters: relocate dangling link punctuation before stripping footnotes
    (so a footnote adjacent to a link can't be mistaken for the link's punct),
    then heal list-marker leaks, then unwrap admonitions, then collapse spacing.
    """
    md = _fix_dangling_links(md)
    md = _strip_footnotes(md)
    md = _heal_list_leaks(md)
    md = _unwrap_admonitions(md)
    # Tidy spacing left by the strips: collapse runs of spaces and stray space
    # before sentence punctuation introduced by removing an inline superscript.
    md = re.sub(r"[ \t]{2,}", " ", md)
    md = re.sub(r"[ \t]+([.,;:!?])", r"\1", md)
    md = "\n".join(line.rstrip() for line in md.split("\n"))
    return md


def _collapse(md: str) -> str:
    md = "\n".join(line.rstrip() for line in md.splitlines())
    while "\n\n\n" in md:
        md = md.replace("\n\n\n", "\n\n")
    return md.strip()


def distill(html: str, url: str = "", max_chars: int = 12_000, offset: int = 0) -> str:
    """Rendered HTML → clean markdown.

    Args:
        html: outerHTML of the page (ideally post-render). Relative links are
              resolved against ``url`` (or the page's ``<base href>``).
        url:  page URL — the base for relative links; also helps trafilatura
              classify content.
        max_chars: the most markdown one call returns. A longer page comes in
              parts, each ending in a marker that names the next part's offset.
        offset: where in the page's markdown this part starts (0 = the top).
    """
    md, _ = _distill(html, url, max_chars, offset)
    return md


# Parts of a long page end on a line, or failing that a space, that is outside
# every link and fenced code block, so no part splits a URL or a code sample.
_MD_LINK = re.compile(r"!?\[[^\]\n]*\]\([^)\n]*\)")
_FENCE_LINE = re.compile(r"^[ \t]{0,3}(?:```|~~~)")


def _unsplittable(md: str) -> list[tuple[int, int]]:
    """Spans of ``md`` a part must not end inside: links and fenced code blocks."""
    spans = [m.span() for m in _MD_LINK.finditer(md)]
    pos, fence_at = 0, None
    for line in md.splitlines(keepends=True):
        if _FENCE_LINE.match(line):
            if fence_at is None:
                fence_at = pos
            else:
                spans.append((fence_at, pos + len(line)))
                fence_at = None
        pos += len(line)
    if fence_at is not None:
        spans.append((fence_at, len(md)))
    return spans


def _part_end(md: str, start: int, max_chars: int) -> int:
    """Where the part beginning at ``start`` ends: at most ``max_chars`` later.

    A part ends just before a paragraph break, else a line break, else a space,
    so it ends on text and the next part begins with the break.
    """
    limit = start + max_chars
    if limit >= len(md):
        return len(md)
    spans = [s for s in _unsplittable(md) if s[1] > start and s[0] < limit]

    def safe(b: int) -> bool:
        return not any(s < b < e for s, e in spans)

    floor = start + max_chars // 2  # never trade more than half a part for a nicer cut
    for wanted in ("\n\n", "\n", " "):
        for b in range(limit, floor, -1):
            if md.startswith(wanted, b) and safe(b):
                return b
    return limit  # one link or code block longer than half a part: cut it


def _distill(html: str, url: str = "", max_chars: int = 12_000,
             offset: int = 0) -> tuple[str, dict]:
    """:func:`distill` plus structured metadata for the event log.

    Returns ``(markdown, meta)`` where ``meta`` records which extractor path won
    (``trafilatura`` | ``fallback`` | ``failed``), the input/output sizes, the
    compression ratio, whether the output was truncated, the page's whole
    markdown length, and where the next part starts (``None`` after the last).
    """
    if offset < 0:
        raise ValueError(f"offset must be 0 or more, not {offset}")
    meta: dict = {
        "extractor": None,
        "in_chars": len(html),
        "out_chars": 0,
        "ratio": 0.0,
        "truncated": False,
        "offset": offset,
        "total_chars": None,
        "next_offset": None,
    }

    # Raw-HTML repairs (Bugs 2, 4, 6) before extraction so both paths benefit.
    try:
        prepared = _prepare_html(html, url)
    except Exception:  # noqa: BLE001 — never let preprocessing break extraction
        prepared = html

    md: str | None = None
    try:
        import trafilatura

        md = trafilatura.extract(
            prepared, url=url or None, output_format="markdown",
            include_links=True, include_formatting=True, favor_recall=True,
        )
        if md and len(md.strip()) >= 40:
            meta["extractor"] = "trafilatura"
    except Exception:  # noqa: BLE001 — trafilatura is best-effort
        md = None

    if not md or len(md.strip()) < 40:
        try:
            md = _fallback_markdown(html, url)  # repairs its own parse of the page
            meta["extractor"] = "fallback"
        except Exception as e:  # noqa: BLE001
            md = f"(distillation failed: {e})"
            meta["extractor"] = "failed"

    md = _clean_markdown(md or "")
    md = _collapse(md)
    total = meta["total_chars"] = len(md)
    if offset >= total > 0:
        md = f"…[offset {offset} is past the end of this page's {total} chars]"
    elif offset or total > max_chars:
        end = _part_end(md, offset, max_chars)
        md = md[offset:end]
        if end < total:
            # The marker keeps its old shape ("…[truncated at N chars" … "chars]"),
            # which servo-reader 0.4 and other readers already recognise.
            md += (f"\n\n…[truncated at {end - offset} chars; the next part starts at "
                   f"offset {end} of {total} chars]")
            meta["truncated"] = True
            meta["next_offset"] = end
    meta["out_chars"] = len(md)
    meta["ratio"] = round(meta["in_chars"] / len(md), 1) if md else 0.0
    return md, meta
