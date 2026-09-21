"""URL-row policy for the live reconciler (S6): one removal table + tab memory.

Pure over row data — no panel/browser imports (services lane). A row may leave
the list only with a named reason (RULE 2); a tab with a live job defers (RULE 15).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app.core.models import UrlRow
from app.services.auto_connect import dedupe_linked_rows, enabled_tab_ids, matches_pattern

MISS_THRESHOLD = 2           # a gone tab must miss twice before its row leaves
MEMORY_MAX = 200             # remembered checkboxes, oldest evicted first

REASON_TEXT = {"tab_gone": "tab gone", "invalid": "invalid",
               "pattern_mismatch": "pattern mismatch", "duplicate": "duplicate"}


@dataclass
class Removal:
    """One row leaving the URL list, with its reason (RULE 2)."""
    row_id: str
    url: str
    reason: str


@dataclass
class RemovalSpec:
    """Inputs to one removal pass; `deferred` collects busy-tab out-comes."""
    rows: list
    live_keys: set
    pattern: str = "arena.ai"
    busy_tabs: set = field(default_factory=set)
    misses: dict = field(default_factory=dict)
    deferred: set = field(default_factory=set)


def _is_linked(row) -> bool:
    """Linked = owns a live tab id; user rows never linked yet are kept (D-4)."""
    return bool(getattr(row, "tab_id", "") or "")


def _first_per_tab(rows) -> dict:
    """tab_id -> id of the first row owning it (the later twins are duplicates)."""
    first = {}
    for r in rows or []:
        tid = getattr(r, "tab_id", "") or ""
        if tid and tid not in first:
            first[tid] = getattr(r, "id", "")
    return first


_REMOVAL_CHECKS: tuple[tuple[str, Callable], ...] = (
    ("duplicate", lambda r, sp, first: _is_linked(r) and first.get(r.tab_id) != getattr(r, "id", "")),
    ("invalid", lambda r, sp, first: not str(getattr(r, "url", "")).startswith("http")),
    ("pattern_mismatch", lambda r, sp, first: _is_linked(r) and bool(getattr(r, "enabled", False))
     and not matches_pattern(getattr(r, "url", ""), sp.pattern or "")),
    ("tab_gone", lambda r, sp, first: _is_linked(r) and r.tab_id not in (sp.live_keys or set())
     and sp.misses.get(getattr(r, "id", ""), 0) >= MISS_THRESHOLD),
)


def _reason_of(row, spec, first) -> str:
    """First table match wins; '' keeps the row."""
    for reason, hit in _REMOVAL_CHECKS:
        if hit(row, spec, first):
            return reason
    return ""


def removable_rows(spec: RemovalSpec) -> list[Removal]:
    """Every removal carries its reason; busy tabs defer (RULE 2/15)."""
    out = []
    first = _first_per_tab(spec.rows)
    for r in spec.rows or []:
        tid = getattr(r, "tab_id", "") or ""
        if tid and tid in (spec.busy_tabs or set()):
            if _reason_of(r, spec, first):
                spec.deferred.add(tid)
            continue
        reason = _reason_of(r, spec, first)
        if reason:
            out.append(Removal(row_id=getattr(r, "id", ""), url=str(getattr(r, "url", "")),
                               reason=reason))
    return out


def advance_misses(rows, live_keys, misses) -> dict:
    """Hysteresis counters: +1 per absent linked row; a reappearance resets."""
    live = live_keys or set()
    out = {}
    for r in rows or []:
        tid = getattr(r, "tab_id", "") or ""
        if not tid or tid in live:
            continue
        rid = getattr(r, "id", "")
        out[rid] = int((misses or {}).get(rid, 0)) + 1
    return out


def dedupe_rows(rows):
    """One row per tab (I-33) — the single wrapper behind url_queue's repair."""
    return dedupe_linked_rows(rows)


def add_rows(urls, adds) -> int:
    """Append rows for tabs none owns yet; returns count added."""
    owned = {getattr(u, "tab_id", "") for u in urls}
    added = 0
    for url, tab_id in adds or []:
        if tab_id in owned:
            continue
        urls.append(UrlRow.create(url, enabled=True, tab_id=tab_id))
        added += 1
    return added


def remember(memory: dict, url: str, enabled: bool) -> None:
    """Remember a checkbox BY URL (rows die and re-add; the URL is the identity)."""
    memory[url] = bool(enabled)
    while len(memory) > MEMORY_MAX:
        memory.pop(next(iter(memory)))


def restore_enabled(row, memory: dict) -> None:
    """A re-added/claimed row keeps its remembered checkbox when known (D-12R)."""
    url = getattr(row, "url", "")
    if url in (memory or {}):
        row.enabled = bool(memory[url])


def removal_lines(removals) -> list[str]:
    """One log line per removed row, reason spelled out (RULE 2 vocabulary)."""
    return [f"🧹 URL row removed — {r.url} — {REASON_TEXT.get(r.reason, r.reason)}"
            for r in removals or []]


def allowed_tab_ids(rows) -> set:
    """The run gate (`auto_connect.enabled_tab_ids` owns the math) — receivers only READ it (RULE 10)."""
    return enabled_tab_ids(rows)


def receiver_reason(row, allowed: set, pool) -> str:
    """Why a row can NOT take a run job right now (\"\" = receiver). One of 4 words (I-45)."""
    if not getattr(row, "enabled", False):
        return "unchecked"
    tab_id = getattr(row, "tab_id", "") or ""
    if not tab_id or tab_id not in (allowed or set()):
        return "not linked"
    page = pool.get_page(tab_id) if pool is not None else None
    if page is None or not getattr(page, "is_connected", False):
        return "offline"
    if getattr(page, "current_image", None):
        return "busy"
    return ""


def mark_receivers(rows, allowed: set, pool) -> int:
    """The ONE writer of row.receiver/receiver_reason (the icon only reflects). Returns changed."""
    changed = 0
    for row in rows or []:
        reason = receiver_reason(row, allowed, pool)
        receiver = not reason
        if getattr(row, "receiver", False) != receiver or getattr(row, "receiver_reason", "") != reason:
            row.receiver = receiver
            row.receiver_reason = reason
            changed += 1
    return changed
