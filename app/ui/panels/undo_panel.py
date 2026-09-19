"""Undo Panel — Bridge panel mixin (W1.6 split)."""

from __future__ import annotations

import json
import logging
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

from app.core.layout_service import canonical_grid_payload, default_payload
from app.core.models import UrlRow

log = logging.getLogger("arena")


class UndoEditPanel:

    @Slot(str, str, result=bool)
    def push_global_history(self, kind: str, value_json: str):
        try:
            # parse value
            try:
                value = json.loads(value_json) if value_json else None
            except json.JSONDecodeError:
                # for grid, value_json is already canonical payload string; keep raw
                value = value_json
            # validate grid
            if kind == "grid":
                payload, err = canonical_grid_payload(value if isinstance(value, str) else json.dumps(value))
                if err:
                    return False
                value = payload
            # push
            self.undo_service.push(kind, value)
            self._remember_global_edit(kind, value)
            self._emit_undo_state()
            return True
        except Exception as e:
            log.warning(f"push_global_history failed: {e}")
            return False

    def _remember_global_edit(self, kind, value):
        """Apply a pushed global edit to live state (dispatch by kind)."""
        handler = _UNDO_REMEMBER_HANDLERS.get(kind)
        if handler is None:
            return  # unknown kinds are a silent no-op (characterized)
        try:
            handler(self, value)
        except Exception as e:
            log.warning(f"_remember_global_edit {kind} failed: {e}")

    def _remember_grid(self, value):
        self.config.set_state(grid_layout=value)
        self.grid_layout_changed.emit(value)
        self.grid_layout_persisted.emit(True)

    def _remember_window_states(self, value):
        if isinstance(value, dict):
            self.config.set_state(window_states=value)

    def _remember_urls(self, value):
        if isinstance(value, list):
            self.state.urls = _js_urls_to_rows(value)
            self._save_arena()

    def _remember_folder(self, value):
        if isinstance(value, dict):
            self.state.folder.update(value)
            self._save_arena()

    def _remember_queue(self, value):
        if isinstance(value, list):
            sel_map = {img.get("id"): img.get("selected") for img in value}
            for im in self.state.images:
                if im.id in sel_map:
                    im.selected = bool(sel_map[im.id])
            self.state.recalculate_progress()
            self._save_arena()

    def _remember_prompt(self, value):
        if isinstance(value, str):
            self.state.prompt["user_prompt"] = value
            self._save_arena()
        elif isinstance(value, dict):
            tmpl = value.get("template") or value.get("user_prompt") or ""
            self.state.prompt["user_prompt"] = tmpl
            self._save_arena()

    def _remember_settings(self, value):
        if isinstance(value, dict):
            self.state.settings.timeouts.update(value.get("timeouts", {}))
            self.state.settings.output.update(value.get("output", {}))
            self.state.settings.highlight.update(value.get("highlight", {}))
            if "supported_types" in value:
                self.state.folder["supported_types"] = value["supported_types"]
            self._save_arena()

    def _remember_action_blocks(self, value):
        if isinstance(value, list):
            try:
                self.config.set_state(action_blocks=value)
                self.action_blocks_updated.emit(json.dumps(value, ensure_ascii=False))
                self._log(f"↩ Remember action_blocks ({len(value)} blocks)", "info")
            except Exception as e:
                log.warning(f"remember action_blocks failed: {e}")

    def _remember_arena(self, value):
        if isinstance(value, dict):
            try:
                if isinstance(value.get("urls"), list) and value["urls"] and "url" in value["urls"][0]:
                    self.state.urls = [UrlRow(
                        id=u.get("id"), url=u.get("url"), enabled=u.get("enabled", True),
                        last_status=u.get("status", "unchecked"), error=u.get("last_error")
                    ) for u in value["urls"]]
                if "folder" in value:
                    self.state.folder.update(value["folder"])
                if "prompt" in value:
                    tmpl = value["prompt"].get("template") if isinstance(value["prompt"], dict) else value["prompt"]
                    if tmpl:
                        self.state.prompt["user_prompt"] = tmpl
                self.state.recalculate_progress()
                self._save_arena()
            except Exception as e:
                log.warning(f"remember arena edit failed: {e}")


class UndoApplyPanel:

    def _apply_undo_entry(self, entry):
        """Apply one undo entry to live state (dispatch by kind)."""
        if not entry or not isinstance(entry, dict):
            return False
        kind = entry.get("kind")
        value = entry.get("value")
        try:
            handler = _UNDO_APPLY_HANDLERS.get(kind)
            if handler is None:
                self._log(f"↩ Undo {kind} (no specific handler)", "info")
            else:
                handler(self, value)
            return True
        except Exception as e:
            log.warning(f"_apply_undo_entry {kind} failed: {e}")
            return False

    def _apply_grid(self, value):
        if isinstance(value, str):
            self.config.set_state(grid_layout=value)
            self.grid_layout_changed.emit(value)
            self.grid_layout_persisted.emit(True)
            self._log(f"↩ Undo grid layout", "info")

    def _apply_window_states(self, value):
        if isinstance(value, dict):
            self.config.set_state(window_states=value)
            self._log(f"↩ Undo window states", "info")

    def _apply_urls(self, value):
        if isinstance(value, list):
            self.state.urls = _js_urls_to_rows(value)
            self._save_arena()
            self._log(f"↩ Undo URLs ({len(value)} items)", "info")

    def _apply_folder(self, value):
        if isinstance(value, dict):
            self.state.folder = value
            self._save_arena()
            self._log(f"↩ Undo folder", "info")

    def _apply_queue(self, value):
        if isinstance(value, list):
            sel_map = {img.get("id"): img for img in value}
            for im in self.state.images:
                if im.id in sel_map:
                    js = sel_map[im.id]
                    im.selected = bool(js.get("selected", im.selected))
                    im.status = js.get("status", im.status)
            self.state.recalculate_progress()
            self._save_arena()
            self._log(f"↩ Undo queue selection", "info")

    def _apply_prompt(self, value):
        tmpl = value if isinstance(value, str) else (value.get("template") if isinstance(value, dict) else "")
        self.state.prompt["user_prompt"] = tmpl
        self._save_arena()
        self._log(f"↩ Undo prompt", "info")

    def _apply_settings(self, value):
        if isinstance(value, dict):
            for key in ("timeouts", "output", "highlight"):
                if key in value:
                    getattr(self.state.settings, key).update(value[key])
            if "supported_types" in value:
                self.state.folder["supported_types"] = value["supported_types"]
                self.state.settings.supported_types = value["supported_types"]
            self._save_arena()
            self._log(f"↩ Undo settings", "info")

    def _apply_action_blocks(self, value):
        # NOTE: historically the first of two duplicated elif branches ran
        # here and logged "Remember action_blocks" — quirk kept (characterized).
        if isinstance(value, list):
            try:
                self.config.set_state(action_blocks=value)
                self.action_blocks_updated.emit(json.dumps(value, ensure_ascii=False))
                self._log(f"↩ Remember action_blocks ({len(value)} blocks)", "info")
            except Exception as e:
                log.warning(f"apply action_blocks undo failed: {e}")

    def _apply_arena(self, value):
        if isinstance(value, dict):
            try:
                if "urls" in value:
                    self.state.urls = [UrlRow(
                        id=u.get("id"), url=u.get("url"), enabled=u.get("enabled", True),
                        last_status=u.get("status", "unchecked"), error=u.get("last_error")
                    ) for u in value["urls"]]
                if "folder" in value:
                    self.state.folder.update(value["folder"])
                if "prompt" in value:
                    tmpl = value["prompt"].get("template") if isinstance(value["prompt"], dict) else str(value["prompt"])
                    self.state.prompt["user_prompt"] = tmpl
                self.state.recalculate_progress()
                self._save_arena()
                self._log(f"↩ Undo arena snapshot", "info")
            except Exception as e:
                log.warning(f"apply arena undo failed: {e}")


class UndoApiPanel:

    @Slot(result=str)
    def undo(self):
        result = self.undo_service.undo()
        if not result:
            self._log("⚠ Nothing to undo", "warn")
            self._emit_undo_state()
            return "null"
        hist, idx = self.undo_service.history()
        if idx == -1:
            self._undo_to_empty(result)
        else:
            current_entry = hist[idx] if 0 <= idx < len(hist) else None
            self._apply_undo_entry(current_entry or result)
        self._emit_undo_state()
        return json.dumps(result, ensure_ascii=False)

    def _undo_to_empty(self, result):
        """Undo past the start: restore default/empty for the undone kind."""
        undone = result.get("undone") or result
        undone_kind = (undone.get("kind") if isinstance(undone, dict) else None) or result.get("kind")
        try:
            handler = _UNDO_EMPTY_HANDLERS.get(undone_kind)
            if handler is not None:
                handler(self, undone_kind)
            else:
                self._undo_empty_log_only(undone_kind or result.get("kind"))
        except Exception as e:
            log.warning(f"undo empty handling failed: {e}")

    def _undo_empty_grid(self, _kind=None):
        payload = default_payload()
        self.config.set_state(grid_layout=payload)
        self.grid_layout_changed.emit(payload)
        self.grid_layout_persisted.emit(True)
        self._log("↩ Undo grid → default", "info")

    def _undo_empty_window_states(self, _kind=None):
        empty_ws = {"closed": [], "minimized": []}
        self.config.set_state(window_states=empty_ws)
        self._log("↩ Undo window states → empty", "info")

    def _undo_empty_urls(self, _kind=None):
        self.state.urls = []
        self._save_arena()
        self._log("↩ Undo urls → empty", "info")

    def _undo_empty_folder(self, _kind=None):
        self.state.folder = {"root_path": "", "supported_types": [".png", ".jpg", ".jpeg", ".webp"], "ignore_ai_suffix": True}
        self._save_arena()
        self._log("↩ Undo folder → empty", "info")

    def _undo_empty_prompt(self, _kind=None):
        self.state.prompt["user_prompt"] = ""
        self._save_arena()
        self._log("↩ Undo prompt → empty", "info")

    def _undo_empty_log_only(self, kind=None):
        """queue/settings/unknown kinds: nothing to reset, just report."""
        self._log(f"↩ Undo {kind} → empty", "info")


    @Slot(result=str)
    def redo(self):
        result = self.undo_service.redo()
        if not result:
            self._log("⚠ Nothing to redo", "warn")
            self._emit_undo_state()
            return "null"
        self._apply_undo_entry(result)
        self._emit_undo_state()
        self._log(f"↪ Redo {result.get('kind')}", "success")
        return json.dumps(result, ensure_ascii=False)

    @Slot(result=str)
    def get_undo_history(self):
        hist, idx = self.undo_service.history()
        return json.dumps({"history": hist, "index": idx}, ensure_ascii=False)

    def _emit_undo_state(self):
        try:
            hist, idx = self.undo_service.history()
            can_undo = idx >= 0
            can_redo = idx < len(hist) - 1
            payload = json.dumps({
                "history": hist,
                "index": idx,
                "canUndo": can_undo,
                "canRedo": can_redo,
                "count": len(hist),
            }, ensure_ascii=False)
            self.undo_state_changed.emit(payload)
            self.history_changed.emit()
        except Exception as e:
            log.warning(f"emit undo state failed: {e}")


# ── module-level helpers ──

def _js_urls_to_rows(value):
    """JS url dicts -> UrlRow list (urls-kind shape: default ids, error fallback)."""
    return [UrlRow(
        id=u.get("id", f"url_{i}"),
        url=u.get("url", ""),
        enabled=u.get("enabled", True),
        last_status=u.get("status", "unchecked"),
        last_checked=u.get("last_checked"),
        error=u.get("last_error") or u.get("error")
    ) for i, u in enumerate(value)]

_UNDO_REMEMBER_HANDLERS = {
    "grid": UndoEditPanel._remember_grid, "window_states": UndoEditPanel._remember_window_states,
    "urls": UndoEditPanel._remember_urls, "folder": UndoEditPanel._remember_folder,
    "queue": UndoEditPanel._remember_queue, "prompt": UndoEditPanel._remember_prompt,
    "settings": UndoEditPanel._remember_settings, "action_blocks": UndoEditPanel._remember_action_blocks,
    "arena": UndoEditPanel._remember_arena,
}

_UNDO_APPLY_HANDLERS = {
    "grid": UndoApplyPanel._apply_grid, "window_states": UndoApplyPanel._apply_window_states,
    "urls": UndoApplyPanel._apply_urls, "folder": UndoApplyPanel._apply_folder,
    "queue": UndoApplyPanel._apply_queue, "prompt": UndoApplyPanel._apply_prompt,
    "settings": UndoApplyPanel._apply_settings, "action_blocks": UndoApplyPanel._apply_action_blocks,
    "arena": UndoApplyPanel._apply_arena,
}


# Undo-to-empty dispatch (W1.6): kind -> unbound handler on UndoApiPanel.
_UNDO_EMPTY_HANDLERS = {
    "grid": UndoApiPanel._undo_empty_grid,
    "window_states": UndoApiPanel._undo_empty_window_states,
    "urls": UndoApiPanel._undo_empty_urls,
    "folder": UndoApiPanel._undo_empty_folder,
    "queue": UndoApiPanel._undo_empty_log_only,
    "prompt": UndoApiPanel._undo_empty_prompt,
    "settings": UndoApiPanel._undo_empty_log_only,
}
