"""Window Preset Panel — Bridge panel mixin (W1.6 split)."""

from __future__ import annotations

import json
from datetime import datetime
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

from app.core.layout_service import GRID_VERSION, canonical_grid_payload, default_payload, leaf_ids



class WindowPresetIoPanel:

    @Slot(str, str, result=str)
    def save_window_preset(self, name: str, grid_json: str):
        try:
            tree, payload, ws, incoming, err = self._parse_preset_input(grid_json)
            if not payload:
                payload, err = canonical_grid_payload(grid_json or self.get_grid_layout() or default_payload())
            if err and not payload:
                return json.dumps({"ok": False, "error": err})
            if not payload:
                return json.dumps({"ok": False, "error": "invalid grid payload"})
            info = {"tree": tree, "ws": ws, "incoming": incoming}
            doc = self._build_preset_doc(name, payload, info)
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
        # Pure getter: returns the stored portable doc for the JS preview →
        # confirm → apply flow (no server-side apply; that would rearrange
        # the grid behind the preview modal before the user confirms).
        doc = self.config.window_presets.load_preset(name)
        if not doc:
            return json.dumps({"ok": False, "error": f"preset {name} not found"})
        try:
            grid = doc.get("grid", {})
            tree = grid.get("tree") if isinstance(grid, dict) else None
            if not isinstance(tree, dict):
                return json.dumps({"ok": False, "error": "unsupported window preset format or schema version"})
            ver = grid.get("version", GRID_VERSION)
            _, err = canonical_grid_payload(json.dumps({"v": ver, "tree": tree}))
            if err:
                return json.dumps({"ok": False, "error": err})
            self._log(f"Window preset loaded: {name}", "success")
            return json.dumps(doc, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

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
        doc = self.config.window_presets.load_preset(name)
        if not doc:
            return json.dumps({"ok": False, "error": "not found"})
        try:
            if QFileDialog is None:
                # headless fallback: export to config folder
                path = Path("config") / f"{name}_window.json"
                with path.open("w", encoding="utf-8") as f:
                    json.dump(doc, f, indent=2, ensure_ascii=False)
            else:
                folder = QFileDialog.getExistingDirectory(None, "Export window preset")
                if not folder:
                    return json.dumps({"ok": False, "cancelled": True})
                path = Path(folder) / f"{name}.json"
                with path.open("w", encoding="utf-8") as f:
                    json.dump(doc, f, indent=2, ensure_ascii=False)
            self._exported_paths[name] = str(path)
            self._log(f"Window preset exported to {path}", "success")
            return json.dumps({"ok": True, "path": str(path)})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def import_window_preset(self):
        try:
            if QFileDialog is None:
                return json.dumps({"ok": False, "error": "No file dialog in headless mode"})
            file_path, _ = QFileDialog.getOpenFileName(None, "Import window preset", "", "JSON (*.json)")
            if not file_path:
                return json.dumps({"ok": False, "cancelled": True})
            with open(file_path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            name = doc.get("name") or Path(file_path).stem
            grid = doc.get("grid", {})
            payload = grid.get("payload")
            if payload:
                _, err = canonical_grid_payload(payload)
                if err:
                    return json.dumps({"ok": False, "error": f"invalid grid: {err}"})
            self.config.window_presets.save_preset(name, doc)
            self.list_window_presets()
            self._log(f"Window preset imported: {name}", "success")
            return json.dumps({"ok": True, "name": name})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=bool)
    def show_window_preset_in_folder(self, name: str):
        path = self._exported_paths.get(name) or str(self.config.window_presets.path)
        self._log(f"Preset folder: {path}", "info")
        return True


class WindowPresetParsePanel:

    def _extract_tree_from_grid(self, g, parsed):
        # ideal-size: 10 lines reason=extract tree case
        if "tree" not in g or not isinstance(g["tree"], dict):
            return None, None
        tree = g["tree"]
        ver = g.get("version") or parsed.get("v") or 4
        cand = json.dumps({"v": ver, "tree": tree}, ensure_ascii=False, separators=(",",":"))
        tp, err = canonical_grid_payload(cand)
        if err:
            return None, None
        return tree, tp

    def _extract_payload_from_grid(self, g):
        # ideal-size: 7 lines reason=extract payload case
        if "payload" not in g or not isinstance(g["payload"], str):
            return None, None
        tp, err = canonical_grid_payload(g["payload"])
        if err:
            return None, None
        data = json.loads(tp)
        return data.get("tree"), tp

    def _extract_from_portable(self, parsed: dict):
        # ideal-size: 12 lines reason=delegates to tree/payload helpers
        try:
            if not isinstance(parsed, dict):
                return None, None, None, None
            if "grid" not in parsed or not isinstance(parsed["grid"], dict):
                return None, None, None, None
            g = parsed["grid"]
            ws = parsed.get("window_states")
            tree, payload = self._extract_tree_from_grid(g, parsed)
            if payload:
                return tree, payload, ws, parsed
            tree, payload = self._extract_payload_from_grid(g)
            if payload:
                return tree, payload, ws, parsed
            return None, None, None, None
        except Exception:
            return None, None, None, None

    def _parse_preset_input(self, grid_json: str):
        # ideal-size: 18 lines reason=parses multiple input formats
        if not grid_json:
            return None, None, None, None, None
        try:
            parsed = json.loads(grid_json)
        except Exception as e:
            return None, None, None, None, f"bad JSON {e}"
        if not isinstance(parsed, dict):
            return None, None, None, None, "payload must be object"
        tree, payload, ws, doc = self._extract_from_portable(parsed)
        if payload:
            return tree, payload, ws, doc, None
        if "v" in parsed and "tree" in parsed:
            tp, err = canonical_grid_payload(grid_json)
            if not err:
                data = json.loads(tp)
                return data.get("tree"), tp, None, None, None
            return None, None, None, None, err
        return None, None, None, None, None

    def _build_preset_doc(self, name: str, payload: str, info: dict):
        # ideal-size: 20 lines reason=build final preset document from info dict
        data = json.loads(payload)
        tree = info.get("tree") or data.get("tree")
        ws = info.get("ws")
        incoming = info.get("incoming")
        count = len(leaf_ids(tree)) if tree else 0
        if not ws:
            ws = self.config.get_state("window_states", {"closed": [], "minimized": []})
            if incoming and isinstance(incoming.get("window_states"), dict):
                ws = incoming["window_states"]
        if incoming and isinstance(incoming, dict) and incoming.get("format") == "chat-v-bot.window-preset":
            doc = incoming.copy()
            doc["name"] = name
            doc["grid"] = {"payload": payload, "window_count": count, "tree": tree, "type": doc.get("grid", {}).get("type", "sash-tree"), "version": data.get("v", 4), "sizes_unit": "percent"}
            doc["window_states"] = ws
            doc["updated_at"] = datetime.utcnow().isoformat() + "Z"
            doc["app_version"] = doc.get("app_version", "arena-1.0")
        else:
            doc = {"name": name, "grid": {"payload": payload, "window_count": count, "tree": tree}, "window_states": ws, "updated_at": datetime.utcnow().isoformat() + "Z", "app_version": "arena-1.0"}
        return doc
