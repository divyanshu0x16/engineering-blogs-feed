"""
Best-effort full-article extraction, for in-page reading mode.

Given a post URL, fetch the page and pull out the article body as a small,
sanitized HTML fragment safe to render via innerHTML client-side. Returns ""
on any failure — reading mode falls back to "Read on site" in that case, this
never raises and never fails a fetch run.

Deliberately conservative about what survives sanitization: only a fixed set
of typographic tags, no images, no scripts, no inline styles or event
handlers. The content came from someone else's page and gets embedded
directly into ours, so treat it as untrusted markup, not as trusted HTML.
"""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup, NavigableString

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
TIMEOUT = 15
MAX_CHARS = 20_000
MIN_CHARS = 200

STRIP_TAGS = [
    "script", "style", "nav", "header", "footer", "aside", "form",
    "iframe", "noscript", "svg", "button", "input", "select", "textarea",
    "figure", "figcaption", "img", "picture", "video", "audio",
    # h1 inside an article body is almost always the headline itself,
    # which the page already renders separately from post metadata —
    # keeping it here would duplicate the title above the body text.
    "h1",
]
ALLOWED_TAGS = {
    "p", "br", "strong", "em", "b", "i", "u", "a", "ul", "ol", "li",
    "blockquote", "h2", "h3", "h4", "h5", "h6", "pre", "code", "hr",
}
ARTICLE_SELECTORS = [
    "article",
    "[role=main]",
    "main",
    ".post-content", ".article-content", ".entry-content",
    "#content",
]


def _find_article_root(soup: BeautifulSoup):
    for sel in ARTICLE_SELECTORS:
        node = soup.select_one(sel)
        if node and len(node.get_text(strip=True)) >= MIN_CHARS:
            return node

    # Fall back to the <div>/<section> with the most paragraph text — a
    # crude but effective readability heuristic for pages with no semantic
    # article markup.
    candidates = soup.find_all(["div", "section"])
    best, best_len = None, 0
    for c in candidates:
        length = sum(len(p.get_text()) for p in c.find_all("p", recursive=False))
        if length > best_len:
            best, best_len = c, length
    if best is not None and best_len >= MIN_CHARS:
        return best
    return None


def _sanitize(root) -> str:
    for tag in root.find_all(STRIP_TAGS):
        tag.decompose()

    for tag in root.find_all(True):
        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()
            continue
        if tag.name == "a":
            href = tag.get("href", "")
            if not href.startswith(("http://", "https://")):
                tag.unwrap()
                continue
            tag.attrs = {"href": href, "target": "_blank", "rel": "noopener noreferrer"}
        else:
            tag.attrs = {}

    # Drop now-empty leaf nodes left behind by unwrapping/stripping.
    for tag in root.find_all(["p", "li", "blockquote"]):
        if not tag.get_text(strip=True):
            tag.decompose()

    html = "".join(str(c) for c in root.contents if not isinstance(c, NavigableString) or c.strip())
    html = re.sub(r"\s+\n", "\n", html).strip()
    return html


def extract_article(url: str) -> str:
    """Best-effort article body as a sanitized HTML fragment, or "" on failure."""
    try:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        root = _find_article_root(soup)
        if root is None:
            return ""

        content = _sanitize(root)
        if len(re.sub(r"<[^>]+>", "", content)) < MIN_CHARS:
            return ""

        if len(content) > MAX_CHARS:
            content = content[:MAX_CHARS].rsplit(">", 1)[0] + ">"
        return content

    except Exception:  # noqa: BLE001 - extraction is best-effort, never fatal
        return ""
