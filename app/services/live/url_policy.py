"""Pure URL-row policy for the reconciler (S6, D-4 / I-50) — no bridge, no I/O.

Removal is a table of `(reason, predicate)` pairs (RULE 19 step 2): a row is
removed for the FIRST reason that holds, deferred (never removed) while its
tab has a live job (RULE 15), and never-linked user rows are kept — a typed
row is authorisation, not garbage. Closed tabs get hysteresis: a row goes
only after `miss_threshold` consecutive fetches without its tab.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Set, Tuple

from app.core.enums import UrlStatus
from app.core.models import UrlRow
from app.services.auto_connect import dedupe_linked_rows, enabled_tab_ids, matches_pattern

MEMORY_LIMIT = 200
MISS_THRESHOLD = 2
INVALID_STATUSES = frozenset({UrlStatus.AUTH_REQUIRED.value, UrlStatus.UNSUPPORTED.value,
                              UrlStatus.UNAVAILABLE.value})


@dataclass
class RemovalSpec:
    rows: List[Any]
    live_keys: Set[str]
    pattern: str = ""
    busy_tabs: Set[str] = field(default_factory=set)
    misses: Dict[str, int] = field(default_factory=dict)
    miss_threshold: int = MISS_THRESHOLD


@dataclass(frozen=True)
class Removal:
    row_id: str
    url: str
    reason: str  # duplicate | invalid | pattern_mismatch | tab_gone


def owns_run_tab(row: Any) -> bool:
    """A checked row linked to a tab — the same gate as `auto_connect.enabled_tab_ids`."""
    return bool(getattr(row, "enabled", False)) and bool(getattr(row, "tab_id", ""))


def _is_duplicate(row: Any, spec: RemovalSpec, seen: Set[str]) -> bool:
    tid = row.tab_id
    if tid in seen:
        return True
    seen.add(tid)
    return False


def _is_invalid(row: Any, spec: RemovalSpec, seen: Set[str]) -> bool:
    return row.last_status in INVALID_STATUSES


def _is_pattern_mismatch(row: Any, spec: RemovalSpec, seen: Set[str]) -> bool:
    return not matches_pattern(row.url, spec.pattern)


def _is_tab_gone(row: Any, spec: RemovalSpec, seen: Set[str]) -> bool:
    return row.tab_id not in spec.live_keys and spec.misses.get(row.tab_id, 0) >= spec.miss_threshold


Predicate = Callable[[Any, RemovalSpec, Set[str]], bool]
REMOVAL_RULES: Tuple[Tuple[str, Predicate], ...] = (
    ("duplicate", _is_duplicate),
    ("invalid", _is_invalid),
    ("pattern_mismatch", _is_pattern_mismatch),
    ("tab_gone", _is_tab_gone),
)


def _first_reason(row: Any, spec: RemovalSpec, seen: Set[str]) -> str:
    """The first table reason that holds for a LINKED row ('' = keep)."""
    if not row.tab_id:
        return ""
    return next((reason for reason, holds in REMOVAL_RULES if holds(row, spec, seen)), "")


def _decisions(spec: RemovalSpec) -> List[Tuple[Removal, bool]]:
    """Every (removal, deferred) pair in row order; kept rows are absent."""
    seen: Set[str] = set()
    out = []
    for row in spec.rows:
        reason = _first_reason(row, spec, seen)
        if reason:
            out.append((Removal(row.id, row.url, reason), row.tab_id in spec.busy_tabs))
    return out


def removable_rows(spec: RemovalSpec) -> List[Removal]:
    """Rows to remove now (busy tabs are deferred — see `deferred_rows`)."""
    return [removal for removal, deferred in _decisions(spec) if not deferred]


def deferred_rows(spec: RemovalSpec) -> List[Removal]:
    """Rows that would go but whose tab has a live job (removed on a later pass)."""
    return [removal for removal, deferred in _decisions(spec) if deferred]


def busy_tabs(pool: Any, tab_ids: Iterable[str]) -> Set[str]:
    """Tab ids with a live job (`cooldown_service.tab_has_live_job`); empty without a pool."""
    from app.services.cooldown_service import tab_has_live_job
    if pool is None:
        return set()
    return {tid for tid in tab_ids if tid and tab_has_live_job(pool, tid)}


def advance_misses(rows: Iterable[Any], live_keys: Set[str], misses: Dict[str, int]) -> Dict[str, int]:
    """Hysteresis counters per linked tab: +1 while absent, dropped when it reappears."""
    out: Dict[str, int] = {}
    for row in rows:
        tid = getattr(row, "tab_id", "")
        if tid and tid not in live_keys:
            out[tid] = misses.get(tid, 0) + 1
    return out


def dedupe_rows(state_urls: list) -> tuple[list, int]:
    """Repair legacy N-rows-per-tab state in place; returns (plan rows, removed)."""
    rows = [{"id": u.id, "url": u.url, "tab_id": u.tab_id, "enabled": u.enabled}
            for u in state_urls]
    kept, dropped = dedupe_linked_rows(rows)
    if not dropped:
        return rows, 0
    drop = {r["id"] for r in dropped}
    state_urls[:] = [u for u in state_urls if u.id not in drop]
    return kept, len(dropped)


def add_rows(urls: list, adds: Iterable[Tuple[str, str]], memory: Dict[str, bool] | None = None) -> int:
    """Append rows for tabs none owns yet (I-33), restoring a remembered checkbox; returns count."""
    owned = {u.tab_id for u in urls if u.tab_id}
    added = 0
    for url, tab_id in adds:
        if tab_id in owned:
            continue
        urls.append(UrlRow.create(url, enabled=restore_enabled(url, memory), tab_id=tab_id))
        owned.add(tab_id)
        added += 1
    return added


def remember(rows: Iterable[Any], memory: Dict[str, bool]) -> None:
    """url → enabled for rows about to go, bounded at `MEMORY_LIMIT` (oldest evicted)."""
    for row in rows:
        memory.pop(row.url, None)
        memory[row.url] = bool(row.enabled)
    while len(memory) > MEMORY_LIMIT:
        memory.pop(next(iter(memory)))


def restore_enabled(url: str, memory: Dict[str, bool] | None) -> bool:
    """A re-opened tab gets the checkbox the user left it with (default checked)."""
    return bool((memory or {}).get(url, True))


_REASON_TEXT = {
    "tab_gone": lambda pattern, threshold: f"tab closed ({threshold} reconciles)",
    "pattern_mismatch": lambda pattern, threshold: f"does not match pattern '{pattern}'",
    "invalid": lambda pattern, threshold: "invalid — status is not usable",
    "duplicate": lambda pattern, threshold: "duplicate row for the same tab",
}


def removal_lines(removals: Iterable[Removal], pattern: str = "", threshold: int = MISS_THRESHOLD) -> List[str]:
    """One log line per removal, reason included (RULE 2)."""
    return [f"🔻 URL removed {r.url} — {_REASON_TEXT[r.reason](pattern, threshold)}" for r in removals]


# ── Receiver flag (S7, D-18 / I-53): one owner, the web UI only reflects it ──

RECEIVER_TITLES = {
    "unchecked": "Not used as job receiver — row unchecked",
    "not linked": "Not used as job receiver — no Chrome tab linked",
    "offline": "Not used as job receiver — tab not connected",
    "busy": "Not used as job receiver — tab busy with a job",
}


def _connected_tabs(pool: Any) -> Set[str]:
    """Pooled + connected tab ids (empty without a pool)."""
    try:
        return {p["tab_id"] for p in pool.status_snapshot()["pages"] if p.get("is_connected")}
    except (AttributeError, KeyError, TypeError):
        return set()


def receiver_reason(row: Any, pool: Any) -> str:
    """'' when the row can receive a job now, else the first failing gate."""
    if not row.enabled:
        return "unchecked"
    if not row.tab_id:
        return "not linked"
    if row.tab_id not in _connected_tabs(pool) or row.tab_id not in enabled_tab_ids([row]):
        return "offline"
    return "busy" if busy_tabs(pool, [row.tab_id]) else ""


def receiver_title(row: Any, pool: Any) -> str:
    """The icon's tooltip (the reason's wording; '' for a receiver)."""
    return RECEIVER_TITLES.get(receiver_reason(row, pool), "")


def mark_receivers(rows: Iterable[Any], pool: Any) -> int:
    """The ONE writer of `UrlRow.receiver`; returns how many rows changed."""
    changed = 0
    for row in rows:
        value = receiver_reason(row, pool) == ""
        if row.receiver != value:
            row.receiver = value
            changed += 1
    return changed


# ── Checkbox owns pool membership (D-3, 2026-09-21): one decision, two enforcers ──

@dataclass(frozen=True)
class PoolExit:
    """A pooled tab that must leave the pool — the membership rule's output (I-56/I-58).

    `reason` is `unchecked` (the row exists, its checkbox is off) or `orphan`
    (no row owns the tab at all — a row the removal table/✕/undo dropped).
    `row` is the owning row for `unchecked` and None for `orphan`.
    """

    tab_id: str
    reason: str
    row: Any = None


_EXIT_LINES = {
    "unchecked": "🚪 URL unchecked {url} — tab left the worker pool",
    "orphan": "🚪 Worker {tab} left the pool — no URL row owns it",
}
_DEFER_LINES = {
    "unchecked": "⏸ Pool exit deferred {url} — job running on its tab (next reconcile)",
    "orphan": "⏸ Pool exit deferred {tab} — job running on its tab (next reconcile)",
}


def _exit_text(table: dict, exit: PoolExit) -> str:
    """One wording for both enforcers (the service and the UI log the same sentence)."""
    try:
        return table.get(exit.reason, "🚪 Worker {tab} left the pool").format(
            url=getattr(exit.row, "url", "") or "", tab=(exit.tab_id or "")[:12])
    except Exception:
        return f"🚪 Worker {(exit.tab_id or '')[:12]} left the pool"


def exit_line(exit: PoolExit) -> str:
    """The log line for a tab leaving the pool (reason-specific)."""
    return _exit_text(_EXIT_LINES, exit)


def defer_line(exit: PoolExit) -> str:
    """The log line for a busy tab whose exit is postponed (RULE 15)."""
    return _exit_text(_DEFER_LINES, exit)


def _unchecked_exits(rows: Iterable[Any], pooled: Set[str]) -> List[PoolExit]:
    """Checked-off rows whose linked tab is pooled (I-56, the checkbox half)."""
    return [PoolExit(r.tab_id, "unchecked", r) for r in rows or []
            if getattr(r, "tab_id", "") and r.tab_id in pooled and not getattr(r, "enabled", True)]


def _orphan_exits(rows: Iterable[Any], pooled: Set[str]) -> List[PoolExit]:
    """Pooled tabs NO row owns (I-58, the ownership half): the pool never exceeds the rows."""
    owned = {getattr(r, "tab_id", "") for r in rows or []} - {""}
    return [PoolExit(tid, "orphan") for tid in sorted(pooled - owned)]


def pool_exits(rows: Iterable[Any], pool: Any) -> tuple[List[PoolExit], List[PoolExit]]:
    """Pooled tabs no CHECKED row owns: (leave now, deferred while a job runs).

    The one membership rule (S11 + I-58): the URL list authorises every worker,
    so a pooled tab is out when its row's checkbox is off (I-56) or when no row
    owns it at all (I-58 — a row the removal table, the ✕ button or an undo
    dropped). The busy deferral is the same gate the removal table uses
    (RULE 15 — nothing leaves mid-job); no pool → nothing to enforce.
    """
    try:
        pooled = set(pool._pages.keys())
    except AttributeError:
        return [], []
    candidates = _unchecked_exits(rows, pooled) + _orphan_exits(rows, pooled)
    busy = busy_tabs(pool, [e.tab_id for e in candidates])
    now = [e for e in candidates if e.tab_id not in busy]
    later = [e for e in candidates if e.tab_id in busy]
    return now, later
