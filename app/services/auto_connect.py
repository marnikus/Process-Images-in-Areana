"""Auto-connect planning — match open Chrome tabs to URL rows by page ID.

Pure planner: (tabs, pattern, rows, pooled) -> add/claim/connect/stale.
Duplicate URLs are normal (same web in two tabs); identity is the CDP
target id, never the URL alone. Presence sync only flags pooled tabs
whose connection dropped — it never deletes, so a failed fetch can't
wipe the pool. Imports services -> browser only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.browser.cdp_protocol import is_devtools_url


@dataclass
class AutoConnectPlan:
    """One scan outcome: rows to add (url, tab_id) / claim (row_id, tab_id),
    tab sockets to join, pooled ids gone from Chrome."""

    add: list = field(default_factory=list)
    claim: list = field(default_factory=list)
    connect: list = field(default_factory=list)
    stale: list = field(default_factory=list)


def matches_pattern(url: Any, pattern: Any) -> bool:
    """Case-insensitive substring; blank pattern matches every URL."""
    if not isinstance(url, str) or not url:
        return False
    filt = pattern.strip().lower() if isinstance(pattern, str) else ""
    if not filt:
        return True
    return filt in url.lower()


def _tab_key(tab: Any) -> str:
    """Unique page identity: CDP target id, ws_url fallback."""
    tab_id = getattr(tab, "id", "") or ""
    if tab_id:
        return tab_id
    return getattr(tab, "ws_url", "") or ""


def _live_tabs(tabs: Any) -> list:
    """Real keyed tabs, deduped by page id (pattern-independent)."""
    live = []
    seen = set()
    for tab in tabs or []:
        key = _tab_key(tab)
        if not key or key in seen:
            continue
        seen.add(key)
        if is_devtools_url(getattr(tab, "url", ""), getattr(tab, "title", "")):
            continue
        live.append(tab)
    return live


def _row_index(rows: Any):
    """(by_tab, unlinked-by-url) lookup for one scan."""
    rows = rows or []
    by_tab = {r.get("tab_id"): r for r in rows if r.get("tab_id")}
    unlinked = {}
    for r in rows:
        if not r.get("tab_id"):
            unlinked.setdefault(r.get("url", ""), r)
    return by_tab, unlinked


def _row_action(rows_by_tab: dict, unlinked: dict, tab: Any, key: str):
    """Claim tuple, add tuple, or None when the tab is already linked."""
    if key in rows_by_tab:
        return None
    row = unlinked.pop(getattr(tab, "url", "") or "", None)
    if row is None:
        return ("add",)
    return ("claim", row.get("id", ""))


def _apply_row_action(plan: AutoConnectPlan, action, tab: Any, key: str) -> None:
    """Record a claim or add for one matched tab."""
    if action is None:
        return
    if action[0] == "claim":
        plan.claim.append((action[1], key))
    else:
        plan.add.append((getattr(tab, "url", ""), key))


def plan_auto_connect(tabs: Any, pattern: Any, rows: Any, pooled: Any) -> AutoConnectPlan:
    """Pure plan: rows to add/claim, sockets to join, ids gone stale."""
    pooled = set(pooled or [])
    rows_by_tab, unlinked = _row_index(rows)
    plan = AutoConnectPlan()
    live = set()
    for tab in _live_tabs(tabs):
        key = _tab_key(tab)
        live.add(key)
        if not matches_pattern(getattr(tab, "url", ""), pattern):
            continue
        _apply_row_action(plan, _row_action(rows_by_tab, unlinked, tab, key), tab, key)
        if key not in pooled:
            plan.connect.append(getattr(tab, "ws_url", "") or "")
    plan.stale = sorted(pooled - live)
    return plan


def sync_pool_presence(pool: Any, live_ids: Any) -> tuple[int, list]:
    """Flag pooled tabs gone from Chrome; revive returnees. Never deletes."""
    try:
        pages = pool._pages
        lock = pool._lock
    except AttributeError:
        return 0, []
    live = set(live_ids or [])
    revived = 0
    stale = []
    with lock:
        for tab_id, page in pages.items():
            if tab_id in live and not page.is_connected:
                page.is_connected = True
                revived += 1
            elif tab_id not in live and page.is_connected:
                page.is_connected = False
                stale.append(tab_id)
    return revived, sorted(stale)
