"""Folder Ai Panel — Bridge panel mixin (W1.6 split)."""

from __future__ import annotations

import json
from pathlib import Path
try:
    from PySide6.QtCore import QObject, Signal, Slot
    _qt_core = True
except ImportError:
    _qt_core = False

if not _qt_core:  # headless shim (no PySide6) — exercised by tests/test_qt_shim_fallback.py
    class QObject:
        def __init__(self, *qt_shim_args, **qt_shim_kwargs): pass

    def Signal(*sig_shim_args, **sig_shim_kwargs):
        class _Sig:
            def emit(self, *emit_shim_args, **emit_shim_kwargs): pass
            def connect(self, *connect_shim_args, **connect_shim_kwargs): pass
        return _Sig()

    def Slot(*slot_shim_args, **slot_shim_kwargs):
        def deco(fn): return fn
        return deco

try:
    from PySide6.QtWidgets import QFileDialog
except ImportError:
    QFileDialog = None




class FolderAiPanel:

    def _run_folder_ai(self, mode: str) -> str:
        """Disk _AI op on the picker folder; refuses mid-run. Pending JSON."""
        if getattr(self, "_run_state", "idle") != "idle":
            return json.dumps({"ok": False, "error": "stop the run first"})
        if getattr(self, '_scan_in_progress', False):
            return json.dumps({"ok": False, "pending": True, "error": "scan already in progress"})
        root = self.state.folder.get("root_path", "")
        if not root:
            return json.dumps({"ok": False, "error": "No folder set"})
        root_path = Path(root)
        if not root_path.exists():
            return json.dumps({"ok": False, "error": "Folder does not exist"})
        try:
            self._scan_in_progress = True
            self._log(f"Folder {'Only _AI' if mode == 'only' else 'Drop _AI'} in {root_path}...", "warn")
            self._submit_folder_ai(root_path, set(self.state.folder.get("supported_types", [".png", ".jpg", ".jpeg", ".webp"])), mode)
        except Exception as e:
            self._scan_in_progress = False
            return json.dumps({"ok": False, "error": str(e)})
        return json.dumps({"ok": True, "pending": True})

    def _submit_folder_ai(self, root_path, exts, mode) -> None:
        """Run the folder _AI worker off the UI thread."""
        if self._thumb_executor:
            self._thumb_executor.submit(self._folder_ai_worker, root_path, exts, mode)
        else:
            import threading
            threading.Thread(target=self._folder_ai_worker, args=(root_path, exts, mode), daemon=True).start()

    def _folder_ai_worker(self, root_path, exts, mode) -> None:
        """Rename/delete _AI files on disk, sync queue. Off UI thread."""
        try:
            from app.core.folder_ai import delete_non_ai_images, strip_ai_suffixes
            if mode == "only":
                deleted, errors = delete_non_ai_images(root_path, exts)
                self._drop_missing_queue_images(root_path, deleted)
                self._log(f"Only _AI: deleted {len(deleted)} files from {root_path}", "warn")
            else:
                pairs, skipped, errors = strip_ai_suffixes(root_path, exts)
                self._rename_queue_images(root_path, pairs)
                self._log(f"Drop _AI: renamed {len(pairs)}, skipped {skipped} in {root_path}", "warn")
            for err in errors[:3]:
                self._log(str(err), "warn")
            self.state.recalculate_progress()
            self._save_arena()
        except Exception as e:
            self._log(f"Folder _AI op failed: {e}", "error")
        finally:
            self._scan_in_progress = False
