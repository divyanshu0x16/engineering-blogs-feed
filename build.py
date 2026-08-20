"""
Build the static feed page.

    python build.py              fetch fresh posts, then render index.html
    python build.py --no-fetch   render from the existing data/posts.json
    python build.py --serve      build, then serve on http://localhost:8000

The renderer is deliberately trivial: template.html contains a single
__DATA__ placeholder which is replaced with the JSON payload. There is no
template engine to learn, and the template stays a valid standalone file you
can open and style directly.
"""

from __future__ import annotations

import argparse
import http.server
import json
import socketserver
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "template.html"
DATA = ROOT / "data" / "posts.json"
OUTPUT = ROOT / "index.html"
PORT = 8000


def run_fetch() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "fetch.py")], cwd=ROOT
    )
    if result.returncode != 0:
        print("\nFetch failed and there was no cached data to fall back on.")
        raise SystemExit(result.returncode)


def render() -> None:
    if not DATA.exists():
        raise SystemExit(
            "data/posts.json not found — run `python build.py` without "
            "--no-fetch at least once."
        )

    payload = json.loads(DATA.read_text())
    template = TEMPLATE.read_text()

    if "__DATA__" not in template:
        raise SystemExit("template.html is missing the __DATA__ placeholder.")

    # ensure_ascii=False keeps the output readable; </script> inside a string
    # would break the page, so escape the sequence defensively.
    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    OUTPUT.write_text(template.replace("__DATA__", blob))

    n = len(payload["posts"])
    print(f"Rendered {n} posts to {OUTPUT.relative_to(ROOT)}")


def serve() -> None:
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", PORT), handler) as httpd:
        print(f"\nServing at http://localhost:{PORT}/index.html  (Ctrl-C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-fetch", action="store_true", help="skip fetching; render cached data"
    )
    parser.add_argument(
        "--serve", action="store_true", help="serve the result on localhost"
    )
    args = parser.parse_args()

    if not args.no_fetch:
        run_fetch()
    render()

    if args.serve:
        import os

        os.chdir(ROOT)
        serve()


if __name__ == "__main__":
    main()
