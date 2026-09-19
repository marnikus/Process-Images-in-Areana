"""Folder Panel — Bridge panel mixin (W1.6 split)."""

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

from app.core.models import ImageItem



class FolderScanPanel:

    def _push_folder_undo(self):
        try:
            self.undo_service.push("folder", self.state.folder.copy())
            self._emit_undo_state()
        except Exception:
            pass

    @Slot(str, result=str)
    def pick_folder(self, start_dir: str):
        if QFileDialog is None:
            return json.dumps({"ok": False, "error": "No file dialog"})
        start = (start_dir or "").strip()
        if not start or not Path(start).is_dir():
            last = (self.state.folder.get("root_path", "") or "").strip()
            start = last if last and Path(last).is_dir() else ""
        folder = QFileDialog.getExistingDirectory(None, "Select image folder", start)
        if not folder:
            return json.dumps({"ok": False, "cancelled": True})
        self.state.folder["root_path"] = folder
        self._save_arena()
        self._push_folder_undo()
        return json.dumps({"ok": True, "path": folder})

    @Slot(str, result=str)
    def set_folder_path(self, path: str):
        p = Path(path)
        if not p.exists() or not p.is_dir():
            return json.dumps({"ok": False, "error": "Folder does not exist"})
        self.state.folder["root_path"] = str(p)
        self._save_arena()
        self._push_folder_undo()
        return json.dumps({"ok": True, "path": str(p)})

    @Slot(result=str)
    def scan_folder(self):
        """Non-blocking scan to avoid UI freeze on mouse clicks."""
        if getattr(self, '_scan_in_progress', False):
            return json.dumps({"ok": False, "pending": True, "error": "scan already in progress"})
        root_path, err = self._scan_root_or_error()
        if err:
            return json.dumps(err)
        from .services.scan_service import scan_folder_pure
        try:
            job = lambda: self._scan_merge_job(scan_folder_pure, root_path)  # noqa: E731
            self._submit_scan_job(job, f"🔍 Scanning folder {root_path}… (non-blocking)")
            return json.dumps({"ok": True, "pending": True, "count": 0, "message": "scan started non-blocking"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def scan_folder_new_batch(self):
        """Clear queue then scan — non-blocking to avoid freeze."""
        try:
            try:
                self._push_queue_undo()
            except Exception:
                pass
            cleared = self._clear_queue_for_new_batch()
            root_path, err = self._scan_root_or_error()
            if err:
                err["cleared"] = cleared
                return json.dumps(err)
            from .services.scan_service import scan_folder_pure
            job = lambda: self._scan_new_batch_job(scan_folder_pure, root_path, cleared)  # noqa: E731
            self._submit_scan_job(job)
            return json.dumps({"ok": True, "pending": True, "cleared": cleared, "message": "new batch scan started non-blocking"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def _scan_root_or_error(self):
        """Validate state folder root -> (Path, None) or (None, error dict)."""
        root = self.state.folder.get("root_path", "")
        if not root:
            return None, {"ok": False, "error": "No folder set"}
        root_path = Path(root)
        if not root_path.exists():
            return None, {"ok": False, "error": "Folder does not exist"}
        return root_path, None

    def _scan_filters(self):
        """(supported extensions set, ignore_ai_suffix) from state."""
        supported = set(self.state.folder.get("supported_types", [".png", ".jpg", ".jpeg", ".webp"]))
        ignore_ai = self.state.folder.get("ignore_ai_suffix", True)
        return supported, ignore_ai

    def _submit_scan_job(self, job, start_log=None):
        """Run scan job in the thumb executor (or a daemon thread)."""
        self._scan_in_progress = True
        if start_log:
            self._log(start_log, "info")
        if self._thumb_executor:
            self._thumb_executor.submit(job)
        else:
            import threading
            threading.Thread(target=job, daemon=True).start()

    def _scan_merge_job(self, scan_fn, root_path):
        """Worker: merge-scanned (keeps existing rows) — thread body."""
        try:
            supported, ignore_ai = self._scan_filters()
            scanned = scan_fn(root_path, supported, ignore_ai)
            added = self._merge_scanned(scanned)
            self.state.recalculate_progress()
            self._save_arena()
            self._log(f"Scanned {len(scanned)} images, {added} new", "success")
        except Exception as e:
            self._log(f"Scan failed: {e}", "error")
        finally:
            self._scan_in_progress = False

    def _scan_new_batch_job(self, scan_fn, root_path, cleared):
        """Worker: fresh queue after clear — thread body."""
        try:
            supported, ignore_ai = self._scan_filters()
            scanned = scan_fn(root_path, supported, ignore_ai)
            for sc in scanned:
                self.state.images.append(ImageItem.from_scan_dict(sc, selected=False))
            self.state.recalculate_progress()
            self._save_arena()
            self._log(f"🗑 New batch: cleared {cleared} old, scanned {len(scanned)} new images", "warn")
        except Exception as e:
            self._log(f"New batch scan failed: {e}", "error")
        finally:
            self._scan_in_progress = False

    def _merge_scanned(self, scanned) -> int:
        """Merge scan dicts into the queue; returns added count."""
        existing = {img.relative_path: img for img in self.state.images}
        added = 0
        for s in scanned:
            rel = s["relative_path"]
            if rel not in existing:
                self.state.images.append(ImageItem.from_scan_dict(s, selected=False))
                added += 1
            else:
                e = existing[rel]
                e.size = s["size"]
                e.mtime = s["mtime"]
                e.absolute_path = s["absolute_path"]
        return added
