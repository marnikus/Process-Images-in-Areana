"""Folder pick slots — `pick_folder` / `set_folder_path` (mixed into QueueScanMixin).

2026-10-02 bugfix: `state.folder` is a plain dict by contract, but a legacy
`arena.json` / imported preset could carry `"folder": null` or a bare path
string. The old slots did `self.state.folder["root_path"] = …` and raised
inside the QWebChannel call — no reply, no log, a Browse button that
"does nothing". `as_folder_dict` normalises every shape first and both
slots always return JSON.

Imports go panels -> services/core only (Qt via qt_compat).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from app.ui.qt_compat import QFileDialog, Slot
from app.ui.services import undo_entries

DEFAULT_TYPES = [".png", ".jpg", ".jpeg", ".webp"]


def as_folder_dict(value: Any) -> Dict[str, Any]:
    """dict → copy with defaults filled; str → {root_path}; anything else → empty folder."""
    base: Dict[str, Any] = {"root_path": "", "supported_types": list(DEFAULT_TYPES), "ignore_ai_suffix": True}
    if isinstance(value, dict):
        base.update(value)
        base["root_path"] = str(base.get("root_path") or "")
        return base
    if isinstance(value, str):
        base["root_path"] = value.strip()
    return base


def ensure_folder_dict(bridge) -> Dict[str, Any]:
    """Normalise `bridge.state.folder` in place and return it."""
    folder = getattr(bridge.state, "folder", None)
    if not isinstance(folder, dict):
        folder = as_folder_dict(folder)
        bridge.state.folder = folder
    return folder


def resolve_pick_start(folder, start_dir: str) -> str:
    """Dialog seed: explicit dir, else last root, else ""."""
    start = (start_dir or "").strip()
    if not start or not Path(start).is_dir():
        last = (as_folder_dict(folder).get("root_path", "") or "").strip()
        start = last if last and Path(last).is_dir() else ""
    return start


def push_folder_undo(bridge) -> None:
    """Snapshot folder config to undo (best effort)."""
    try:
        snapshot = dict(ensure_folder_dict(bridge))
        bridge.undo_service.push("folder", snapshot)
        undo_entries.emit_undo_state(bridge)
    except Exception:
        pass


def commit_folder(bridge, path: str) -> str:
    """The ONE write path for the folder root: normalise, persist, emit, undo → JSON."""
    folder = ensure_folder_dict(bridge)
    folder["root_path"] = str(path)
    bridge._save_arena()
    push_folder_undo(bridge)
    return json.dumps({"ok": True, "path": str(path), "folder": folder}, ensure_ascii=False)


class FolderPickMixin:
    """Folder root slots; QueueScanMixin inherits these (packing: 2 slots)."""

    @Slot(str, result=str)
    def pick_folder(self, start_dir: str):
        try:
            if QFileDialog is None:
                return json.dumps({"ok": False, "error": "No file dialog"})
            start = resolve_pick_start(getattr(self.state, "folder", None), start_dir)
            folder = QFileDialog.getExistingDirectory(None, "Select image folder", start)
            if not folder:
                return json.dumps({"ok": False, "cancelled": True})
            return commit_folder(self, folder)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def set_folder_path(self, path: str):
        try:
            raw = (path or "").strip()
            p = Path(raw) if raw else None
            if p is None or not p.exists() or not p.is_dir():
                return json.dumps({"ok": False, "error": "Folder does not exist"})
            return commit_folder(self, str(p))
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})
