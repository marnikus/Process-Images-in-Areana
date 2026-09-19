# ideal-size: ~100 lines reason=one gate, one invariant ("every id JS asks
# for must exist"); the collector and the report are read as one unit (RULE 18.2)
"""DOM id contract gate — fail the build on a dead `getElementById`.

Background (docs/01 §2.1): the JS was refactored away from `index.html` and
14 ids were referenced by JS while missing from the markup — whole windows
went inert with no error. This gate makes that class of drift loud.

A referenced id is OK when it exists in **either**:
  1. `index.html` — the static markup (`id="..."`), or
  2. JavaScript — created on demand by the app itself (`el.id = "x"` or
     `id="x"` inside a string / template literal). Guarded
     `createElement`-and-assign code guarantees the element exists at the
     point it is read, so it is not drift.

Everything else is a dead id and fails the build.

Usage:
    python tools/check_dom_ids.py            # report, exit 1 on any dead id
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "app" / "ui" / "web"
HTML = WEB / "index.html"
JS_DIR = WEB / "js"

# getElementById("literal") / getElementById('literal')
GET_BY_ID = re.compile(r"getElementById\(\s*['\"]([A-Za-z0-9_-]+)['\"]\s*\)")
# ids assigned in JS:  el.id = 'x'  /  el.id = "x"
JS_ID_ASSIGN = re.compile(r"\.id\s*=\s*['\"]([A-Za-z0-9_-]+)['\"]")
# ids created in markup strings inside JS:  id="x" / id='x'
JS_ID_IN_MARKUP = re.compile(r"id=['\"]([A-Za-z0-9_-]+)['\"]")
# static markup ids
HTML_ID = re.compile(r"id=\"([^\"]+)\"")


def html_ids() -> set[str]:
    return set(HTML_ID.findall(HTML.read_text(encoding="utf-8", errors="ignore")))


def js_created_ids() -> set[str]:
    created: set[str] = set()
    for path in JS_DIR.rglob("*.js"):
        src = path.read_text(encoding="utf-8", errors="ignore")
        created |= set(JS_ID_ASSIGN.findall(src))
        created |= set(JS_ID_IN_MARKUP.findall(src))
    return created


def find_dead_ids() -> dict[str, list[str]]:
    """dead id -> list of referencing files (static refs only)."""
    known = html_ids() | js_created_ids()
    dead: dict[str, list[str]] = {}
    for path in JS_DIR.rglob("*.js"):
        src = path.read_text(encoding="utf-8", errors="ignore")
        for name in GET_BY_ID.findall(src):
            if name not in known:
                dead.setdefault(name, [])
                if str(path) not in dead[name]:
                    dead[name].append(str(path))
    return dead


def main() -> int:
    dead = find_dead_ids()
    created = js_created_ids()
    for name, files in sorted(dead.items()):
        print(f"MISSING #{name} <- {', '.join(Path(f).name for f in files)}")
    print(f"dom ids: {len(html_ids())} in index.html, "
          f"{len(created)} created by JS, {len(dead)} dead")
    if dead:
        print("FAIL — every getElementById id must exist in index.html "
              "or be created by JS")
        return 1
    print("OK — no dead DOM ids")
    return 0


if __name__ == "__main__":
    sys.exit(main())
