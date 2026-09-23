"""Wall-clock cooldown persistence — timers + readable tab ids survive a restart.

Entries keyed by tab_id (stable while Chrome runs); URL fallback covers
Chrome restarts too. Real time counts: cooldown_until is epoch-based and
expiry is checked against time.time() on load/restore. Plus per-URL job
counters (stats) for the Jobs columns (display only, never a routing input);
counters are never pruned, while the
`aliases` section (2026-09-21, D-5) keeps each tab's 4-digit readable number
and last known account — capped by recency, never pruned by a timer ending.
Reuses the same-layer JSON helpers; works on pool snapshots (no browser
imports beyond the pure `core.tab_alias` validator).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

from ..core.tab_alias import clean_entry
from .json_store import load_json as _load_json, save_json_atomic as _atomic_write

_VERSION = 1
_MAX_ENTRIES = 25
MAX_ALIASES = 200


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


def _write_doc(path, entries: dict, stats: dict, aliases: Optional[dict] = None) -> None:
    """Single atomic writer; oldest cooldown first out, stats intact.

    `aliases` is passed through unchanged; callers that do not own the section
    hand the one already on disk, so no writer can drop it (D-5/D-6).
    """
    items = sorted(entries.items(), key=_entry_sort_key)
    trimmed = dict(items[-_MAX_ENTRIES:])
    kept = load_aliases(path) if aliases is None else aliases
    _atomic_write(Path(path), {"version": _VERSION, "entries": trimmed,
                               "stats": stats, "aliases": kept})


def save_entries(path, entries: dict) -> None:
    """Atomic capped entry write; stats + aliases sections preserved untouched."""
    _write_doc(path, entries, load_stats(path))


# ---- readable tab ids (D-5/D-6) -------------------------------------------

def load_aliases(path) -> dict:
    """Per-tab readable ids: {tab_id: {no, email, seen}}; junk dropped."""
    raw = _load_json(Path(path), {})
    aliases = raw.get("aliases", {}) if isinstance(raw, dict) else {}
    if not isinstance(aliases, dict):
        return {}
    clean: dict[str, dict] = {}
    for tab_id, value in aliases.items():
        if not isinstance(tab_id, str) or not tab_id or not isinstance(value, dict):
            continue
        entry = clean_entry(value.get("no"), value.get("email"), value.get("seen"))
        if entry:
            clean[tab_id] = entry
    return clean


def _trim_aliases(aliases: dict) -> dict:
    """Newest first, capped — a number nobody has used for a while goes first."""
    items = sorted(aliases.items(),
                   key=lambda kv: float(kv[1].get("seen", 0) or 0), reverse=True)
    return dict(items[:MAX_ALIASES])


def save_aliases(path, aliases: dict) -> None:
    """Merge + cap the alias section; timers and stats stay untouched."""
    merged = load_aliases(path)
    for tab_id, value in dict(aliases or {}).items():
        if not isinstance(tab_id, str) or not tab_id or not isinstance(value, dict):
            continue
        entry = clean_entry(value.get("no"), value.get("email"), value.get("seen"))
        if entry:
            merged[tab_id] = entry
    _write_doc(path, load_entries(path), load_stats(path), _trim_aliases(merged))


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


def _persistable(until: float, pending: int, moment: float) -> bool:
    """A live timer or a stacked debt is worth keeping — status is a label (D-1)."""
    return until > moment or pending > 0


def _entry_from_page(page: dict) -> Optional[dict]:
    """Persistable entry for cooling/pending pages, else None."""
    until = float(page.get("cooldown_until", 0) or 0)
    pending = int(page.get("pending_penalty", 0) or 0)
    if not _persistable(until, pending, time.time()):
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


def _merge_page_alias(aliases: dict, page: dict) -> None:
    """Fold one page's readable id in; the account is refreshed only when known."""
    tab_id = page.get("tab_id", "")
    entry = aliases.get(tab_id)
    if entry is None:
        fresh = clean_entry(page.get("alias_no"), page.get("owner", ""), time.time())
        if fresh:
            aliases[tab_id] = fresh
        return
    owner = page.get("owner", "")
    if isinstance(owner, str) and owner.strip():
        entry["email"] = owner.strip().lower()
    entry["seen"] = time.time()


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
    aliases = load_aliases(path)
    for page in pages:
        if not isinstance(page, dict) or not page.get("tab_id", ""):
            continue
        _merge_page_entry(entries, page)
        _merge_page_stats(stats, page)
        _merge_page_alias(aliases, page)
    _write_doc(path, entries, stats, _trim_aliases(aliases))


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
