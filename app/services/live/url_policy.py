# ideal-size: ~185 lines reason=S6 budget — row reconcile policy: removal reasons, hysteresis, dedupe, memory, receivers (RULE 18.2)
"""live/url_policy (S6) — row removal, dedupe, memory, receiver flag (I-42)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services import auto_connect as ac


@dataclass
class RemovalSpec:
    rows: Any = field(default_factory=list)
    live_keys: set = field(default_factory=set)
    pattern: str = ""
    busy_tabs: set = field(default_factory=set)
    misses: dict = field(default_factory=dict)


@dataclass
class Removal:
    row_id: str
    url: str
    reason: str


def _is_invalid(url: str) -> bool:
    return not url or not (url.startswith("http://") or url.startswith("https://"))


def _row_reason(row, spec: RemovalSpec, seen: set) -> str | None:
    tid = getattr(row, "tab_id", "") or ""
    url = getattr(row, "url", "") or ""
    misses = spec.misses or {}
    if tid and tid in (spec.busy_tabs or set()):
        return None
    if not tid and getattr(row, "last_status", "") == "unchecked":
        return None
    if tid and tid in seen:
        return "duplicate"
    if tid and tid not in (spec.live_keys or set()):
        if (misses.get(tid, 0) + 1) < 3:
            return None
        return "tab_gone"
    if tid and spec.pattern:
        try:
            if not ac.matches_pattern(url, spec.pattern):
                return "pattern_mismatch"
        except Exception:
            pass
    if _is_invalid(url):
        return "invalid"
    return None


def removable_rows(spec: RemovalSpec) -> list[Removal]:
    rows = spec.rows or []
    seen: set[str] = set()
    out: list[Removal] = []
    for row in rows:
        reason = _row_reason(row, spec, seen)
        tid = getattr(row, "tab_id", "") or ""
        if tid and tid not in (spec.busy_tabs or set()) and tid not in seen:
            seen.add(tid)
        if reason:
            out.append(Removal(getattr(row, "id", ""), getattr(row, "url", ""), reason))
    return out


def advance_misses(rows: Any, live_keys: set, misses: dict) -> dict:
    live_keys = live_keys or set()
    misses = dict(misses or {})
    present = {getattr(r, "tab_id", "") for r in rows or [] if getattr(r, "tab_id", "")}
    for tid in list(misses.keys()):
        if tid in live_keys:
            misses.pop(tid, None)
    for tid in present:
        if tid not in live_keys:
            misses[tid] = misses.get(tid, 0) + 1
        else:
            misses.pop(tid, None)
    return misses


def dedupe_rows(rows: Any) -> tuple[list, list]:
    dicts = [{"id": getattr(r, "id", ""), "url": getattr(r, "url", ""), "tab_id": getattr(r, "tab_id", ""), "enabled": bool(getattr(r, "enabled", False))} for r in rows or []]
    kept_d, dropped_d = ac.dedupe_linked_rows(dicts)
    drop_ids = {d["id"] for d in dropped_d}
    kept = [r for r in rows if getattr(r, "id", "") not in drop_ids]
    dropped = [r for r in rows if getattr(r, "id", "") in drop_ids]
    return kept, dropped


def add_rows(rows: Any, adds: Any, memory: Any = None) -> int:
    from app.core.models import UrlRow as UR
    owned = {getattr(u, "tab_id", "") for u in rows or [] if getattr(u, "tab_id", "")}
    added = 0
    for it in adds or []:
        url, tid = (it[0], it[1]) if isinstance(it, (list, tuple)) else (it.get("url", ""), it.get("tab_id", ""))
        if not tid or tid in owned:
            continue
        enabled = bool(memory.get(tid, True)) if isinstance(memory, dict) and tid in memory else True
        rows.append(UR.create(url, enabled=enabled, tab_id=tid))
        owned.add(tid)
        added += 1
    return added


def remember(rows: Any, memory: dict | None = None) -> dict:
    mem = dict(memory or {})
    for r in rows or []:
        tid = getattr(r, "tab_id", "") or ""
        if tid:
            mem[tid] = bool(getattr(r, "enabled", False))
            if len(mem) > 200:
                mem.pop(next(iter(mem)))
    return mem


def restore_enabled(tab_id: str, memory: dict | None) -> bool:
    if memory and tab_id in memory:
        return bool(memory[tab_id])
    return True


def removal_lines(removals: list[Removal]) -> list[str]:
    return [f"🗑 Removed URL {r.url[:60]} — {r.reason}" for r in removals or []]


def receiver_reason(row: Any, allowed: set | None, pooled: set | None) -> str:
    if not getattr(row, "enabled", False): return "unchecked"
    tid = getattr(row, "tab_id", "") or ""
    if not tid: return "not linked"
    if tid not in (allowed or set()): return "unchecked"
    if tid not in (pooled or set()): return "offline"
    return ""


def mark_receivers(rows: Any, allowed: set | None, pooled: set | None) -> int:
    changed = 0
    for r in rows or []:
        want = receiver_reason(r, allowed, pooled) == ""
        if getattr(r, "receiver", None) != want:
            try: r.receiver = want
            except Exception: setattr(r, "receiver", want)
            changed += 1
    return changed
