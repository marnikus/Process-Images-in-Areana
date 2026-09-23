"""Ui.Vision autorun URL + macro pre-flight — pure helpers, no Qt, no browser I/O.

Why this file exists (2026-09-23, "Can't find macro with name Python_XClick_Demo"):
the Ui.Vision command line is actually a URL, so every value that can hold a
space (the autorun page path, the savelog path) must be %-encoded, and only the
documented query keys reach the extension. Sources:

* macro names with spaces need %20 (ulrich): forum.ui.vision/t/5481
* autorun params macro/folder/storage/savelog/closeRPA/closeBrowser/direct/cmd_varN:
  https://ui.vision/rpa/docs/ (Command Line API)
* tab reuse is `selectWindow | title=*...*` INSIDE the macro — no `tab=` URL
  parameter exists: https://ui.vision/rpa/docs/selenium-ide/selectwindow
* hard-drive mode reads <Home>/macros, and the Home + storage mode are stored
  per browser profile: https://ui.vision/rpa/x

Owns: URL building, macro-file lookup + status, window-title matching.
Imports stdlib only; stays leaf-ward inside `browser/` (RULE 18).
"""

import html
import json
import os
from pathlib import Path
from urllib.parse import quote, urlencode

#: Query keys the autorun page understands; `cmd_var<N>` handled by prefix.
_KNOWN_QUERY_KEYS = frozenset({
    "macro", "folder", "storage", "savelog", "direct",
    "closeRPA", "closeBrowser", "close", "testsuite",
})


def page_file_url(page_path: str) -> str:
    """Absolute path -> file:/// URL with %20-style encoding (works on any OS)."""
    normalized = (page_path or "").strip().replace("\\", "/")
    if normalized.startswith("//"):  # UNC \\server\share
        return "file:" + quote(normalized, safe="/:")
    if len(normalized) > 1 and normalized[1] == ":":
        return "file:///" + quote(normalized, safe="/:")
    return "file://" + quote(normalized, safe="/:")


def autorun_query(macro: str, savelog: str = "", storage: str = "xfile") -> dict:
    """The documented query dict for one macro run (starts immediately)."""
    query = {"macro": (macro or "").strip(), "storage": storage, "direct": "1"}
    if (savelog or "").strip():
        query["savelog"] = savelog.strip()
    return query


def build_autorun_url(page_path: str, query: dict) -> str:
    """Autorun page + %-encoded query (spaces -> %20, never +, never raw)."""
    return page_file_url(page_path) + "?" + urlencode(query, quote_via=quote)


def unknown_query_keys(query: dict) -> list:
    """Keys the extension silently ignores (e.g. tab=) — warn, don't send."""
    return [k for k in query if k not in _KNOWN_QUERY_KEYS and not k.startswith("cmd_var")]


def macro_file(home: str, macro: str) -> str:
    """Where hard-drive mode looks: <home>/macros/<macro>.json (a/b -> subdir)."""
    name = (macro or "").strip().replace("\\", "/")
    if name.lower().endswith(".json"):
        name = name[:-5]
    return os.path.join((home or "").strip(), "macros", *name.split("/")) + ".json"


def macro_status(home: str, macro: str) -> str:
    """Pre-flight the on-disk macro: ok | missing | invalid (RULE 4)."""
    try:
        text = Path(macro_file(home, macro)).read_text(encoding="utf-8")
    except OSError:
        return "missing"
    try:
        data = json.loads(text)
    except ValueError:
        return "invalid"
    if not isinstance(data, dict) or not isinstance(data.get("Commands"), list):
        return "invalid"
    return "ok"


def window_title_matches(pattern: str, title: str) -> bool:
    """Substring, case-insensitive, entity-decoded: tabs match => windows match."""
    needle = html.unescape(pattern or "").casefold().strip()
    haystack = html.unescape(title or "").casefold()
    return bool(needle) and needle in haystack


def select_window_command(pattern: str) -> dict:
    """First macro command that reuses the matching tab (no tab= URL param exists)."""
    return {"Command": "selectWindow", "Target": f"title=*{(pattern or '').strip()}*", "Value": ""}
