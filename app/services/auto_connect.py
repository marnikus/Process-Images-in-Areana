"""Auto-connect planning + URL-row tab ownership (one live tab ↔ one row).

Pure planner: (tabs, pattern, rows, pooled) -> add/claim/connect/stale.
Duplicate URLs are normal (same web in two tabs); identity is the CDP
target id, never the URL alone. Presence sync only flags pooled tabs
whose connection dropped — it never deletes, so a failed fetch can't
wipe the pool. The run-gating helpers (rows -> tabs direction) keep the
I-33 invariant: a tab runs jobs only when a checked row owns it, and
rows are never re-bound to foreign tabs. Imports services -> browser only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.browser.cdp_protocol import is_devtools_url
from app.browser.tab_matcher import score_tab

# Exact URL match only for run-start claims: anything weaker (host level)
# could bind a row to the wrong chat tab (RULE 4 — no silent redirects).
_CLAIM_MIN_SCORE = 500


@dataclass
class AutoConnectPlan:
    """One scan outcome: rows to add (url, tab_id) / claim (row_id, tab_id),
    tab sockets to join, pooled ids gone from Chrome, linked rows to drop."""

    add: list = field(default_factory=list)
    claim: list = field(default_factory=list)
    connect: list = field(default_factory=list)
    stale: list = field(default_factory=list)
    remove: list = field(default_factory=list)


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


def live_tab_keys(tabs: Any) -> set:
    """Keyed ids of real tabs in this fetch (pattern-independent)."""
    return {_tab_key(t) for t in _live_tabs(tabs)}


def pick_primary_ws(pages) -> str:
    """Socket of the first connected pooled tab, else ''."""
    for p in pages or []:
        ws = getattr(p, "ws_url", "") or ""
        if ws and getattr(p, "is_connected", False):
            return ws
    return ""


def prunable_row_ids(rows: Any, live_keys) -> list:
    """Ids of linked rows whose tabs vanished from the live keys."""
    live = live_keys or set()
    gone = []
    for r in rows or []:
        tid = r.get("tab_id", "")
        if tid and tid not in live:
            gone.append(r.get("id", ""))
    return gone


def _row_allows_rejoin(rows_by_tab: dict, key: str) -> bool:
    """A tab owned by an UNCHECKED row never auto-rejoins the pool (D-5, 2026-09-21).

    No row / legacy dict without the key counts as allowed (UrlRow.enabled's True default).
    """
    owner = rows_by_tab.get(key)
    return owner is None or bool(owner.get("enabled", True))


def plan_auto_connect(tabs: Any, pattern: Any, rows: Any, pooled: Any) -> AutoConnectPlan:
    """Pure plan: rows to add/claim, sockets to join, ids gone stale."""
    pooled = set(pooled or [])
    rows_by_tab, unlinked = _row_index(rows)
    plan = AutoConnectPlan()
    live = live_tab_keys(tabs)
    for tab in _live_tabs(tabs):
        key = _tab_key(tab)
        if not matches_pattern(getattr(tab, "url", ""), pattern):
            continue
        _apply_row_action(plan, _row_action(rows_by_tab, unlinked, tab, key), tab, key)
        if key not in pooled and _row_allows_rejoin(rows_by_tab, key):
            plan.connect.append(getattr(tab, "ws_url", "") or "")
    plan.stale = sorted(pooled - live)
    return plan


def sync_pool_presence(pool: Any, live_ids: Any, unconfirmed: Any = None) -> tuple[int, list]:
    """Flag pooled tabs gone from the browser that owns them; revive returnees. Never deletes.

    A page whose browser did not answer this pass is left exactly as it was (round 11,
    D-4): its worker is not dead, its tab list simply did not arrive.
    """
    try:
        pages = pool._pages
        lock = pool._lock
    except AttributeError:
        return 0, []
    live = set(live_ids or [])
    quiet = set(unconfirmed or [])
    revived = 0
    stale = []
    with lock:
        for tab_id, page in pages.items():
            verdict = _presence(page, tab_id, live, quiet)
            if verdict == "revive":
                page.is_connected = True
                revived += 1
            elif verdict == "stale":
                page.is_connected = False
                stale.append(tab_id)
    return revived, sorted(stale)


def _presence(page: Any, tab_id: str, live: set, quiet: set) -> str:
    """What one pooled page should become: `"revive"`, `"stale"` or `""` (leave it).

    A quiet browser's pages are left exactly as they are (round 11, D-4): its tab list
    never arrived, so it has said nothing about the worker either way.
    """
    if getattr(page, "browser", "") in quiet:
        return ""
    if tab_id in live:
        return "revive" if not page.is_connected else ""
    return "stale" if page.is_connected else ""


# ── Ownership repair + run gating (I-33: one live tab ↔ one row) ──

def _wins_over(row: dict, cur: dict) -> bool:
    """An enabled row displaces a disabled owner; ties keep the earlier."""
    return bool(row.get("enabled", False)) and not cur.get("enabled", False)


def _best_per_tab(rows: list) -> dict:
    """Winning row per tab_id; unlinked rows skipped."""
    best: dict = {}
    for r in rows:
        tid = r.get("tab_id", "")
        if not tid:
            continue
        if best.get(tid) is None or _wins_over(r, best[tid]):
            best[tid] = r
    return best


def dedupe_linked_rows(rows: Any) -> tuple[list, list]:
    """Collapse rows sharing a tab_id (legacy bug left N rows per tab).

    Keeps first enabled else first per tab; unlinked rows untouched.
    Returns (kept-in-order, dropped rows)."""
    clean = []
    for r in rows or []:
        if isinstance(r, dict):
            clean.append(r)
    best = _best_per_tab(clean)
    kept, dropped = [], []
    for r in clean:
        tid = r.get("tab_id", "")
        if not tid or best[tid] is r:
            kept.append(r)
        else:
            dropped.append(r)
    return kept, dropped


def enabled_tab_ids(urls: Any) -> set:
    """Tab ids owned by checked (enabled) URL rows — the run gate."""
    out = set()
    for u in urls or []:
        if getattr(u, "enabled", False) and getattr(u, "tab_id", ""):
            out.add(u.tab_id)
    return out


def row_for_tab(urls: Any, tab_id: str):
    """The checked row owning this tab, else None."""
    if not tab_id:
        return None
    for u in urls or []:
        if getattr(u, "enabled", False) and getattr(u, "tab_id", "") == tab_id:
            return u
    return None


def pick_url_for_tab(urls: Any, tab_id: str):
    """Row to record for a job on this tab: its owner, else first checked.

    Never re-binds a row: ownership belongs to auto-connect alone."""
    owner = row_for_tab(urls, tab_id)
    if owner is not None:
        return owner
    for u in urls or []:
        if getattr(u, "enabled", False):
            return u
    return None


def counts_in(pool: Any, allowed: set) -> tuple[int, int]:
    """(total, free) over allowed tabs only — parallel gate for checked rows."""
    try:
        with pool._lock:
            for p in pool._pages.values():
                p.try_expire()
            pages = [p for p in pool._pages.values() if p.tab_id in (allowed or set())]
            return len(pages), len([p for p in pages if p.is_free()])
    except AttributeError:
        return 0, 0


def _claimable_tid(page: Any, owned: set) -> str:
    """Connected pool page id no row owns yet; '' when not claimable."""
    p = page or {}
    tid = p.get("tab_id", "")
    if not tid or tid in owned or not p.get("is_connected", True):
        return ""
    return tid


def _claim_matches(url_row: Any, page: Any) -> bool:
    """Exact-URL verdict for binding a row to a pool page."""
    score, _kind = score_tab(getattr(url_row, "url", ""), (page or {}).get("url", ""))
    return score >= _CLAIM_MIN_SCORE


def claim_unlinked_from_pool(urls: Any, pages: Any) -> int:
    """Run-start rescue: link checked unlinked rows to their exact tab.

    Only an exact URL match on a connected page no row already owns;
    never steals. Returns number of rows linked."""
    claimed = 0
    owned = {getattr(u, "tab_id", "") for u in urls or [] if getattr(u, "tab_id", "")}
    for u in urls or []:
        if not getattr(u, "enabled", False) or getattr(u, "tab_id", ""):
            continue
        tid = _first_claimable_tid(u, owned, pages)
        if tid:
            u.tab_id = tid
            owned.add(tid)
            claimed += 1
    return claimed


def _first_claimable_tid(url_row: Any, owned: set, pages: Any) -> str:
    """First claimable page whose URL exactly matches this row."""
    for p in pages or []:
        tid = _claimable_tid(p, owned)
        if tid and _claim_matches(url_row, p):
            return tid
    return ""
