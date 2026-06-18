"""DOM → clean markdown distillation — the value-add of the harness.

Turns a rendered page's HTML into token-efficient markdown an agent can read:
trafilatura for article-shaped pages, a noise-stripping BeautifulSoup +
markdownify fallback for thin/utility pages. Pure functions, no engine
required, so this module is fully unit-testable offline.

Both extractors leave reproducible markdown defects on real pages (Wikipedia,
Docusaurus). Two deterministic cleanup passes harden the output:

* ``_recover_empty_anchors`` runs on the *raw HTML* before either extractor,
  so a table cell whose only content is a link (e.g. a Wikipedia infobox
  "Repository" row) keeps visible text instead of collapsing to an empty cell.
* ``_clean_markdown`` runs on the *produced markdown* to fix link/punctuation
  reordering, strip citation superscripts, heal mid-sentence list-marker leaks,
  and unwrap Docusaurus ``:::`` admonition fences.

Every transform is conservative — it targets a specific defect signature and is
covered by a focused unit test in ``tests/test_distill.py``.
"""
from __future__ import annotations

import re

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
# Bug 4 — table cell whose only content is a link renders empty.
# Fix at the source: an anchor with no visible text but a real href gets visible
# text derived from the href, *before* the HTML reaches trafilatura/markdownify.
# Applied on both paths, so it also fixes the trafilatura output (a black box we
# otherwise can't reach into). See tests: test_*recovers_link_only_*cell*.
# --------------------------------------------------------------------------- #
def _recover_empty_anchors(html: str) -> str:
    """Give empty ``<a href>`` anchors visible text from their href.

    Wikipedia infobox cells (and similar) often hold a single link whose text
    lives in a child that gets stripped, leaving ``<a href="…"></a>`` — which
    markdownify and trafilatura both render as an empty cell. We fill the anchor
    with a readable form of the href so the cell survives distillation.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    changed = False
    for a in soup.find_all("a"):
        if a.get_text(strip=True):
            continue  # already has visible text — leave it alone
        href = a.get("href") or ""
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue  # in-page / non-navigational — no useful text to recover
        a.string = re.sub(r"^[a-z][a-z0-9+.-]*://", "", href).rstrip("/")
        changed = True
    return str(soup) if changed else html


def _fallback_markdown(html: str) -> str:
    """Body-level HTML → markdown with nav-chrome / cookie-banner noise removed."""
    from bs4 import BeautifulSoup
    from markdownify import markdownify as mdify

    html = _recover_empty_anchors(html)
    soup = BeautifulSoup(html, "html.parser")
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


def distill(html: str, url: str = "", max_chars: int = 12_000) -> str:
    """Rendered HTML → clean markdown.

    Args:
        html: outerHTML of the page (ideally post-render, links absolutized).
        url:  page URL — helps trafilatura resolve and classify content.
        max_chars: hard cap; output is truncated with a marker beyond it.
    """
    # Recover link-only cells (Bug 4) before extraction so both paths benefit.
    try:
        prepared = _recover_empty_anchors(html)
    except Exception:  # noqa: BLE001 — never let preprocessing break extraction
        prepared = html

    md: str | None = None
    try:
        import trafilatura

        md = trafilatura.extract(
            prepared, url=url or None, output_format="markdown",
            include_links=True, include_formatting=True, favor_recall=True,
        )
    except Exception:  # noqa: BLE001 — trafilatura is best-effort
        md = None

    if not md or len(md.strip()) < 40:
        try:
            md = _fallback_markdown(html)  # fallback re-recovers anchors itself
        except Exception as e:  # noqa: BLE001
            md = f"(distillation failed: {e})"

    md = _clean_markdown(md or "")
    md = _collapse(md)
    if len(md) > max_chars:
        md = md[:max_chars] + f"\n\n…[truncated at {max_chars} chars]"
    return md
