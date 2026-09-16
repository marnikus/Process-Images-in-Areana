"""Auto-connect page detection — pure URL pattern matching + page selection.

Spec (AUTO-CONNECT & URL PARSING):
- 02 scan only the CDP host:port from settings, filter pages by URL string pattern
  (e.g. every page containing "arena.ai") — pattern is a storable setting;
- 02 the same URL can legitimately appear twice (same web, two tabs), so pages are
  identified by their unique CDP page id, never by URL alone;
- 03 every matching page is connected automatically — no manual "Add" step.

RULE 16/18: pure functions only, no I/O, no Qt, small and unit tested.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Sequence, Tuple

DEFAULT_PATTERN = "arena.ai"

_SCHEME_RE = re.compile(r"^https?://")
_WS_ID_RE = re.compile(r"/devtools/page/([^/?#]+)")


def normalize_url(url: str) -> str:
    """Lowercase, drop scheme/fragment/trailing slashes — comparison form."""
    u = (url or "").strip().lower()
    if not u:
        return ""
    u = _SCHEME_RE.sub("", u)
    u = u.split("#", 1)[0]
    return u.rstrip("/")


def split_patterns(raw: str) -> List[str]:
    """Split a user pattern field on comma / semicolon / newline."""
    parts = re.split(r"[,;\n]+", raw or "")
    return [p.strip() for p in parts if p.strip()]


def _expand_tokens(pattern: str) -> List[str]:
    """Split "arena.ai lmarena.ai" and "arena.ai|lmarena.ai" into single tokens."""
    tokens: List[str] = []
    for chunk in pattern.split("|"):
        tokens.extend(chunk.split())
    return tokens


def compile_patterns(raw: str) -> List[str]:
    """Normalized, de-duplicated pattern list ready for :func:`url_matches`."""
    out: List[str] = []
    for pattern in split_patterns(raw):
        cleaned = normalize_url(pattern) or pattern.strip().lower()
        for token in _expand_tokens(cleaned):
            if token and token not in out:
                out.append(token)
    return out


def _match_token(token: str, url: str, title: str) -> bool:
    needle = token.lower()
    url_l = (url or "").lower()
    bare = normalize_url(url_l)
    if any(needle in hay for hay in (url_l, bare, (title or "").lower())):
        return True
    return bool(("*" in needle or "?" in needle) and fnmatch.fnmatch(bare, needle))


def url_matches(url: str, patterns: Sequence[str], title: str = "") -> bool:
    """True when *url* satisfies at least one pattern (substring or wildcard)."""
    if not url:
        return False
    return any(_match_token(p, url, title) for p in patterns or ())


def page_id_from_ws(ws_url: str) -> str:
    """Page id embedded in ``ws://host:port/devtools/page/<id>``."""
    m = _WS_ID_RE.search(ws_url or "")
    return m.group(1) if m else (ws_url or "").strip()


def page_id(tab: Any) -> str:
    """Unique CDP page id — dedupe key, because URLs may repeat."""
    if isinstance(tab, dict):
        tid = str(tab.get("id") or "").strip()
        ws = str(tab.get("ws_url") or tab.get("webSocketDebuggerUrl") or "")
    else:
        tid = str(getattr(tab, "id", "") or "").strip()
        ws = str(getattr(tab, "ws_url", "") or "")
    if tid:
        return tid
    return page_id_from_ws(ws)


def tab_fields(tab: Any) -> Tuple[str, str, str, str]:
    """(page_id, title, url, ws_url) from a dict or TabInfo-like object."""
    if isinstance(tab, dict):
        get = lambda k: str(tab.get(k) or "")  # noqa: E731 — 3-key dict read
        url = get("url")
        ws = get("ws_url") or get("webSocketDebuggerUrl")
        title = get("title")
    else:
        url = str(getattr(tab, "url", "") or "")
        ws = str(getattr(tab, "ws_url", "") or "")
        title = str(getattr(tab, "title", "") or "")
    return page_id(tab), title, url, ws


def _tab_entry(tab: Any) -> Dict[str, Any]:
    pid, title, url, ws = tab_fields(tab)
    return {"page_id": pid, "title": title, "url": url, "ws_url": ws}


def _is_internal(tab: Dict[str, Any]) -> bool:
    try:
        from .cdp_protocol import is_devtools_url

        return bool(is_devtools_url(tab.get("url", ""), tab.get("title", "")))
    except Exception:
        return not (tab.get("url") or "")


@dataclass
class Selection:
    """Result of one detection pass — RULE 4: empty is reported apart from broken."""

    pages: List[Dict[str, Any]] = field(default_factory=list)
    scanned: int = 0
    matched: int = 0
    duplicates: int = 0
    skipped_internal: int = 0
    skipped_pattern: int = 0
    limited: bool = False
    patterns: List[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pages": list(self.pages),
            "scanned": self.scanned,
            "matched": self.matched,
            "duplicates": self.duplicates,
            "skipped_internal": self.skipped_internal,
            "skipped_pattern": self.skipped_pattern,
            "limited": self.limited,
            "patterns": list(self.patterns),
            "error": self.error,
        }


def _classify(entry: Dict[str, Any], pats: Sequence[str], seen: set) -> str:
    """Why one scanned page is in or out — one decision, named outcomes."""
    pid = entry["page_id"]
    if not pid:
        return "no_id"
    if pid in seen:
        return "duplicate"
    if _is_internal(entry):
        return "internal"
    if not url_matches(entry["url"], pats, entry["title"]):
        return "pattern"
    return "match"


_TALLY_FIELD = {
    "duplicate": "duplicates",
    "internal": "skipped_internal",
    "pattern": "skipped_pattern",
}


def _tally(sel: "Selection", verdict: str) -> bool:
    """Count a skip reason; True when the page must not be linked."""
    field = _TALLY_FIELD.get(verdict)
    if not field:
        return verdict != "match"
    setattr(sel, field, getattr(sel, field) + 1)
    return True


def _apply_limit(sel: "Selection", max_pages: int) -> None:
    if max_pages and max_pages > 0 and len(sel.pages) > max_pages:
        sel.pages = sel.pages[:max_pages]
        sel.limited = True


def select_pages(
    tabs: Iterable[Any], patterns: Sequence[str], max_pages: int = 0
) -> Selection:
    """Pick the pages to auto-connect.

    * keep every page whose URL matches — two tabs on the same URL are two pages;
    * collapse repeated *page ids* (same target listed twice by Chrome);
    * never return devtools/chrome:// internals;
    * ``max_pages`` <= 0 means unlimited.
    """
    pats = list(patterns or [])
    sel = Selection(patterns=pats)
    seen: set = set()
    for raw in tabs or []:
        entry = _tab_entry(raw)
        sel.scanned += 1
        if _tally(sel, _classify(entry, pats, seen)):
            continue
        seen.add(entry["page_id"])
        sel.pages.append(entry)
    sel.matched = len(sel.pages)
    _apply_limit(sel, max_pages)
    return sel
