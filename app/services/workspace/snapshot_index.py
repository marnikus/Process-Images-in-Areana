"""Snapshot index — recent snapshots, last save, last restore (`workspace_meta.json`).

One small JSON beside the config (never inside a snapshot). Save records a
published folder, restore records its result, the window reads all three.
Missing folders are pruned from the list, never shown. Imports: services →
persistence only (no Qt, no providers).
"""

from __future__ import annotations

from pathlib import Path

from app.persistence.json_store import load_json, save_json_atomic
from .meta import META_FILE, RECENT_CAP, config_dir, utc_now_iso


def _meta_path(bridge) -> Path:
    return config_dir(bridge) / META_FILE


def _read_meta(bridge) -> dict:
    meta = load_json(_meta_path(bridge), {})
    return meta if isinstance(meta, dict) else {}


def _write_meta(bridge, meta: dict) -> None:
    try:
        save_json_atomic(_meta_path(bridge), meta)
    except OSError:
        pass


def record_snapshot(bridge, path: str) -> None:
    meta = _read_meta(bridge)
    recent = [p for p in meta.get("recent", []) if p != path]
    recent.insert(0, path)
    meta["recent"] = recent[:RECENT_CAP]
    meta["last_snapshot"] = {"path": path, "utc": utc_now_iso()}
    _write_meta(bridge, meta)


def record_restore(bridge, root: str, result: str) -> None:
    meta = _read_meta(bridge)
    meta["last_restore"] = {"path": str(root), "utc": utc_now_iso(), "result": result}
    _write_meta(bridge, meta)


def recent_snapshots(bridge, limit: int = RECENT_CAP) -> list:
    """Existing recent snapshots (missing ones pruned from the list, never shown)."""
    meta = _read_meta(bridge)
    kept = [p for p in meta.get("recent", []) if Path(p).exists()]
    if len(kept) != len(meta.get("recent", [])):
        meta["recent"] = kept
        _write_meta(bridge, meta)
    return kept[:max(1, int(limit))]


def last_snapshot(bridge) -> str:
    """The quick-load target: the last successful save, when it still exists."""
    meta = _read_meta(bridge)
    path = (meta.get("last_snapshot") or {}).get("path", "")
    return path if path and Path(path).exists() else ""


def last_restore(bridge) -> dict:
    """The last restore attempt ({path, utc, result}) for the window's status line."""
    meta = _read_meta(bridge)
    return meta.get("last_restore") or {}
