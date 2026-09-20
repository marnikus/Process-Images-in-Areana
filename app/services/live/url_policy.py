"""URL-row policy — rows follow Chrome, every removal has a reason (S6, D-4 / I-50).

Pure functions over the planner's row dicts (`{id, url, tab_id, enabled}`):

* `removable_rows(spec)` — a table of `(reason, predicate)` pairs, first
  match wins, linked rows only (a never-linked user row is the user's, D-4);
  a row whose tab runs a job is deferred, not removed (RULE 15);
  `tab_gone` needs `MISS_THRESHOLD` consecutive misses (hysteresis).
* `advance_misses` — the per-tab miss counters (dropped on reappearance).
* `dedupe_rows` / `add_rows` / `tab_owned` — moved from `panels/url_queue`
  (the panel keeps 2-line delegations); `add_rows` restores the checkbox a
  closed tab's row had (`remember` / `restore_enabled`, bounded memory).
* `removal_lines` — one log line per removal (RULE 2 vocabulary).

Layer: services → services/core only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

from app.core.models import UrlRow
from app.services.auto_connect import dedupe_linked_rows, matches_pattern

MISS_THRESHOLD = 2      # consecutive fetches without the tab before its row goes
MEMORY_MAX = 200        # remembered checkbox states (url → enabled), oldest out first

REASON_TEXT = {
    "tab_gone": "tab closed",
    "pattern_mismatch": "URL no longer matches the pattern",
    "invalid": "URL is not http(s)",
    "duplicate": "duplicate row for one tab (I-33)",
}


@dataclass
class Removal:
    row_id: str
    url: str
    reason: str


@dataclass
class RemovalSpec:
    """What a pass knows when it decides removals (never carries a bridge)."""

    rows: list
    live_keys: set
    pattern: str = ""
    busy_tabs: set = field(default_factory=set)
    misses: dict = field(default_factory=dict)
    deferred: list = field(default_factory=list)   # filled by removable_rows: busy tabs kept for now


def _is_duplicate(row: dict, spec: RemovalSpec) -> bool:
    _kept, dropped = dedupe_linked_rows(spec.rows)
    return any(d is row for d in dropped)


def _is_invalid(row: dict, spec: RemovalSpec) -> bool:
    return not str(row.get("url") or "").startswith(("http://", "https://"))


def _pattern_mismatch(row: dict, spec: RemovalSpec) -> bool:
    return bool(spec.pattern) and not matches_pattern(row.get("url", ""), spec.pattern)


def _tab_gone(row: dict, spec: RemovalSpec) -> bool:
    tab_id = row.get("tab_id", "")
    return tab_id not in spec.live_keys and spec.misses.get(tab_id, 0) >= MISS_THRESHOLD


REMOVAL_RULES: tuple = (   # ordered: the most specific reason first (RULE 19: a table, not a chain)
    ("duplicate", _is_duplicate),
    ("invalid", _is_invalid),
    ("pattern_mismatch", _pattern_mismatch),
    ("tab_gone", _tab_gone),
)


def _reason_for(row: dict, spec: RemovalSpec) -> str:
    return next((reason for reason, pred in REMOVAL_RULES if pred(row, spec)), "")


def removable_rows(spec: RemovalSpec) -> List[Removal]:
    """Linked rows to drop, each with its reason; busy tabs are deferred into `spec.deferred`."""
    out: List[Removal] = []
    for row in spec.rows:
        if not row.get("tab_id"):
            continue
        reason = _reason_for(row, spec)
        if not reason:
            continue
        if row["tab_id"] in spec.busy_tabs:
            spec.deferred.append(row.get("id", ""))
            continue
        out.append(Removal(row.get("id", ""), row.get("url", ""), reason))
    return out


def advance_misses(rows: Iterable[dict], live_keys: set, misses: Dict[str, int]) -> Dict[str, int]:
    """Miss counters for linked rows: +1 while the tab is absent, forgotten once it is back."""
    out: Dict[str, int] = {}
    for row in rows:
        tab_id = row.get("tab_id", "")
        if tab_id and tab_id not in live_keys:
            out[tab_id] = misses.get(tab_id, 0) + 1
    return out


def busy_tabs(pool: Any) -> set:
    """Tabs with a job in flight (`current_image`), read from the pool snapshot."""
    try:
        return {p.get("tab_id") for p in pool.status_snapshot()["pages"] if p.get("current_image")}
    except Exception:
        return set()


def dedupe_rows(state_urls: list) -> tuple[list, int]:
    """Repair legacy N-rows-per-tab state in place; returns (plan rows, removed)."""
    rows = [{"id": u.id, "url": u.url, "tab_id": u.tab_id, "enabled": u.enabled} for u in state_urls]
    kept, dropped = dedupe_linked_rows(rows)
    if not dropped:
        return rows, 0
    drop = {r["id"] for r in dropped}
    state_urls[:] = [u for u in state_urls if u.id not in drop]
    return kept, len(dropped)


def tab_owned(urls: Iterable, tab_id: str) -> bool:
    """One row per tab (I-33): never add a second."""
    return any(u.tab_id == tab_id for u in urls)


def add_rows(urls: list, adds: Iterable[tuple], memory: Optional[dict] = None) -> int:
    """Append rows for tabs none owns yet (checkbox restored from memory); returns count added."""
    added = 0
    for url, tab_id in adds:
        if tab_owned(urls, tab_id):
            continue
        urls.append(UrlRow.create(url, enabled=restore_enabled(memory or {}, url), tab_id=tab_id))
        added += 1
    return added


def remember(memory: dict, row: dict) -> None:
    """Keep a removed row's checkbox by URL; bounded, oldest entry out first."""
    memory.pop(row.get("url", ""), None)
    memory[row.get("url", "")] = bool(row.get("enabled", True))
    while len(memory) > MEMORY_MAX:
        memory.pop(next(iter(memory)))


def restore_enabled(memory: dict, url: str, default: bool = True) -> bool:
    return bool(memory.get(url, default))


def removal_lines(removals: Iterable[Removal]) -> List[str]:
    """One line per removed row, naming the reason (RULE 2)."""
    return [f"🤖 URL row removed: {r.url} — {REASON_TEXT.get(r.reason, r.reason)}" for r in removals]
