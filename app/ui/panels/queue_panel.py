"""Queue Panel — Bridge panel mixin (W1.6 split)."""

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




class QueuePanel:

    @Slot(result=str)
    def retry_failed(self):
        count = 0
        for img in self.state.images:
            if img.status == "failed":
                img.status = "pending"
                img.selected = True
                img.error = None
                count += 1
        self.state.recalculate_progress()
        self._save_arena()
        self._push_queue_undo()
        return json.dumps({"ok": True, "count": count})

    @Slot(result=str)
    def clear_queue(self):
        """Clear entire image queue — start new batch. User requested: should able to start new batch not adding only."""
        try:
            count = len(self.state.images)
            # push undo before clearing so user can undo
            try:
                self._push_queue_undo()
            except Exception:
                pass
            self.state.images = []
            self.state.jobs = []
            self.state.recalculate_progress()
            self._save_arena()
            self._log(f"🗑 Cleared image queue: {count} images removed — ready for new batch", "warn")
            return json.dumps({"ok": True, "count": count})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def clear_images(self):
        # alias for clear_queue for compatibility
        return self.clear_queue()

    @Slot(result=str)
    def drop_ai_suffix(self):
        """Drop _AI: strip the suffix from filenames in the picker folder."""
        return self._run_folder_ai("strip")

    @Slot(result=str)
    def keep_only_ai_files(self):
        """Only _AI: delete non-_AI images in the picker folder."""
        return self._run_folder_ai("only")

    @Slot(result=str)
    def reset_all(self):
        for img in self.state.images:
            img.status = "pending"
            img.selected = False
            img.error = None
            img.output_path = None
            img.assigned_url_id = None
            img.attempt_count = 0
        self.state.jobs = []
        self.state.recalculate_progress()
        self._save_arena()
        self._push_queue_undo()
        return json.dumps({"ok": True})

    @Slot(str, result=str)
    def retry_image(self, img_id: str):
        for img in self.state.images:
            if img.id == img_id:
                img.status = "pending"
                img.selected = True
                img.error = None
                self.state.recalculate_progress()
                self._save_arena()
                self._push_queue_undo()
                return json.dumps({"ok": True})
        return json.dumps({"ok": False, "error": "not found"})

    @Slot(str, result=str)
    def reset_image(self, img_id: str):
        for img in self.state.images:
            if img.id == img_id:
                img.status = "pending"
                img.selected = False
                img.error = None
                img.output_path = None
                img.assigned_url_id = None
                img.attempt_count = 0
                self.state.recalculate_progress()
                self._save_arena()
                self._push_queue_undo()
                return json.dumps({"ok": True})
        return json.dumps({"ok": False, "error": "not found"})

    def _drop_missing_queue_images(self, root_path, deleted) -> None:
        """Forget queue entries whose files were deleted."""
        try:
            gone = {str(Path(root_path, r).resolve()) for r in deleted}
            self.state.images = [i for i in self.state.images if i.absolute_path not in gone]
        except Exception:
            pass

    def _rename_queue_images(self, root_path, pairs) -> None:
        """Point queue entries at renamed files (stats preserved)."""
        try:
            from app.utils.hashing import fingerprint_from_path_stat
            by_old = {str(Path(root_path, old).resolve()): new for old, new in pairs}
            for img in self.state.images:
                new_rel = by_old.get(img.absolute_path)
                if not new_rel:
                    continue
                img.relative_path = new_rel
                img.absolute_path = str(Path(root_path, new_rel).resolve())
                img.filename = Path(new_rel).name
                img.base_name = Path(new_rel).stem
                img.fingerprint = fingerprint_from_path_stat(new_rel, img.size, img.mtime)
        except Exception:
            pass


class QueueSelectionPanel:
    """Queue selection ops (single/bulk + undo push) — W1.6 split."""

    def _push_queue_undo(self):
        try:
            js_images = self._arena_to_js()["images"]
            self.undo_service.push("queue", js_images)
            self._emit_undo_state()
        except Exception:
            pass

    @Slot(str, bool, result=str)
    def set_image_selected(self, img_id: str, selected: bool):
        for img in self.state.images:
            if img.id == img_id:
                img.selected = bool(selected)
                if selected and img.status == "skipped":
                    img.status = "pending"
                self.state.recalculate_progress()
                self._save_arena()
                self._push_queue_undo()
                return json.dumps({"ok": True})
        return json.dumps({"ok": False, "error": "not found"})

    @Slot(bool, str, result=str)
    def bulk_select(self, selected: bool, filter_status: str):
        count = 0
        for img in self.state.images:
            if filter_status == "all" or img.status == filter_status:
                img.selected = bool(selected)
                count += 1
        self.state.recalculate_progress()
        self._save_arena()
        self._push_queue_undo()
        return json.dumps({"ok": True, "count": count})

    def _clear_queue_for_new_batch(self) -> int:
        """Drop images+jobs for a new batch; returns cleared image count."""
        cleared = len(self.state.images)
        self.state.images = []
        self.state.jobs = []
        self.state.recalculate_progress()
        self._save_arena()
        self._log(f"🗑 Cleared {cleared} old — scanning new batch non-blocking", "warn")
        return cleared
