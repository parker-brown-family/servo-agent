"""DOM → clean markdown distillation — the value-add of the harness.

Turns a rendered page's HTML into token-efficient markdown an agent can read:
trafilatura for article-shaped pages, a noise-stripping BeautifulSoup +
markdownify fallback for thin/utility pages. Pure functions, no engine
required, so this module is fully unit-testable offline.
"""
from __future__ import annotations

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


def _fallback_markdown(html: str) -> str:
    """Body-level HTML → markdown with nav-chrome / cookie-banner noise removed."""
    from bs4 import BeautifulSoup
    from markdownify import markdownify as mdify

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
    md: str | None = None
    try:
        import trafilatura

        md = trafilatura.extract(
            html, url=url or None, output_format="markdown",
            include_links=True, include_formatting=True, favor_recall=True,
        )
    except Exception:  # noqa: BLE001 — trafilatura is best-effort
        md = None

    if not md or len(md.strip()) < 40:
        try:
            md = _fallback_markdown(html)
        except Exception as e:  # noqa: BLE001
            md = f"(distillation failed: {e})"

    md = _collapse(md or "")
    if len(md) > max_chars:
        md = md[:max_chars] + f"\n\n…[truncated at {max_chars} chars]"
    return md
