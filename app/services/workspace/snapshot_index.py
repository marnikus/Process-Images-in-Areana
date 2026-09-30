"""Snapshot index — recent snapshots, last save, last restore (`workspace_meta.json`).

One small JSON beside the config (never inside a snapshot). Save records a
published folder, restore records its result, the window reads all three.
Missing folders are pruned from the list, never shown. The index is read with
`provider.read_live_json` — the ONE live-file read rule: missing = empty,
corrupt/non-object = broken, warned once and rebuilt (audit #3 N2, RULE 4).
Imports: services → persistence only (no Qt).
"""

from __future__ import annotations

from pathlib import Path

from app.persistence.json_store import save_json_atomic
from .meta import META_FILE, RECENT_CAP, config_dir, log_message, utc_now_iso
from .provider import read_live_json


def _meta_path(bridge) -> Path:
    return config_dir(bridge) / META_FILE


_BROKEN_WARNED: set = set()   # one warning per broken index file, not one per read


def _read_meta(bridge) -> dict:
    meta, cause = _load_meta(bridge)
    return {} if cause else meta


def _load_meta(bridge) -> tuple:
    """Read the index with the ONE live-read rule; a broken file is warned once (N2)."""
    path = _meta_path(bridge)
    meta, cause = read_live_json(path)
    _note_index_health(bridge, path, cause)
    return meta, cause


def _note_index_health(bridge, path: Path, cause: str) -> None:
    """Remember a broken index file (one warning), forget it once it reads clean."""
    key = str(path)
    if cause:
        _broken_once(bridge, key, cause)
    else:
        _BROKEN_WARNED.discard(key)


def _broken_once(bridge, key: str, cause: str) -> None:
    """The warning itself — once per file, until a later read succeeds (N2)."""
    if key not in _BROKEN_WARNED:
        _BROKEN_WARNED.add(key)
        log_message(bridge, f"⚠️ Workspace index unreadable — rebuilding it: {cause}", "warn")


def _recent_paths(meta: dict) -> list:
    """`recent` entries that are usable path strings (a hand-edited index is inert)."""
    recent = meta.get("recent")
    return [p for p in recent if isinstance(p, str) and p] if isinstance(recent, list) else []


def _record(meta: dict, key: str) -> dict:
    """One of the `{path, utc, …}` records, or {} when the file carries junk."""
    value = meta.get(key)
    return value if isinstance(value, dict) else {}


def _write_meta(bridge, meta: dict) -> None:
    try:
        save_json_atomic(_meta_path(bridge), meta)
    except OSError as exc:
        log_message(bridge, f"⚠️ Workspace index not saved ({META_FILE}): {exc} — "
                            "the snapshot itself is fine; the recent list may be stale", "warn")


def record_snapshot(bridge, path: str) -> None:
    meta = _read_meta(bridge)
    recent = [p for p in _recent_paths(meta) if p != path]
    recent.insert(0, path)
    meta["recent"] = recent[:RECENT_CAP]
    meta["last_snapshot"] = {"path": path, "utc": utc_now_iso()}
    _write_meta(bridge, meta)


def record_restore(bridge, root: str, result: str) -> None:
    meta = _read_meta(bridge)
    meta["last_restore"] = {"path": str(root), "utc": utc_now_iso(), "result": result}
    _write_meta(bridge, meta)


def _prune_recent(bridge, meta: dict) -> list:
    """Drop entries whose folder is gone (never shown), rewriting the index if it changed."""
    paths = _recent_paths(meta)
    kept = [p for p in paths if Path(p).exists()]
    if kept != paths:
        meta["recent"] = kept
        _write_meta(bridge, meta)
    return kept


def recent_snapshots(bridge, limit: int = RECENT_CAP) -> list:
    """Existing recent snapshots (missing/garbage entries pruned, never shown)."""
    kept = _prune_recent(bridge, _read_meta(bridge))
    return kept[:max(1, int(limit))]


def last_snapshot(bridge) -> str:
    """The quick-load target: the last successful save, when it still exists."""
    path = _record(_read_meta(bridge), "last_snapshot").get("path", "")
    return path if isinstance(path, str) and path and Path(path).exists() else ""


def last_restore(bridge) -> dict:
    """The last restore attempt ({path, utc, result}) for the window's status line."""
    return _record(_read_meta(bridge), "last_restore")
