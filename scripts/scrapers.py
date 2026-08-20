"""
Custom scrapers for blogs that don't publish a usable RSS feed.

Each scraper is registered in SCRAPERS under the source `id` used in
sources.yaml, and must return a list of dicts shaped like:

    {"title": str, "url": str, "date": "YYYY-MM-DD", "summary": str}

Scrapers are inherently fragile — a site redesign will break them. Each one
should fail loudly (raise) rather than silently returning nothing, so the
build surfaces the problem instead of quietly dropping a source.
"""

from __future__ import annotations

import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
TIMEOUT = 30


def _get(url: str) -> str:
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.text


def scrape_uber(source: dict) -> list[dict]:
    """
    Uber retired eng.uber.com and its RSS feed; posts now live under
    uber.com/blog/engineering/ as a client-rendered listing whose data is
    embedded in the page as JSON. We pull the article cards out of the
    server-rendered HTML.

    If this breaks, the fastest fix is usually to open the page, find the
    <script> tag containing post objects, and adjust the selector below.
    """
    html = _get("https://www.uber.com/en-IN/blog/engineering/")
    soup = BeautifulSoup(html, "html.parser")

    posts: list[dict] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/blog/" not in href:
            continue
        # Skip category/index links — real posts have a slug after /blog/
        if re.search(r"/blog/(engineering|category|tag)/?$", href):
            continue

        title = a.get_text(" ", strip=True)
        if not title or len(title) < 20:
            continue

        url = href if href.startswith("http") else "https://www.uber.com" + href
        if url in seen:
            continue
        seen.add(url)

        # Dates sit in a sibling/parent node; fall back to today if absent.
        date = ""
        parent = a.find_parent()
        if parent:
            m = re.search(
                r"(January|February|March|April|May|June|July|August|"
                r"September|October|November|December)\s+(\d{1,2}),\s+(\d{4})",
                parent.get_text(" ", strip=True),
            )
            if m:
                date = datetime.strptime(
                    f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y"
                ).strftime("%Y-%m-%d")

        posts.append(
            {
                "title": title,
                "url": url,
                "date": date or datetime.utcnow().strftime("%Y-%m-%d"),
                "summary": "",
            }
        )

    if not posts:
        raise RuntimeError(
            "Uber scraper found no posts — the page layout has probably "
            "changed. Inspect https://www.uber.com/en-IN/blog/engineering/ "
            "and update scrape_uber() in scripts/scrapers.py."
        )

    return posts


SCRAPERS = {
    "uber": scrape_uber,
}
