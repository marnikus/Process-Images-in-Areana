# ideal-size: methods=14 reason=frozen JS layout/state surface; accessors serialize layout-owned grid/window/arena stores, splitting would scatter state serialization
"""Layout + state panel — grid/window presets and arena state accessors.

Mixin holds the 14 slots (thin where bodies exceed a few lines); document
shaping lives in `ui/services/window_preset_service.py`, state->JS mapping in
`ui/services/arena_serialize.py`. Imports go panels -> services/core only.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from app.core.layout_service import (
    WINDOW_IDS,
    canonical_grid_payload,
    default_payload,
)
from app.core.persistence import save_state
from app.ui.qt_compat import QFileDialog, Slot
from app.ui.services import arena_serialize as js
from app.ui.services import undo_entries
from app.ui.services import window_preset_service as presets

log = logging.getLogger("arena")


def save_arena_state(bridge) -> None:
    """Persist AppState, then re-emit (Bridge._save_arena delegates here)."""
    try:
        save_state(bridge.state, bridge.state_path)
        emit_arena_state(bridge)
    except Exception as e:
        log.error(f"Failed to save arena state: {e}")
        bridge.arena_log.emit(f"Failed to save state: {e}", "error")


def emit_arena_state(bridge) -> None:
    """Emit arena + progress payloads (Bridge._emit_arena_state delegates)."""
    try:
        js_state = js.arena_to_js(bridge.state)
        bridge.arena_state_updated.emit(json.dumps(js_state, ensure_ascii=False))
        prog = js_state.get("progress", {}).copy()
        prog["run_state"] = getattr(bridge, "_run_state", "idle")
        bridge.progress_updated.emit(json.dumps(prog, ensure_ascii=False))
    except Exception as e:
        log.warning(f"emit arena state failed: {e}")


def _write_preset_doc(path: Path, doc: dict) -> None:
    """Write one preset doc as indented JSON."""
    with path.open("w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)


def _read_preset_doc(file_path: str) -> dict:
    """Read one preset doc from disk."""
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def export_preset_file(bridge, name: str) -> str:
    """Write the stored preset doc to disk (dialog, else headless fallback)."""
    doc = bridge.config.window_presets.load_preset(name)
    if not doc:
        return json.dumps({"ok": False, "error": "not found"})
    try:
        if QFileDialog is None:
            path = Path("config") / f"{name}_window.json"
        else:
            folder = QFileDialog.getExistingDirectory(None, "Export window preset")
            if not folder:
                return json.dumps({"ok": False, "cancelled": True})
            path = Path(folder) / f"{name}.json"
        _write_preset_doc(path, doc)
        bridge._exported_paths[name] = str(path)
        bridge._log(f"Window preset exported to {path}", "success")
        return json.dumps({"ok": True, "path": str(path)})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


def _preset_grid_error(doc) -> Optional[str]:
    """Grid-payload validation error, or None when valid/absent."""
    payload = doc.get("grid", {}).get("payload")
    if payload:
        _, err = canonical_grid_payload(payload)
        if err:
            return f"invalid grid: {err}"
    return None


def import_preset_file(bridge) -> str:
    """Read a preset doc from disk after validating its grid payload."""
    try:
        if QFileDialog is None:
            return json.dumps({"ok": False, "error": "No file dialog in headless mode"})
        file_path, _ = QFileDialog.getOpenFileName(None, "Import window preset", "", "JSON (*.json)")
        if not file_path:
            return json.dumps({"ok": False, "cancelled": True})
        doc = _read_preset_doc(file_path)
        name = doc.get("name") or Path(file_path).stem
        err = _preset_grid_error(doc)
        if err:
            return json.dumps({"ok": False, "error": err})
        bridge.config.window_presets.save_preset(name, doc)
        bridge.list_window_presets()
        bridge._log(f"Window preset imported: {name}", "success")
        return json.dumps({"ok": True, "name": name})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


def _known_ids(items) -> list:
    """String items restricted to known window ids."""
    return [i for i in items if isinstance(i, str) and i in WINDOW_IDS]


def _window_filter(raw: dict) -> dict:
    """Closed/minimized lists restricted to known window ids."""
    closed = _known_ids(raw.get("closed", []))
    minimized = [i for i in _known_ids(raw.get("minimized", [])) if i not in closed]
    return {"closed": closed, "minimized": minimized}


class LayoutStateMixin:
    """Grid layout, window states/presets, app/arena state slots.

    ideal-size: 14 frozen JS slots; validate/wire helpers already live at
    module level — remaining per-slot bodies cannot move without
    scattering slot+helper pairs (R10.10).
    """

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
            undo_entries.emit_undo_state(self)
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
            undo_entries.emit_undo_state(self)
        except Exception:
            pass
        return payload

    @Slot(result=str)
    def get_window_states(self):
        raw = self.config.get_state("window_states", None)
        if not isinstance(raw, dict):
            return ""
        return json.dumps(_window_filter(raw), ensure_ascii=False)

    @Slot(str, result=bool)
    def save_window_states(self, states_json: str):
        try:
            data = json.loads(states_json or "{}")
        except json.JSONDecodeError:
            return False
        if not isinstance(data, dict):
            return False
        payload = _window_filter(data)
        self.config.set_state(window_states=payload)
        try:
            self.undo_service.push("window_states", payload)
            undo_entries.emit_undo_state(self)
        except Exception:
            pass
        return True

    @Slot(result=str)
    def list_window_presets(self):
        presets_list = self.config.window_presets.list_presets()
        payload = json.dumps(presets_list, ensure_ascii=False)
        self.window_preset_list_updated.emit(payload)
        return payload

    @Slot(str, str, result=str)
    def save_window_preset(self, name: str, grid_json: str):
        try:
            fallback = grid_json or self.get_grid_layout() or default_payload()
            stored_ws = self.config.get_state("window_states", {"closed": [], "minimized": []})
            doc, err = presets.save_preset_doc(name, grid_json, fallback, stored_ws)
            if err:
                return json.dumps({"ok": False, "error": err})
            self.config.window_presets.save_preset(name, doc)
            self.list_window_presets()
            count = doc.get("grid", {}).get("window_count", 0)
            self._log(f"Window preset saved: {name} ({count} windows)", "success")
            return json.dumps({"ok": True, "name": name})
        except Exception as e:
            import traceback
            traceback.print_exc()
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def load_window_preset(self, name: str):
        # Pure getter: returns the stored portable doc for the JS preview ->
        # confirm -> apply flow (no server-side apply; that would rearrange
        # the grid behind the preview modal before the user confirms).
        doc = self.config.window_presets.load_preset(name)
        payload, err = presets.load_preset_doc(doc, name)
        if err:
            return json.dumps({"ok": False, "error": err})
        self._log(f"Window preset loaded: {name}", "success")
        return payload

    @Slot(str, result=str)
    def delete_window_preset(self, name: str):
        ok = self.config.window_presets.delete_preset(name)
        if ok:
            self.list_window_presets()
            self._log(f"Window preset deleted: {name}", "info")
            return json.dumps({"ok": True})
        return json.dumps({"ok": False, "error": "not found"})

    @Slot(str, result=str)
    def export_window_preset(self, name: str):
        return export_preset_file(self, name)

    @Slot(result=str)
    def import_window_preset(self):
        return import_preset_file(self)

    @Slot(str, result=bool)
    def show_window_preset_in_folder(self, name: str):
        path = self._exported_paths.get(name) or str(self.config.window_presets.path)
        self._log(f"Preset folder: {path}", "info")
        return True

    @Slot(result=str)
    def get_app_state(self):
        theme = self.config.get_state("theme", "dark")
        grid_layout = self.config.get_state("grid_layout", None)
        window_states = self.config.get_state("window_states", None)
        hist, idx = self.undo_service.history()
        payload = {
            "theme": theme,
            "state": {
                "grid_layout": grid_layout,
                "window_states": window_states,
                "undo_history": hist,
                "undo_history_index": idx,
            }
        }
        return json.dumps(payload, ensure_ascii=False)

    @Slot(result=str)
    def get_arena_state(self):
        js_state = js.arena_to_js(self.state)
        return json.dumps(js_state, ensure_ascii=False)
