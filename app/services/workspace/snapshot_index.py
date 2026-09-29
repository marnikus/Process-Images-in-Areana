"""Snapshot index — recent snapshots, last save, last restore (`workspace_meta.json`).

One small JSON beside the config (never inside a snapshot). Save records a
published folder, restore records its result, the window reads all three.
Missing folders are filtered from the list, never shown. The explicit
`prune_missing` command cleans the file — `recent_snapshots` itself is now
pure (no write side-effect, S4 fix). Imports: services → persistence only.
"""

from __future__ import annotations

from pathlib import Path

from app.persistence.json_store import load_json, save_json_atomic
from .meta import META_FILE, RECENT_CAP, config_dir, log_message, utc_now_iso


class SnapshotIndex:
    """Encapsulates workspace_meta.json read/write + pruning (S4).

    The old module-level functions delegate to this class for backward compat.
    `recent()` is pure (filters missing, no write); `prune_missing()` is the
    explicit command that writes.
    """

    def __init__(self, bridge):
        self._bridge = bridge
        self._path = config_dir(bridge) / META_FILE

    def _read(self) -> dict:
        meta = load_json(self._path, {})
        return meta if isinstance(meta, dict) else {}

    def _write(self, meta: dict) -> None:
        try:
            save_json_atomic(self._path, meta)
        except OSError as exc:
            log_message(self._bridge,
                        f"⚠️ Workspace index not saved ({META_FILE}): {exc} — "
                        "the snapshot itself is fine; the recent list may be stale",
                        "warn")

    def record_snapshot(self, path: str) -> None:
        meta = self._read()
        recent = [p for p in meta.get("recent", []) if p != path]
        recent.insert(0, path)
        meta["recent"] = recent[:RECENT_CAP]
        meta["last_snapshot"] = {"path": path, "utc": utc_now_iso()}
        self._write(meta)

    def record_restore(self, root: str, result: str) -> None:
        meta = self._read()
        meta["last_restore"] = {"path": str(root), "utc": utc_now_iso(),
                                "result": result}
        self._write(meta)

    def recent(self, limit: int = RECENT_CAP) -> list:
        """Pure read: existing recent snapshots, missing filtered, no write."""
        meta = self._read()
        kept = [p for p in meta.get("recent", []) if Path(p).exists()]
        return kept[:max(1, int(limit))]

    def prune_missing(self) -> int:
        """Remove missing folders from the index file, return pruned count."""
        meta = self._read()
        recent = meta.get("recent", [])
        kept = [p for p in recent if Path(p).exists()]
        pruned = len(recent) - len(kept)
        if pruned:
            meta["recent"] = kept
            self._write(meta)
        return pruned

    def last_snapshot(self) -> str:
        meta = self._read()
        path = (meta.get("last_snapshot") or {}).get("path", "")
        return path if path and Path(path).exists() else ""

    def last_restore(self) -> dict:
        meta = self._read()
        return meta.get("last_restore") or {}


# ---- module-level wrappers for backward compat ----

def _meta_path(bridge) -> Path:
    return config_dir(bridge) / META_FILE


def _read_meta(bridge) -> dict:
    return SnapshotIndex(bridge)._read()


def _write_meta(bridge, meta: dict) -> None:
    SnapshotIndex(bridge)._write(meta)


def record_snapshot(bridge, path: str) -> None:
    SnapshotIndex(bridge).record_snapshot(path)


def record_restore(bridge, root: str, result: str) -> None:
    SnapshotIndex(bridge).record_restore(root, result)


def recent_snapshots(bridge, limit: int = RECENT_CAP) -> list:
    """Pure read (S4 fix) — missing folders filtered, no write side-effect.

    Call `prune_missing` explicitly when you want the file cleaned.
    """
    return SnapshotIndex(bridge).recent(limit)


def prune_missing(bridge) -> int:
    """Explicit prune command — removes missing folders from index file."""
    return SnapshotIndex(bridge).prune_missing()


def last_snapshot(bridge) -> str:
    return SnapshotIndex(bridge).last_snapshot()


def last_restore(bridge) -> dict:
    return SnapshotIndex(bridge).last_restore()
