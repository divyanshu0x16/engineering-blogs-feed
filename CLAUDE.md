# CLAUDE.md

Context for Claude Code working in this repo.

## What this is

A static aggregator for company engineering blogs. It fetches RSS feeds (and
scrapes the one blog that has none), writes a combined `data/posts.json`, and
renders that into a single self-contained `index.html`. GitHub Actions rebuilds
it daily and publishes to GitHub Pages.

No framework, no build toolchain, no database. That is deliberate — the whole
thing should stay readable in one sitting.

## Architecture

```
sources.yaml          the list of blogs — the main thing you edit
scripts/fetch.py      fetches every source → data/posts.json
scripts/scrapers.py   custom scrapers for blogs with no RSS feed
scripts/extract.py    best-effort full-article extraction for reading mode
build.py              renders data/posts.json + template.html → index.html
template.html         the page: HTML, CSS and JS, with one __DATA__ placeholder
data/posts.json       committed fetch output; also the offline fallback
index.html            build artifact, committed so Pages can serve it
```

Data flows one way: `sources.yaml` → `fetch.py` → `posts.json` → `build.py` →
`index.html`. Fetching and rendering are separate commands on purpose, so you
can iterate on the design without re-hitting the network every time.

## Commands

```bash
pip install -r requirements.txt

python build.py                # fetch + render
python build.py --no-fetch     # render only — use this while restyling
python build.py --serve        # build, then serve on localhost:8000
python scripts/fetch.py        # fetch only
```

## Conventions that matter

**A post object is always this shape.** Both RSS parsing and custom scrapers
must produce it, and the template reads exactly these keys:

```json
{ "source": "uber", "title": "...", "url": "https://...",
  "date": "2026-08-19", "summary": "...", "content": "<p>...</p>" }
```

`date` is always `YYYY-MM-DD` — this is what sorting and month-grouping rely
on. A post missing `title`, `url`, or `date` is dropped during fetch.

`content` is a sanitized HTML fragment (a fixed allowlist of typographic
tags, no images or scripts) used for in-page reading mode — see
`scripts/extract.py`. It's populated separately from the RSS/scrape pass and
cached by URL in `posts.json`, so a normal fetch run only extracts genuinely
new posts. It's "" when extraction failed or hasn't run yet for that post,
and the card falls back to linking straight to the source.

**Failures are per-source and non-fatal.** If one blog is unreachable, its
previously fetched posts are carried over from the existing `posts.json`, the
error is recorded in `payload["errors"]`, and the build still succeeds. The
page shows a small `!` badge on that source's chip. Only a total wipeout
(zero posts from every source) exits non-zero. Preserve this behaviour — a
single dead feed should never break the site.

**`template.html` stays a valid standalone file.** The only magic is the
`__DATA__` placeholder, which `build.py` replaces with a JSON blob. Don't
introduce a template engine; if you need more logic, put it in the page's own
JavaScript, which already has the full dataset in `DATA`.

**No external requests from `index.html`, with one opt-in exception.** All
CSS and JS are inline; the page must work offline and from a `file://` URL by
default. Don't add CDN links, web fonts, or analytics. This is also why
reading-mode content has no `<img>` tags — `extract.py` strips images during
sanitization rather than embedding remote `src` URLs that would try to load
at view time. The one deliberate exception is read-state sync (below): it
only fires once a user pastes a GitHub token, and the page works fully
offline without one.

**Read/unread state, synced via a private GitHub gist.** Read-state (a set
of post URLs) lives in `localStorage` under `ebf_read_state_v1`, always
local-first. If the user connects sync (`ebf_sync_v1` holds `{token,
gistId}`), the page finds-or-creates a private gist named
`engineering-blogs-feed-state.json` under their account and merges/pushes
that same set to it, so a second device just needs the same token pasted
in — no gist ID to copy around. This is the one place the page talks to a
network API from the browser; it requires a classic PAT with only the
`gist` scope, entered via a `prompt()` and never sent anywhere but
`api.github.com`. Keep this feature's failure modes non-fatal, same spirit
as source fetch errors — a sync error shouldn't block reading or marking
posts locally.

## Adding a blog

Append an entry to `sources.yaml` and run `python build.py`. That's the whole
process for anything with an RSS feed. Several verified extras (Cloudflare,
GitHub, Dropbox, Discord, Pinterest, DoorDash) are commented out at the bottom
of that file, ready to uncomment.

To find a feed: view source on the blog's homepage and look for
`<link rel="alternate" type="application/rss+xml">`. Failing that try `/feed`,
`/rss`, `/feed.xml`, `/atom.xml`. Medium publications are always
`https://medium.com/feed/<publication>`.

If a blog genuinely has no feed, set `type: scrape` and register a function in
`scripts/scrapers.py` under `SCRAPERS[<id>]`. Scrapers must raise on finding
zero posts rather than returning an empty list, so breakage is loud.

## Known rough edges

These are real and worth fixing — treat them as the natural first tasks:

- **Uber is scraped, not fed.** `scrape_uber()` parses the blog index page and
  will break whenever Uber redesigns it. It's the most fragile part of the repo.
- **Swiggy is dormant.** The Medium publication has published nothing since
  mid-2024, and most of what's there is career profiles rather than
  engineering. `bytes.swiggy.com` blocks automated fetches. Consider dropping it.
- **Stripe has no engineering-only feed**, so `stripe.com/blog/feed.rss` mixes
  in product and business posts. Filtering by keyword would help.
- **Summaries vary in quality.** Medium feeds embed full post HTML, so the
  truncated summary is often just the opening line. Some feeds have none at all.
- **No deduplication.** A post syndicated to two feeds would appear twice.
- **No pagination.** Every post renders at once; fine at ~50, less so at 500.

## Ideas worth building

Roughly in order of value-per-effort:

- Bookmarks/starring, alongside the read/unread state that already exists
- Keyword filters per source (would fix the Stripe noise problem)
- Full-text search across fetched post bodies, not just titles and summaries
  — the data (`content`) is already there from reading-mode extraction
- Tag inference from titles (ML, infra, databases, frontend) for cross-cutting
  filters
- An RSS/Atom feed *output*, so the aggregator can be read in a real feed reader
- Email or Slack digest on a weekly schedule
