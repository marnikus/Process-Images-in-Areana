"""Wall-clock cooldown persistence — timers survive app restart.

Entries keyed by tab_id (stable while Chrome runs); URL fallback covers
Chrome restarts too. Real time counts: cooldown_until is epoch-based and
expiry is checked against time.time() on load/restore. Plus per-URL job
counters (stats) for load balancing; counters are never pruned. Reuses
the same-layer JSON helpers; works on pool snapshots (no browser imports).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

from .json_store import atomic_write_json as _atomic_write
from .json_store import load_json as _load_json

_VERSION = 1
_MAX_ENTRIES = 25


def _is_idle_expired(entry: dict, now: float) -> bool:
    """Expired with no stacked penalty (junk counts as expired)."""
    try:
        until = float(entry.get("cooldown_until", 0) or 0)
        pending = int(entry.get("pending_penalty", 0) or 0)
    except (TypeError, ValueError):
        return True
    return until <= now and pending <= 0


def load_entries(path) -> dict:
    """Read persisted timers; drops expired-idle and malformed entries."""
    raw = _load_json(Path(path), {})
    entries = raw.get("entries", {}) if isinstance(raw, dict) else {}
    if not isinstance(entries, dict):
        return {}
    now = time.time()
    return {k: v for k, v in entries.items()
            if isinstance(v, dict) and not _is_idle_expired(v, now)}


def _entry_sort_key(kv) -> float:
    """Sort entries by cooldown end; junk sorts first (evicted first)."""
    _key, val = kv
    if not isinstance(val, dict):
        return 0
    try:
        return float(val.get("cooldown_until", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _write_doc(path, entries: dict, stats: dict) -> None:
    """Single atomic writer; oldest cooldown first out, stats intact."""
    items = sorted(entries.items(), key=_entry_sort_key)
    trimmed = dict(items[-_MAX_ENTRIES:])
    _atomic_write(Path(path), {"version": _VERSION, "entries": trimmed, "stats": stats})


def save_entries(path, entries: dict) -> None:
    """Atomic capped entry write; stats section preserved untouched."""
    _write_doc(path, entries, load_stats(path))


def describe_cooldown_file(path) -> dict:
    """One extra read of diagnostics for restore logging (no writes)."""
    exists = Path(path).exists()
    raw = _load_json(Path(path), {})
    entries = raw.get("entries", {}) if isinstance(raw, dict) else {}
    total = len(entries) if isinstance(entries, dict) else 0
    live = load_entries(path)
    dropped = [k for k in (entries if isinstance(entries, dict) else {}) if k not in live]
    return {"exists": exists, "raw": total, "live": len(live), "dropped": dropped}


def _saved_jobs(val: Any) -> int:
    """Counter inside a stats value; 0 unless a valid dict entry."""
    if not isinstance(val, dict):
        return 0
    count = val.get("jobs_completed", 0)
    if isinstance(count, bool) or not isinstance(count, int):
        return 0
    return max(count, 0)


def load_stats(path) -> dict:
    """Job counters by normalized URL; malformed values dropped."""
    raw = _load_json(Path(path), {})
    stats = raw.get("stats", {}) if isinstance(raw, dict) else {}
    if not isinstance(stats, dict):
        return {}
    clean: dict[str, dict] = {}
    for url, val in stats.items():
        key = normalize_url(url)
        if not key or not isinstance(val, dict):
            continue
        count = val.get("jobs_completed", 0)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            continue
        prev = _saved_jobs(clean.get(key))
        clean[key] = {"jobs_completed": max(prev, count)}
    return clean


def _persistable(status: str, until: float, pending: int, moment: float) -> bool:
    """Cooling with future time, or any stacked penalty, is worth keeping."""
    if status != "cooldown":
        return pending > 0
    return until > moment


def _entry_from_page(page: dict) -> Optional[dict]:
    """Persistable entry for cooling/pending pages, else None."""
    until = float(page.get("cooldown_until", 0) or 0)
    pending = int(page.get("pending_penalty", 0) or 0)
    if not _persistable(page.get("status", ""), until, pending, time.time()):
        return None
    return {"tab_id": page.get("tab_id", ""), "url": page.get("url", ""),
            "title": page.get("title", ""), "cooldown_until": until,
            "cooldown_total": int(page.get("cooldown_total", 0) or 0),
            "pending_penalty": pending,
            "captcha_count": int(page.get("captcha_count", 0) or 0),
            "reason": page.get("cooldown_reason", "") or "",
            "saved_at": time.time()}


def _merge_page_entry(entries: dict, page: dict) -> None:
    """Fold one page's timer in; idle pages drop their entry."""
    entry = _entry_from_page(page)
    if entry is None:
        entries.pop(page.get("tab_id", ""), None)
    else:
        entries[page.get("tab_id", "")] = entry


def _merge_page_stats(stats: dict, page: dict) -> None:
    """Fold one page's job counter in; stored count never decreases."""
    key = normalize_url(page.get("url", ""))
    done = page.get("jobs_completed", 0)
    if not key or isinstance(done, bool) or not isinstance(done, int):
        return
    stats[key] = {"jobs_completed": max(_saved_jobs(stats.get(key)), done)}


def save_pool_snapshot(path, pool) -> None:
    """Merge live timers + job counters; pool-absent entries kept."""
    try:
        pages = pool.status_snapshot().get("pages", [])
    except Exception:
        return
    entries = load_entries(path)
    stats = load_stats(path)
    for page in pages:
        if not isinstance(page, dict) or not page.get("tab_id", ""):
            continue
        _merge_page_entry(entries, page)
        _merge_page_stats(stats, page)
    _write_doc(path, entries, stats)


def normalize_url(url: Any) -> str:
    """Canonical URL form (case/trailing-slash tolerant, query kept)."""
    if not isinstance(url, str):
        return ""
    return url.strip().lower().rstrip("/")


def _owned_by_other(entry: dict, tab_id: str, known) -> bool:
    """Entry belongs to a different registered tab — never hand it over."""
    owner = entry.get("tab_id", "")
    return bool(owner and owner != tab_id and owner in known)


def consume_entry_for(entries: dict, tab_id: str, page_url: str, known_tab_ids=frozenset()):
    """Pop entry by exact tab id, else exact normalized URL — but never an
    entry owned by another registered tab (same-URL tabs stay isolated)."""
    if tab_id and tab_id in entries:
        return tab_id, entries.pop(tab_id)
    want = normalize_url(page_url)
    if want:
        known = known_tab_ids or frozenset()
        for key, entry in list(entries.items()):
            if not isinstance(entry, dict):
                continue
            if _owned_by_other(entry, tab_id, known):
                continue
            if normalize_url(entry.get("url", "")) == want:
                return key, entries.pop(key)
    return None, None
