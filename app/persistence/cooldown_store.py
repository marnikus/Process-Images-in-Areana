"""Wall-clock cooldown persistence — timers survive app restart.

Entries keyed by tab_id (stable while Chrome runs); URL fallback covers
Chrome restarts too. Real time counts: cooldown_until is epoch-based and
expiry is checked against time.time() on load/restore. Reuses the
same-layer JSON helpers; works on pool snapshots (no browser imports).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

from .config_manager import _atomic_write, _load_json

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


def save_entries(path, entries: dict) -> None:
    """Atomic capped write (oldest cooldown first out)."""
    items = sorted(entries.items(),
                   key=lambda kv: float(kv[1].get("cooldown_until", 0) or 0)
                   if isinstance(kv[1], dict) else 0)
    trimmed = dict(items[-_MAX_ENTRIES:])
    _atomic_write(Path(path), {"version": _VERSION, "entries": trimmed})


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


def save_pool_snapshot(path, pool) -> None:
    """Merge live timers into the file; pool-absent live entries kept."""
    try:
        pages = pool.status_snapshot().get("pages", [])
    except Exception:
        return
    entries = load_entries(path)
    for page in pages:
        if not isinstance(page, dict):
            continue
        tid = page.get("tab_id", "")
        if not tid:
            continue
        entry = _entry_from_page(page)
        if entry is None:
            entries.pop(tid, None)
        else:
            entries[tid] = entry
    save_entries(path, entries)


def _url_score(want: Any, have: Any) -> int:
    """2 exact, 1 prefix either way, else 0."""
    if not isinstance(want, str) or not isinstance(have, str):
        return 0
    w = want.strip().lower()
    h = have.strip().lower()
    if not w or not h:
        return 0
    if w == h:
        return 2
    if w.startswith(h) or h.startswith(w):
        return 1
    return 0


def consume_entry_for(entries: dict, tab_id: str, page_url: str):
    """Pop best entry: exact tab id, else best URL score."""
    if tab_id and tab_id in entries:
        return tab_id, entries.pop(tab_id)
    best_key, best_score = None, 0
    for key, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        score = _url_score(page_url, entry.get("url", ""))
        if score > best_score:
            best_key, best_score = key, score
    if best_key is None:
        return None, None
    return best_key, entries.pop(best_key)
