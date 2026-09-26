"""Many tab sources, one reconcile (I-64, 2026-09-25) — the multi-browser helpers.

`browser_tabs.live_deps` merges Chrome's CDP listing and the Firefox discovery
into ONE `TabListing` per pass. The reconciler stays source-blind and asks
this module three questions:
- Which keys count as live without being listed?
  - `held_rows`: rows of a browser that did not answer or answered empty, which
    are never aged — the old "an empty fetch never touches rows".
  - `held_pages`: pooled pages of a browser that did not answer, which stay
    connected. An empty answer still marks them stale, as before.
- Is an empty listing still an honest answer? (`answered`)
- What is the per-pass Firefox count line?

It also owns URL following: a linked, auto-added row takes its tab's new URL
while that URL still matches the pattern (typed rows keep what the user
typed). It also refreshes the Firefox pages' url/title. Pure over plain values,
plus the pool's external-lock pattern (`sync_pool_presence`); no Qt, no
`app.ui`, no `app.browser`.
"""

from __future__ import annotations

from typing import Any, Iterable, List

from app.core.tab_alias import CONN_UIVISION, FIREFOX, tab_browser
from app.services import auto_connect as ac


class TabListing(list):
    """One pass's merged tabs, plus the keys reconcile must hold and whether it answered."""

    def __init__(self, tabs: Iterable[Any] = (), held_rows: Iterable[str] = (),
                 held_pages: Iterable[str] = (), answered: bool = False):
        super().__init__(tabs)
        self.held_pages = frozenset(key for key in held_pages if key)
        self.held_rows = frozenset(key for key in held_rows if key) | self.held_pages
        self.answered = bool(answered)


def held_rows(tabs: Any) -> frozenset:
    """Row keys never aged this pass (a plain Chrome list holds none)."""
    return getattr(tabs, "held_rows", frozenset())


def held_pages(tabs: Any) -> frozenset:
    """Pooled keys kept connected this pass — their browser said nothing."""
    return getattr(tabs, "held_pages", frozenset())


def live_keys(tabs: Any) -> set:
    """Listed keys (pattern-independent) plus the held row keys."""
    return ac.live_tab_keys(tabs) | held_rows(tabs)


def answered(tabs: Any) -> bool:
    """Rows may follow this listing: it lists tabs, or a source answered with an honest empty list."""
    return bool(tabs) or bool(getattr(tabs, "answered", False))


def keys_of(keys: Iterable[str], browsers: Iterable[str]) -> set:
    """The non-empty keys that belong to one of `browsers` (by id shape)."""
    wanted = set(browsers)
    return {key for key in keys if key and tab_browser(key) in wanted}


def _key(tab: Any) -> str:
    return getattr(tab, "id", "") or getattr(tab, "ws_url", "") or ""


def _new_url(row: Any, by_key: dict, pattern: Any) -> str:
    """The URL a linked auto row should follow ('' = keep its own)."""
    if not row.tab_id or getattr(row, "typed", False):
        return ""
    url = getattr(by_key.get(row.tab_id), "url", "") or ""
    return url if url != row.url and ac.matches_pattern(url, pattern) else ""


def follow_urls(rows: List[Any], tabs: Any, pattern: Any) -> List[tuple]:
    """Linked auto rows take their tab's new URL while it matches; returns (old, new, tab) triples."""
    by_key = {_key(tab): tab for tab in tabs or []}
    moved = []
    for row in rows:
        url = _new_url(row, by_key, pattern)
        if url:
            moved.append((row.url, url, row.tab_id))
            row.url = url
    return moved


def follow_line(old: str, new: str, tab_id: str) -> str:
    return f"🔀 URL followed {old} → {new} (tab {tab_id}) — the tab navigated"


def refresh_firefox_pages(pool: Any, tabs: Any) -> int:
    """Pooled Firefox pages take their listed tab's url/title (the pool table shows them)."""
    by_key = {tab.id: tab for tab in tabs or [] if getattr(tab, "conn", "") == CONN_UIVISION}
    try:
        lock, pages = pool._lock, pool._pages
    except AttributeError:
        return 0
    changed = 0
    with lock:
        for tab_id, tab in by_key.items():
            page = pages.get(tab_id)
            if page is not None and (page.url, page.title) != (tab.url, tab.title):
                page.url, page.title = tab.url, tab.title
                changed += 1
    return changed


def firefox_ids(rows: Iterable[Any]) -> set:
    """Tab ids of the rows linked to Firefox tabs."""
    return keys_of((getattr(row, "tab_id", "") for row in rows or []), (FIREFOX,))


def firefox_line(before: set, after: set, manual: bool) -> str:
    """`🦊 Reconcile: +a firefox added, −r firefox removed, s firefox steady` ('' = nothing to say)."""
    added, removed = len(after - before), len(before - after)
    if not (before or after) or not (added or removed or manual):
        return ""
    return (f"🦊 Reconcile: +{added} firefox added, −{removed} firefox removed, "
            f"{len(after & before)} firefox steady")
