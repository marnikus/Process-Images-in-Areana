# ideal-size: ~170 lines reason=dialog strategies must be read as one ordered
# fallback chain; separating them hides the ordering (RULE 18.2)
"""Folder Browse — restores the native folder dialog (BUG 03.4).

Root cause
----------
`queue_scan.pick_folder()` called:

    QFileDialog.getExistingDirectory(None, "Select image folder", start)

Three ways that produces "the Browse button does nothing":

1. `parent=None` — with a QWebEngineView focused, a parentless modal can open
   **behind** the main window, or not raise at all on Windows.
2. `qt_compat.QFileDialog` is `None` whenever the PySide6 import failed; the
   slot returned `{"ok": false, "error": "No file dialog"}` and the JS
   `_onPickFolder` only wrote to the log console — invisible to the user.
3. The native dialog blocks the Qt event loop while QWebChannel is waiting
   for the slot's return value.

Fix
---
* Resolve a **real parent window** (active window -> main window -> any
  top-level) before opening the dialog.
* Ordered strategy chain: native Qt dialog -> Qt non-native dialog
  (`DontUseNativeDialog`, survives broken shell handlers) -> explicit error.
* Never return a bare `{"ok": false}`: always carry a human `error` the JS
  layer shows as a toast, not just a log line.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

from app.ui.qt_compat import QFileDialog

log = logging.getLogger("arena")

DIALOG_TITLE = "Select image folder"


def resolve_start_dir(folder_state: dict | None, requested: str) -> str:
    """First existing path of: typed value -> saved root -> home."""
    for candidate in ((requested or "").strip(),
                      (folder_state or {}).get("root_path", "")):
        if candidate and Path(candidate).is_dir():
            return str(Path(candidate))
    return str(Path.home())


def _top_level_parent() -> Any:
    """A real window to own the modal (None only when Qt is absent)."""
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return None
    app = QApplication.instance()
    if app is None:
        return None
    win = app.activeWindow()
    if win is not None:
        return win
    tops = [w for w in app.topLevelWidgets() if w.isVisible()]
    return tops[0] if tops else None


def _native(parent: Any, start: str) -> str:
    return QFileDialog.getExistingDirectory(
        parent, DIALOG_TITLE, start, QFileDialog.ShowDirsOnly)


def _non_native(parent: Any, start: str) -> str:
    options = QFileDialog.ShowDirsOnly | QFileDialog.DontUseNativeDialog
    return QFileDialog.getExistingDirectory(parent, DIALOG_TITLE, start, options)


STRATEGIES: tuple[tuple[str, Callable[[Any, str], str]], ...] = (
    ("native", _native),
    ("qt", _non_native),
)


def open_folder_dialog(start: str, logger: Callable | None = None) -> dict:
    """Run the strategy chain. Returns {ok|cancelled|error, path, via}."""
    say = logger or (lambda msg, level="info": log.info(msg))
    if QFileDialog is None:
        return {"ok": False, "error": "Qt file dialog unavailable — type the "
                                      "folder path into the field and press Enter"}
    parent = _top_level_parent()
    last_error = ""
    for name, strategy in STRATEGIES:
        try:
            chosen = strategy(parent, start)
        except Exception as exc:  # noqa: BLE001 - try the next strategy
            last_error = f"{name}: {exc}"
            say(f"Folder dialog ({name}) failed: {exc}", "warn")
            continue
        if chosen:
            return {"ok": True, "path": str(Path(chosen)), "via": name}
        return {"ok": False, "cancelled": True, "via": name}
    return {"ok": False, "error": last_error or "no dialog strategy succeeded"}


def apply_folder_choice(bridge, path: str) -> dict:
    """Persist a chosen/typed folder; single write path for both entries."""
    p = Path(path).expanduser()
    if not p.is_dir():
        return {"ok": False, "error": f"Folder does not exist: {p}"}
    bridge.state.folder["root_path"] = str(p)
    bridge._save_arena()
    return {"ok": True, "path": str(p)}


class FolderBrowseMixin:
    """Slots — wrap with `@Slot(str, result=str)` in the Bridge class body."""

    def pick_folder(self, start_dir: str = "") -> str:
        import json
        start = resolve_start_dir(getattr(self, "state", None)
                                  and self.state.folder, start_dir)
        result = open_folder_dialog(start, self._log)
        if not result.get("ok"):
            if result.get("cancelled"):
                self._log("Folder pick cancelled", "info")
            else:
                self._log(f"❌ Browse failed: {result.get('error')}", "error")
            return json.dumps(result)
        applied = apply_folder_choice(self, result["path"])
        if applied.get("ok"):
            self._log(f"📁 Folder selected: {applied['path']}", "success")
        return json.dumps({**result, **applied})

    def set_folder_path(self, path: str) -> str:
        import json
        applied = apply_folder_choice(self, path)
        level = "success" if applied.get("ok") else "error"
        self._log(f"📁 Folder path: {applied.get('path') or applied.get('error')}", level)
        return json.dumps(applied)
