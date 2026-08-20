"""
Fetch every configured engineering blog and write the combined result to
data/posts.json.

Run directly:      python scripts/fetch.py
Or via the build:  python build.py          (calls this automatically)

Design notes
------------
* Fetching and rendering are deliberately separate steps. data/posts.json is
  committed to the repo, so the site can always be rebuilt without network
  access, and a failed fetch never destroys a good build.
* A source that fails is reported but does not abort the run — its previously
  fetched posts are retained from the existing posts.json.
"""

from __future__ import annotations

import concurrent.futures
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from scrapers import SCRAPERS  # noqa: E402
from extract import extract_article  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SOURCES_FILE = ROOT / "sources.yaml"
OUT_FILE = ROOT / "data" / "posts.json"

# Posts per source kept in the final feed. Raise for a denser page.
MAX_PER_SOURCE = 15
# Summary length before truncation, in characters.
SUMMARY_CHARS = 220

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def clean_summary(raw: str) -> str:
    """Strip HTML tags and entities out of a feed summary, then truncate."""
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    # Medium feeds often begin with a boilerplate byline; drop obvious noise.
    text = re.sub(r"^(Continue reading on .+?»\s*)", "", text)
    if len(text) > SUMMARY_CHARS:
        text = text[:SUMMARY_CHARS].rsplit(" ", 1)[0].rstrip(".,;:") + "…"
    return text


def entry_date(entry) -> str:
    """Best-effort ISO date (YYYY-MM-DD) from a feedparser entry."""
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = getattr(entry, key, None)
        if parsed:
            return datetime(*parsed[:6]).strftime("%Y-%m-%d")
    return ""


def fetch_rss(source: dict) -> list[dict]:
    parsed = feedparser.parse(
        source["feed"], agent=UA, request_headers={"Accept": "application/rss+xml, application/xml"}
    )

    # feedparser sets .bozo on malformed XML, but often still parses usable
    # entries — so only treat it as fatal when nothing came back.
    if not parsed.entries:
        reason = getattr(parsed, "bozo_exception", None) or "no entries returned"
        raise RuntimeError(f"{source['feed']}: {reason}")

    posts = []
    for e in parsed.entries:
        link = getattr(e, "link", "")
        # Medium appends tracking params to every link; strip them.
        link = re.sub(r"\?source=rss[-\w]*$", "", link)
        posts.append(
            {
                "title": html.unescape(getattr(e, "title", "").strip()),
                "url": link,
                "date": entry_date(e),
                "summary": clean_summary(
                    getattr(e, "summary", "") or getattr(e, "description", "")
                ),
            }
        )
    return posts


def fetch_source(source: dict) -> tuple[str, list[dict], str | None]:
    """Returns (source_id, posts, error_message)."""
    sid = source["id"]
    try:
        if source.get("type") == "scrape":
            scraper = SCRAPERS.get(sid)
            if scraper is None:
                raise RuntimeError(f"no scraper registered for '{sid}'")
            posts = scraper(source)
        else:
            posts = fetch_rss(source)

        # Drop entries missing the essentials, sort, trim.
        posts = [p for p in posts if p["title"] and p["url"] and p["date"]]
        posts.sort(key=lambda p: p["date"], reverse=True)
        posts = posts[:MAX_PER_SOURCE]

        for p in posts:
            p["source"] = sid
        return sid, posts, None

    except Exception as exc:  # noqa: BLE001 - we want to report, not crash
        return sid, [], f"{type(exc).__name__}: {exc}"


def main() -> int:
    config = yaml.safe_load(SOURCES_FILE.read_text())
    sources = config["sources"]

    previous: dict[str, list[dict]] = {}
    if OUT_FILE.exists():
        old = json.loads(OUT_FILE.read_text())
        for post in old.get("posts", []):
            previous.setdefault(post["source"], []).append(post)

    print(f"Fetching {len(sources)} sources…\n")

    results: dict[str, list[dict]] = {}
    errors: dict[str, str] = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for sid, posts, err in pool.map(fetch_source, sources):
            if err:
                errors[sid] = err
                kept = previous.get(sid, [])
                results[sid] = kept
                print(f"  ✗ {sid:<9} {err}")
                if kept:
                    print(f"    ↳ keeping {len(kept)} previously fetched post(s)")
            else:
                results[sid] = posts
                newest = posts[0]["date"] if posts else "—"
                print(f"  ✓ {sid:<9} {len(posts):>2} posts   newest {newest}")

    # Reading-mode content is fetched separately from the RSS/scrape pass and
    # cached by URL, so a daily re-run only extracts genuinely new posts
    # instead of re-scraping every article every time.
    content_cache = {
        p["url"]: p["content"]
        for posts in previous.values()
        for p in posts
        if p.get("content")
    }
    to_extract = []
    for posts in results.values():
        for p in posts:
            if not p.get("content"):
                p["content"] = content_cache.get(p["url"], "")
            if not p["content"]:
                to_extract.append(p)

    if to_extract:
        print(f"\nExtracting article content for {len(to_extract)} new post(s)…")
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            contents = pool.map(lambda p: extract_article(p["url"]), to_extract)
            for post, content in zip(to_extract, contents):
                post["content"] = content

    all_posts = [p for sid in results for p in results[sid]]
    all_posts.sort(key=lambda p: p["date"], reverse=True)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": [
            {k: s[k] for k in ("id", "name", "color", "site") if k in s}
            for s in sources
        ],
        "errors": errors,
        "posts": all_posts,
    }

    OUT_FILE.parent.mkdir(exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    print(f"\nWrote {len(all_posts)} posts to {OUT_FILE.relative_to(ROOT)}")
    if errors:
        print(f"{len(errors)} source(s) failed: {', '.join(errors)}")

    # Only a total wipeout is a build failure; partial failures are tolerated.
    return 1 if not all_posts else 0


if __name__ == "__main__":
    raise SystemExit(main())
