"""S6: URL row policy — which rows a reconcile pass may remove, add, or dedupe.

Pure: no bridge, no pool, no signals. The reconciler (reconcile.py) feeds a
RemovalSpec and applies the verdicts; the reasons ride the log lines (RULE 2).
S7: + mark_receivers (receiver flags) — reads pool._pages through its pool
parameter, so tests inject a stub (still no bridge, no signals).
"""

from dataclasses import dataclass, field

from app.services.auto_connect import dedupe_linked_rows, enabled_tab_ids

MISS_THRESHOLD = 3
MEMORY_BOUND = 200
MAX_URL_LEN = 2048


@dataclass
class Removal:
    """One condemned row: id + url + the reason it goes."""

    row_id: str
    url: str
    reason: str


@dataclass
class RemovalSpec:
    """Everything the policy needs; `deferred` is an OUT-field."""
    rows: list
    live_keys: set
    pattern: str
    busy_tabs: set
    misses: dict
    deferred: list = field(default_factory=list)


def _valid_new_url(url: str):
    """Trimmed URL or an error string (add/edit gate); moved from url_queue."""
    url = (url or "").strip()
    if not url:
        return None, "empty URL"
    if not (url.startswith("http://") or url.startswith("https://")):
        return None, "URL must start with http:// or https://"
    if len(url) > MAX_URL_LEN:
        return None, f"URL too long (>{MAX_URL_LEN} chars)"
    return url, ""


def _tab_gone(row, spec):
    """Tri-state: False (live/unlinked), 'defer' (busy), True (gone 3+)."""
    tab_id = getattr(row, "tab_id", "") or ""
    if not tab_id or tab_id in spec.live_keys:
        return False
    if tab_id in spec.busy_tabs:
        spec.deferred.append(row.id)
        return "defer"
    if spec.misses.get(tab_id, 0) < MISS_THRESHOLD:
        return False
    return True


def _pattern_mismatch(row, spec):
    tab_id = getattr(row, "tab_id", "") or ""
    if not tab_id:
        return False
    pattern = (spec.pattern or "").strip()
    if not pattern:
        return False
    return pattern.lower() not in (getattr(row, "url", "") or "").lower()


def _invalid(row, spec):
    tab_id = getattr(row, "tab_id", "") or ""
    if not tab_id:
        return False
    _, err = _valid_new_url(getattr(row, "url", "") or "")
    return bool(err)


_REMOVAL_TABLE = (
    ("tab_gone", _tab_gone),
    ("pattern_mismatch", _pattern_mismatch),
    ("invalid", _invalid),
)


def _first_reason(row, spec):
    """First table hit wins; None when the row survives (deferrals aside)."""
    for reason, check in _REMOVAL_TABLE:
        hit = check(row, spec)
        if hit is True:
            return reason
    return None


def removable_rows(spec):
    """Removals in row order; duplicates resolved after the table."""
    out, seen = [], set()
    for row in spec.rows or []:
        reason = _first_reason(row, spec)
        if reason is None:
            tab_id = getattr(row, "tab_id", "") or ""
            if tab_id and tab_id in seen:
                reason = "duplicate"
            else:
                seen.add(tab_id)
                continue
        out.append(Removal(row.id, getattr(row, "url", "") or "", reason))
        if reason != "duplicate":
            seen.add(getattr(row, "tab_id", "") or "")
    return out


def advance_misses(rows, live_keys, misses):
    """Miss counters: +1 per absent linked tab, reset on reappearance."""
    live = live_keys or set()
    next_misses = {}
    for row in rows or []:
        tab_id = getattr(row, "tab_id", "") or ""
        if tab_id and tab_id not in live:
            next_misses[tab_id] = (misses or {}).get(tab_id, 0) + 1
    return next_misses


def dedupe_rows(state_urls):
    """Repair legacy N-rows-per-tab state; S6: moved from url_queue."""
    rows = [{"id": u.id, "url": u.url, "tab_id": u.tab_id, "enabled": u.enabled}
            for u in state_urls]
    kept, dropped = dedupe_linked_rows(rows)
    if not dropped:
        return rows, 0
    drop = {r["id"] for r in dropped}
    state_urls[:] = [u for u in state_urls if u.id not in drop]
    return kept, len(dropped)


def _tab_already_owned(urls, tab_id: str) -> bool:
    """One row per tab (I-33): never add a second. Moved from url_queue."""
    for u in urls:
        if u.tab_id == tab_id:
            return True
    return False


def add_rows(urls, adds, memory) -> int:
    """Append rows for tabs none owns yet; moved from url_queue + memory."""
    from app.core.models import UrlRow
    added = 0
    for url, tab_id in adds:
        if _tab_already_owned(urls, tab_id):
            continue
        urls.append(UrlRow.create(url, enabled=restore_enabled(tab_id, memory),
                                 tab_id=tab_id))
        added += 1
    return added


def remember(tab_id, enabled, memory):
    """Bank the checkbox before a removal; bounded, oldest-first eviction."""
    memory[tab_id] = bool(enabled)
    while len(memory) > MEMORY_BOUND:
        memory.pop(next(iter(memory)))


def restore_enabled(tab_id, memory):
    """Remembered checkbox, default checked for unknown tabs."""
    return (memory or {}).get(tab_id, True)


def removal_lines(removals):
    """One RULE 2 line per removed row, carrying its reason."""
    return [f"🗑 Removed row {r.url} — {r.reason}" for r in removals or []]


def _connected_ids(pool):
    """Ids of connected pool pages; empty when the pool is missing."""
    try:
        return {tid for tid, page in pool._pages.items() if page.is_connected}
    except Exception:
        return set()


def _receiver_tuple(tab_id, connected_ids, enabled_ids):
    """(flag, reason) for one tab: unassigned, unchecked, offline, else receiving."""
    if not tab_id:
        return False, "no tab assigned"
    if tab_id not in enabled_ids:
        return False, "not running"
    if tab_id not in connected_ids:
        return False, "offline"
    return True, ""


def _stamp_receiver(row, connected_ids, enabled_ids):
    """Stamp one row's (receiver, receiver_reason); True when the tuple changed."""
    want = _receiver_tuple(getattr(row, "tab_id", "") or "", connected_ids, enabled_ids)
    if (row.receiver, row.receiver_reason) != want:
        row.receiver, row.receiver_reason = want
        return True
    return False


def mark_receivers(rows, pool, connected_ids=None):
    """Stamp receiver flags + reasons on rows; return count of changed tuples.

    Enabled comes from the rows (enabled_tab_ids); connected comes from the
    pool unless the caller injects a set (tests, CDP-authoritative callers).
    """
    rows = rows or []
    enabled_ids = enabled_tab_ids(rows)
    if connected_ids is None:
        connected_ids = _connected_ids(pool)
    changed = 0
    for row in rows:
        if _stamp_receiver(row, connected_ids, enabled_ids):
            changed += 1
    return changed
