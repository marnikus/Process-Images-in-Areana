"""Grid Layout Panel — Bridge panel mixin (W1.6 split)."""

from __future__ import annotations

import json
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

from app.core.layout_service import WINDOW_IDS, canonical_grid_payload, default_payload



class GridLayoutPanel:

    @Slot(str, result=bool)
    def set_theme(self, theme: str):
        self.config.set_state(theme=theme)
        self._log(f"Theme set to {theme}", "info")
        return True

    @Slot(result=str)
    def get_grid_layout(self):
        raw = self.config.get_state("grid_layout", None)
        if not isinstance(raw, str) or not raw:
            return ""
        payload, err = canonical_grid_payload(raw)
        return payload if not err else ""

    @Slot(str, result=bool)
    def save_grid_layout(self, layout_json: str):
        payload, err = canonical_grid_payload(layout_json or "")
        if err:
            self._log(f"Grid layout rejected: {err}", "warn")
            self.grid_layout_persisted.emit(False)
            return False
        self.config.set_state(grid_layout=payload)
        self.grid_layout_changed.emit(payload)
        self.grid_layout_persisted.emit(True)
        try:
            self.undo_service.push("grid", payload)
            self._emit_undo_state()
        except Exception:
            pass
        return True

    @Slot(result=str)
    def reset_grid_layout(self):
        payload = default_payload()
        self.config.set_state(grid_layout=payload, window_states={"closed": [], "minimized": []})
        self.grid_layout_changed.emit(payload)
        self.grid_layout_persisted.emit(True)
        self._log("Grid layout reset to default", "info")
        try:
            self.undo_service.push("grid", payload)
            self.undo_service.push("window_states", {"closed": [], "minimized": []})
            self._emit_undo_state()
        except Exception:
            pass
        return payload

    @Slot(result=str)
    def undo_grid_layout(self):
        raw = self.undo()
        try:
            result = json.loads(raw)
            if isinstance(result, dict) and result.get("kind") == "grid":
                return result.get("value") or "null"
            return "null"
        except Exception:
            return "null"

    @Slot(result=str)
    def redo_grid_layout(self):
        raw = self.redo()
        try:
            result = json.loads(raw)
            if isinstance(result, dict) and result.get("kind") == "grid":
                return result.get("value") or "null"
            return "null"
        except Exception:
            return "null"

    @Slot(result=str)
    def get_window_states(self):
        raw = self.config.get_state("window_states", None)
        if not isinstance(raw, dict):
            return ""
        closed = [i for i in raw.get("closed", []) if isinstance(i, str) and i in WINDOW_IDS]
        minimized = [i for i in raw.get("minimized", []) if isinstance(i, str) and i in WINDOW_IDS and i not in closed]
        return json.dumps({"closed": closed, "minimized": minimized}, ensure_ascii=False)

    @Slot(str, result=bool)
    def save_window_states(self, states_json: str):
        try:
            data = json.loads(states_json or "{}")
        except json.JSONDecodeError:
            return False
        if not isinstance(data, dict):
            return False
        closed = [i for i in data.get("closed", []) if isinstance(i, str) and i in WINDOW_IDS]
        minimized = [i for i in data.get("minimized", []) if isinstance(i, str) and i in WINDOW_IDS and i not in closed]
        payload = {"closed": closed, "minimized": minimized}
        self.config.set_state(window_states=payload)
        try:
            self.undo_service.push("window_states", payload)
            self._emit_undo_state()
        except Exception:
            pass
        return True

    @Slot(result=str)
    def list_window_presets(self):
        presets = self.config.window_presets.list_presets()
        payload = json.dumps(presets, ensure_ascii=False)
        self.window_preset_list_updated.emit(payload)
        return payload
