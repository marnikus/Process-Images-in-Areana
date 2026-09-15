"""Bridge — QWebChannel QObject exposing slots to JS.

Handles:
- layout persistence (grid_layout, window_states)
- theme
- window presets (save/load/list/delete/import/export with preview)
- arena operations (urls, folder, queue, prompt, settings, run controls, highlight)
"""

import json
import logging
from datetime import datetime
from pathlib import Path

try:
    from PySide6.QtCore import QObject, Signal, Slot
    from PySide6.QtWidgets import QFileDialog
except ImportError:
    class QObject:
        def __init__(self, *a, **kw): pass
    def Signal(*a, **kw):
        class _Sig:
            def emit(self, *a, **kw): pass
            def connect(self, *a, **kw): pass
        return _Sig()
    def Slot(*a, **kw):
        def deco(fn): return fn
        return deco
    QFileDialog = None

from app.core.layout_service import (
    WINDOW_IDS,
    canonical_grid_payload, default_payload, leaf_ids,
)
from app.core.models import AppState, UrlRow, ImageItem
from app.core.persistence import load_state, save_state, save_preset, load_preset
from app.core.scanner import scan_folder
from app.persistence.config_manager import ConfigManager
from app.core.undo_service import UndoService
from app.browser.tab_matcher import best_matches
from app.browser.dom_highlight import build_highlight_js, build_clear_js

log = logging.getLogger("arena")

class Bridge(QObject):
    log_message = Signal(str, str)
    grid_layout_changed = Signal(str)
    grid_layout_persisted = Signal(bool)
    window_preset_list_updated = Signal(str)
    arena_log = Signal(str, str)
    arena_state_updated = Signal(str)
    progress_updated = Signal(str)
    highlight_rect = Signal(str)
    history_changed = Signal()
    undo_state_changed = Signal(str)  # JSON {history,index,canUndo,canRedo}
    tabs_received = Signal(str)
    connection_status = Signal(str)
    tab_match_result = Signal(str, str)
    url_presets_updated = Signal(str)
    presets_changed = Signal(str, str)  # kind, payload

    def __init__(self, config_manager: ConfigManager, state_path: Path, cdp_client=None, parent=None):
        super().__init__(parent)
        self.config = config_manager
        self.state_path = Path(state_path)
        self.state = load_state(self.state_path)
        self._run_state = "idle"
        self._cancel_requested = False
        self._pause_requested = False
        self._stop_after = False
        self._exported_paths = {}
        self.undo_service = UndoService(self.config.undo)
        self.cdp = cdp_client
        # ensure undo history loaded
        try:
            self.config.undo.load()
        except Exception:
            pass
        # install CDP status forwarding if client exists
        if self.cdp:
            try:
                self.cdp.connected.connect(lambda: self.connection_status.emit("connected"))
                self.cdp.disconnected.connect(lambda: self.connection_status.emit("disconnected"))
                self.cdp.error.connect(lambda e: self.connection_status.emit("error"))
            except Exception:
                pass

    def _save_arena(self):
        try:
            save_state(self.state, self.state_path)
            self._emit_arena_state()
        except Exception as e:
            log.error(f"Failed to save arena state: {e}")
            self.arena_log.emit(f"Failed to save state: {e}", "error")

    def _arena_to_js(self):
        """Convert AppState to JS-friendly shape matching old bridge expectations."""
        d = self.state.to_dict()
        # urls: map to {id, url, enabled, status, last_error}
        urls_js = []
        for u in d.get("urls", []):
            urls_js.append({
                "id": u.get("id"),
                "url": u.get("url"),
                "enabled": u.get("enabled", True),
                "status": u.get("last_status", "unchecked"),
                "last_error": u.get("error", ""),
                "last_checked": u.get("last_checked"),
            })
        # images: map to expected fields
        images_js = []
        for img in d.get("images", []):
            images_js.append({
                "id": img.get("id"),
                "relative_path": img.get("relative_path"),
                "absolute_path": img.get("absolute_path"),
                "filename": img.get("filename"),
                "status": img.get("status", "pending"),
                "selected": img.get("selected", False),
                "assigned_url": img.get("assigned_url_id") or "",
                "attempts": img.get("attempt_count", 0),
                "output_path": img.get("output_path") or "",
                "error": img.get("error") or "",
                "size": img.get("size", 0),
            })
        # prompt: template is user_prompt
        prompt_js = {
            "template": d.get("prompt", {}).get("user_prompt", ""),
        }
        # settings: flatten relevant
        settings_dict = d.get("settings", {})
        timeouts = settings_dict.get("timeouts", {})
        output = settings_dict.get("output", {})
        highlight = settings_dict.get("highlight", {})
        browser = settings_dict.get("browser", {})
        settings_js = {
            "timeout_seconds": timeouts.get("page_load", 30),
            "max_retries": settings_dict.get("retries", {}).get("max_attempts", 3),
            "naming_suffix": output.get("suffix", "_AI"),
            "supported_types": d.get("folder", {}).get("supported_types", [".png",".jpg"]),
            "overwrite": output.get("overwrite", False),
            "highlight_duration": highlight.get("duration_seconds", 3),
            "max_concurrent": settings_dict.get("concurrency", 1),
            "browser": browser,
            "output": output,
            "highlight": highlight,
            "timeouts": timeouts,
        }
        # folder
        folder_js = d.get("folder", {})
        # progress
        progress_js = d.get("progress", {})
        return {
            "version": d.get("version"),
            "urls": urls_js,
            "images": images_js,
            "folder": folder_js,
            "prompt": prompt_js,
            "settings": settings_js,
            "progress": progress_js,
            "run_state": d.get("run_state"),
            "jobs": d.get("jobs", []),
        }

    def _emit_arena_state(self):
        try:
            js_state = self._arena_to_js()
            payload = json.dumps(js_state, ensure_ascii=False)
            self.arena_state_updated.emit(payload)
            prog = js_state.get("progress", {}).copy()
            prog["run_state"] = getattr(self, "_run_state", "idle")
            self.progress_updated.emit(json.dumps(prog, ensure_ascii=False))
        except Exception as e:
            log.warning(f"emit arena state failed: {e}")

    def _log(self, msg: str, level: str = "info"):
        self.log_message.emit(msg, level)
        self.arena_log.emit(msg, level)

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

    @Slot(str, str, result=str)
    def save_window_preset(self, name: str, grid_json: str):
        try:
            tree_payload, err = canonical_grid_payload(grid_json or self.get_grid_layout() or default_payload())
            if err:
                return json.dumps({"ok": False, "error": err})
            data = json.loads(tree_payload)
            tree = data.get("tree")
            window_count = len(leaf_ids(tree))
            doc = {
                "name": name,
                "grid": {
                    "payload": tree_payload,
                    "window_count": window_count,
                    "tree": tree,
                },
                "window_states": self.config.get_state("window_states", {"closed": [], "minimized": []}),
                "updated_at": datetime.utcnow().isoformat() + "Z",
                "app_version": "arena-1.0",
            }
            self.config.window_presets.save_preset(name, doc)
            self.list_window_presets()
            self._log(f"Window preset saved: {name}", "success")
            return json.dumps({"ok": True, "name": name})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def load_window_preset(self, name: str):
        doc = self.config.window_presets.load_preset(name)
        if not doc:
            return json.dumps({"ok": False, "error": f"preset {name} not found"})
        try:
            grid = doc.get("grid", {})
            payload = grid.get("payload")
            if not payload:
                return json.dumps({"ok": False, "error": "invalid preset"})
            _, err = canonical_grid_payload(payload)
            if err:
                return json.dumps({"ok": False, "error": err})
            self.config.set_state(grid_layout=payload, window_states=doc.get("window_states", {"closed": [], "minimized": []}))
            self.grid_layout_changed.emit(payload)
            self._log(f"Window preset loaded: {name}", "success")
            return json.dumps({"ok": True, "name": name, "payload": payload, "window_states": doc.get("window_states")})
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

    @Slot(result=str)
    def get_arena_state(self):
        js_state = self._arena_to_js()
        return json.dumps(js_state, ensure_ascii=False)

    @Slot(str, result=str)
    def add_url(self, url: str):
        url = url.strip()
        if not url:
            return json.dumps({"ok": False, "error": "empty URL"})
        if not (url.startswith("http://") or url.startswith("https://")):
            return json.dumps({"ok": False, "error": "URL must start with http:// or https://"})
        for u in self.state.urls:
            if u.url == url:
                return json.dumps({"ok": False, "error": "URL already exists"})
        # push undo before change? We'll push after with new state
        item = UrlRow.create(url, enabled=True)
        self.state.urls.append(item)
        self._save_arena()
        # push urls snapshot to undo
        try:
            js_urls = self._arena_to_js()["urls"]
            self.undo_service.push("urls", js_urls)
            self._emit_undo_state()
        except Exception:
            pass
        return json.dumps({"ok": True, "id": item.id})

    def _push_urls_undo(self):
        try:
            js_urls = self._arena_to_js()["urls"]
            self.undo_service.push("urls", js_urls)
            self._emit_undo_state()
        except Exception:
            pass

    @Slot(str, result=str)
    def remove_url(self, url_id: str):
        before = len(self.state.urls)
        self.state.urls = [u for u in self.state.urls if u.id != url_id]
        if len(self.state.urls) == before:
            return json.dumps({"ok": False, "error": "not found"})
        self._save_arena()
        self._push_urls_undo()
        return json.dumps({"ok": True})

    @Slot(str, result=str)
    def toggle_url(self, url_id: str):
        for u in self.state.urls:
            if u.id == url_id:
                u.enabled = not u.enabled
                self._save_arena()
                self._push_urls_undo()
                return json.dumps({"ok": True, "enabled": u.enabled})
        return json.dumps({"ok": False, "error": "not found"})

    @Slot(str, str, result=str)
    def edit_url(self, url_id: str, new_url: str):
        new_url = new_url.strip()
        if not new_url:
            return json.dumps({"ok": False, "error": "empty URL"})
        for u in self.state.urls:
            if u.id == url_id:
                u.url = new_url
                u.last_status = "unchecked"
                u.error = None
                self._save_arena()
                self._push_urls_undo()
                return json.dumps({"ok": True})
        return json.dumps({"ok": False, "error": "not found"})

    @Slot(str, result=str)
    def test_url(self, url_id: str):
        for u in self.state.urls:
            if u.id == url_id:
                if u.url.startswith("http"):
                    u.last_status = "ready"
                    u.last_checked = datetime.utcnow().isoformat() + "Z"
                    self._save_arena()
                    return json.dumps({"ok": True, "status": "ready"})
                else:
                    u.last_status = "error"
                    u.error = "Invalid URL"
                    self._save_arena()
                    return json.dumps({"ok": False, "error": "Invalid URL"})
        return json.dumps({"ok": False, "error": "not found"})

    def _push_folder_undo(self):
        try:
            self.undo_service.push("folder", self.state.folder.copy())
            self._emit_undo_state()
        except Exception:
            pass

    @Slot(result=str)
    def pick_folder(self):
        if QFileDialog is None:
            return json.dumps({"ok": False, "error": "No file dialog"})
        folder = QFileDialog.getExistingDirectory(None, "Select image folder")
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
        root = self.state.folder.get("root_path", "")
        if not root:
            return json.dumps({"ok": False, "error": "No folder set"})
        root_path = Path(root)
        if not root_path.exists():
            return json.dumps({"ok": False, "error": "Folder does not exist"})
        supported = set(self.state.folder.get("supported_types", [".png",".jpg",".jpeg",".webp"]))
        ignore_ai = self.state.folder.get("ignore_ai_suffix", True)
        try:
            scanned = scan_folder(root_path, supported, ignore_ai)
            existing = {img.relative_path: img for img in self.state.images}
            added = 0
            for s in scanned:
                rel = s["relative_path"]
                if rel not in existing:
                    img = ImageItem.from_scan_dict(s, selected=False)
                    self.state.images.append(img)
                    added += 1
                else:
                    e = existing[rel]
                    e.size = s["size"]
                    e.mtime = s["mtime"]
                    e.absolute_path = s["absolute_path"]
            self.state.recalculate_progress()
            self._save_arena()
            self._log(f"Scanned {len(scanned)} images, {added} new", "success")
            return json.dumps({"ok": True, "count": len(scanned), "added": added})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

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

    def _push_prompt_undo(self, tmpl: str):
        try:
            self.undo_service.push("prompt", tmpl)
            self._emit_undo_state()
        except Exception:
            pass

    @Slot(str, result=str)
    def set_prompt(self, template: str):
        self.state.prompt["user_prompt"] = template
        self._save_arena()
        self._push_prompt_undo(template)
        return json.dumps({"ok": True})

    @Slot(str, result=str)
    def save_settings(self, settings_json: str):
        try:
            data = json.loads(settings_json)
            # Map to AppSettings structure
            if "timeout_seconds" in data:
                self.state.settings.timeouts["page_load"] = int(data["timeout_seconds"])
            if "max_retries" in data:
                self.state.settings.retries["max_attempts"] = int(data["max_retries"])
            if "naming_suffix" in data:
                self.state.settings.output["suffix"] = data["naming_suffix"]
            if "supported_types" in data:
                self.state.folder["supported_types"] = data["supported_types"]
                self.state.settings.supported_types = data["supported_types"]
            if "overwrite" in data:
                self.state.settings.output["overwrite"] = bool(data["overwrite"])
            if "highlight_duration" in data:
                self.state.settings.highlight["duration_seconds"] = int(data["highlight_duration"])
                self.config.set_state(highlight_duration=int(data["highlight_duration"]))
            self._save_arena()
            try:
                self.undo_service.push("settings", self._arena_to_js()["settings"])
                self._emit_undo_state()
            except Exception:
                pass
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def export_preset(self, name: str):
        try:
            preset_path = Path("config") / f"{name}.json"
            save_preset(self.state, preset_path)
            return json.dumps({"ok": True, "path": str(preset_path)})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def import_preset(self):
        try:
            if QFileDialog is None:
                return json.dumps({"ok": False, "error": "No file dialog"})
            file_path, _ = QFileDialog.getOpenFileName(None, "Import preset JSON", "config", "JSON (*.json)")
            if not file_path:
                return json.dumps({"ok": False, "cancelled": True})
            data = load_preset(Path(file_path))
            if "urls" in data:
                self.state.urls = [UrlRow(**u) for u in data["urls"]]
            if "folder" in data:
                self.state.folder.update(data["folder"])
            if "prompt" in data:
                self.state.prompt.update(data["prompt"])
            if "settings" in data:
                # settings dict from preset is already AppSettings as dict
                s = data["settings"]
                # handle both old and new formats
                if isinstance(s, dict):
                    # if it has timeouts etc, update
                    if "timeouts" in s:
                        self.state.settings.timeouts.update(s["timeouts"])
                    if "output" in s:
                        self.state.settings.output.update(s["output"])
                    if "highlight" in s:
                        self.state.settings.highlight.update(s["highlight"])
            self.state.recalculate_progress()
            self._save_arena()
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    # ---- run controls — real implementation via CDP ----
    def _get_selected_images(self):
        return [img for img in self.state.images if img.selected and img.status in ("pending","failed","selected","needs_review","processing")]

    def _get_enabled_urls(self):
        return [u for u in self.state.urls if u.enabled]

    @Slot(result=str)
    def start_run(self):
        prompt = self.state.prompt.get("user_prompt","").strip()
        if not prompt:
            self._log("⚠ Prompt is empty — set prompt before running", "warn")
            return json.dumps({"ok": False, "error": "empty prompt"})
        selected = self._get_selected_images()
        if not selected:
            self._log("⚠ No selected images — select images in queue", "warn")
            return json.dumps({"ok": False, "error": "no selected images"})
        urls = self._get_enabled_urls()
        if not urls:
            self._log("⚠ No enabled URLs", "warn")
            return json.dumps({"ok": False, "error": "no enabled urls"})
        if not self.cdp or not self.cdp.is_connected:
            self._log("❌ Chrome not connected — click Diagnose, Refresh, Connect first. CDP must be connected to automate.", "error")
            return json.dumps({"ok": False, "error": "cdp not connected"})
        if self._run_state == "running":
            self._log("⚠ Already running", "warn")
            return json.dumps({"ok": False, "error": "already running"})
        self._run_state = "running"
        self._cancel_requested = False
        self._pause_requested = False
        self._stop_after = False
        self._log(f"🚀 Run started: {len(selected)} images, {len(urls)} urls, prompt len {len(prompt)}", "success")
        self._emit_arena_state()
        self._schedule_coro(self._do_run_batch())
        return json.dumps({"ok": True})

    @Slot(result=str)
    def pause_run(self):
        self._pause_requested = True
        self._run_state = "paused"
        self._log("⏸ Paused — will pause after current step", "warn")
        self._emit_arena_state()
        return json.dumps({"ok": True})

    @Slot(result=str)
    def resume_run(self):
        self._pause_requested = False
        self._run_state = "running"
        self._log("▶ Resumed", "info")
        self._emit_arena_state()
        return json.dumps({"ok": True})

    @Slot(result=str)
    def stop_after_current(self):
        self._stop_after = True
        self._run_state = "stopping"
        self._log("⏹ Will stop after current image", "warn")
        self._emit_arena_state()
        return json.dumps({"ok": True})

    @Slot(result=str)
    def cancel_current(self):
        self._cancel_requested = True
        self._run_state = "idle"
        self._log("✖ Cancel requested — stopping", "error")
        self._emit_arena_state()
        return json.dumps({"ok": True})

    @Slot(str, result=str)
    def highlight_image(self, img_id: str):
        self._emit_highlight_demo()
        if self.cdp and self.cdp.is_connected:
            self._schedule_coro(self._do_highlight_demo_cdp(img_id))
        return json.dumps({"ok": True})

    async def _do_highlight_demo_cdp(self, img_id: str):
        try:
            duration = self.config.get_state("highlight_duration", 3)
            duration_ms = int(duration * 1000) if duration else 2000
            from app.browser.cdp_arena import CDPArenaController
            ctrl = CDPArenaController(self.cdp, log_callback=lambda m: self._log(m, "info"))
            await ctrl.highlight_selector('textarea[name="message"]', color="#FF0000", duration_ms=duration_ms, caption=f"Image {img_id[:8]}" if img_id else "Clicked element")
            self.highlight_rect.emit(json.dumps({"x":200,"y":200,"width":320,"height":180,"duration":duration,"label":f"Image {img_id}" if img_id else "Clicked element"}))
        except Exception as e:
            self._log(f"Highlight failed: {e}", "warn")

    async def _do_run_batch(self):
        try:
            from app.browser.cdp_arena import CDPArenaController
            from app.utils.correlation import generate_correlation_id, build_final_prompt
            from app.core.naming import get_output_path, atomic_write_bytes
            from app.core.enums import ImageStatus
            import asyncio

            ctrl = CDPArenaController(self.cdp, log_callback=lambda m: self._log(m, "info"))
            ready, reasons = await ctrl.is_page_ready()
            if not ready:
                self._log(f"⚠ Page not ready: {', '.join(reasons)} — trying anyway", "warn")

            prompt_template = self.state.prompt.get("user_prompt","")
            selected_images = self._get_selected_images()
            urls = self._get_enabled_urls()
            suffix = self.state.settings.output.get("suffix", "_AI")
            overwrite = self.state.settings.output.get("overwrite", False)
            preserve_format = self.state.settings.output.get("preserve_format", True)
            unique_tpl = self.state.settings.output.get("unique_suffix_template", "{base}_AI_{n}{ext}")
            gen_timeout = self.state.settings.timeouts.get("generation", 180) * 1000
            highlight_duration = self.config.get_state("highlight_duration", 3)

            url_idx = 0
            for img in selected_images:
                if self._cancel_requested:
                    self._log("Batch cancelled", "warn")
                    break
                if getattr(self, '_stop_after', False):
                    self._log("Stopping after current as requested", "warn")
                    break
                while getattr(self, '_pause_requested', False):
                    self._log("Paused, waiting for resume...", "warn")
                    await asyncio.sleep(1)
                    if self._cancel_requested:
                        break

                url_row = urls[url_idx % len(urls)] if urls else None
                url_idx += 1
                img.assigned_url_id = url_row.id if url_row else None
                img.attempt_count += 1
                img.status = ImageStatus.PROCESSING.value
                self.state.recalculate_progress()
                self._save_arena()

                correlation_id = generate_correlation_id()
                final_prompt = build_final_prompt(correlation_id, prompt_template)
                self._log(f"[{correlation_id}] Starting {img.relative_path} with URL {url_row.url if url_row else 'N/A'}", "info")

                try:
                    baseline = await ctrl.capture_baseline()
                    self._log(f"[{correlation_id}] Baseline: {baseline.get('output_count')} existing outputs", "info")

                    if await ctrl.is_security_dialog_visible():
                        self._log(f"[{correlation_id}] ⚠ Security verification detected — please solve manually in Chrome, then resume", "error")
                        self._run_state = "paused"
                        self._pause_requested = True
                        self._emit_arena_state()
                        while await ctrl.is_security_dialog_visible():
                            if self._cancel_requested:
                                raise RuntimeError("Cancelled during CAPTCHA")
                            await asyncio.sleep(2)
                        self._log(f"[{correlation_id}] Security dialog gone, continuing", "success")
                        self._pause_requested = False
                        self._run_state = "running"

                    self._log(f"[{correlation_id}] Attaching {img.absolute_path}", "info")
                    try:
                        await ctrl.highlight_selector('input[type="file"]', color="#00FF00", duration_ms=int(highlight_duration*1000), caption="Attach image")
                    except Exception:
                        pass
                    ok, reason = await ctrl.attach_image(img.absolute_path)
                    if not ok:
                        raise RuntimeError(f"Attach failed: {reason}")
                    self._log(f"[{correlation_id}] Attachment verified: {reason}", "success")

                    self._log(f"[{correlation_id}] Inserting prompt with token [{correlation_id}]", "info")
                    try:
                        await ctrl.highlight_selector('textarea[name="message"]', color="#00AAFF", duration_ms=int(highlight_duration*1000), caption="Prompt")
                    except Exception:
                        pass
                    ok, reason = await ctrl.insert_prompt(final_prompt)
                    if not ok:
                        raise RuntimeError(f"Prompt insert failed: {reason}")
                    verified, vreason = await ctrl.verify_prompt(final_prompt)
                    if not verified:
                        self._log(f"[{correlation_id}] Prompt mismatch {vreason}, retrying", "warn")
                        ok, reason = await ctrl.insert_prompt(final_prompt)
                        verified, vreason = await ctrl.verify_prompt(final_prompt)
                        if not verified:
                            raise RuntimeError(f"Prompt verification failed: {vreason}")

                    self._log(f"[{correlation_id}] Submitting once", "info")
                    try:
                        await ctrl.highlight_selector('button[aria-label="Send message"]', color="#FFAA00", duration_ms=int(highlight_duration*1000), caption="Send")
                    except Exception:
                        pass
                    ok, reason = await ctrl.submit()
                    if not ok:
                        raise RuntimeError(f"Submit failed: {reason}")
                    self._log(f"[{correlation_id}] Submitted", "success")

                    self._log(f"[{correlation_id}] Waiting for generation (timeout {gen_timeout}ms)", "info")
                    status, data = await ctrl.wait_for_new_output(baseline, timeout_ms=gen_timeout)
                    if status == "failed":
                        raise RuntimeError(f"Generation timeout or failed: {data.get('error')}")
                    new_src = data.get("new_src")
                    if not new_src:
                        raise RuntimeError("New output src not found after generation")

                    self._log(f"[{correlation_id}] New output detected: {new_src[:80]}...", "success")

                    self._log(f"[{correlation_id}] Downloading highest-quality image", "info")
                    success, file_bytes, ctype = await ctrl.download_image(new_src)
                    if not success:
                        raise RuntimeError(f"Download failed: {ctype}")
                    if len(file_bytes) == 0:
                        raise RuntimeError("Downloaded empty file")

                    ext = None
                    try:
                        from PIL import Image
                        import io
                        im = Image.open(io.BytesIO(file_bytes))
                        fmt = im.format or "PNG"
                        ext = f".{fmt.lower()}" if fmt else ".png"
                        if im.width == 0 or im.height == 0:
                            raise ValueError("Zero dimension image")
                    except Exception:
                        if ".png" in new_src:
                            ext = ".png"
                        elif ".jpg" in new_src or ".jpeg" in new_src:
                            ext = ".jpg"
                        elif ".webp" in new_src:
                            ext = ".webp"
                        else:
                            ext = ".png"

                    from pathlib import Path
                    source_path = Path(img.absolute_path)
                    output_path = get_output_path(
                        source_path,
                        suffix=suffix,
                        preserve_format=preserve_format,
                        overwrite=overwrite,
                        downloaded_ext=ext,
                        unique_template=unique_tpl
                    )
                    atomic_write_bytes(source_path.parent, output_path, file_bytes)
                    img.output_path = str(output_path)
                    img.status = ImageStatus.COMPLETED.value
                    img.error = None
                    self._log(f"[{correlation_id}] ✅ Saved to {output_path} ({len(file_bytes)} bytes)", "success")
                    try:
                        self.highlight_rect.emit(json.dumps({"x": 100, "y": 100, "width": 200, "height": 200, "duration": highlight_duration, "label": f"Saved {output_path.name}"}))
                    except Exception:
                        pass

                except Exception as e:
                    img.status = ImageStatus.FAILED.value
                    img.error = str(e)
                    self._log(f"[{correlation_id}] ❌ Failed {img.relative_path}: {e}", "error")

                finally:
                    self.state.recalculate_progress()
                    self._save_arena()
                    await asyncio.sleep(1)

            self._log("🏁 Batch complete", "success")
            self._run_state = "idle"
            self._emit_arena_state()

        except Exception as e:
            self._log(f"Batch runner crashed: {e}", "error")
            import traceback
            traceback.print_exc()
            self._run_state = "idle"
            self._emit_arena_state()


    # ---- undo system ----
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

    @Slot(result=str)
    def get_undo_history(self):
        hist, idx = self.undo_service.history()
        return json.dumps({"history": hist, "index": idx}, ensure_ascii=False)

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

    def _remember_global_edit(self, kind: str, value):
        try:
            if kind == "grid":
                self.config.set_state(grid_layout=value)
                self.grid_layout_changed.emit(value)
                self.grid_layout_persisted.emit(True)
            elif kind == "window_states":
                if isinstance(value, dict):
                    self.config.set_state(window_states=value)
            elif kind == "urls":
                # value is list of url dicts (js shape) -> convert to UrlRow
                if isinstance(value, list):
                    self.state.urls = [UrlRow(
                        id=u.get("id", f"url_{i}"),
                        url=u.get("url",""),
                        enabled=u.get("enabled",True),
                        last_status=u.get("status","unchecked"),
                        last_checked=u.get("last_checked"),
                        error=u.get("last_error") or u.get("error")
                    ) for i, u in enumerate(value)]
                    self._save_arena()
            elif kind == "folder":
                if isinstance(value, dict):
                    self.state.folder.update(value)
                    self._save_arena()
            elif kind == "queue":
                # value is list of images js shape with selection
                if isinstance(value, list):
                    # map by id
                    sel_map = {img.get("id"): img.get("selected") for img in value}
                    for im in self.state.images:
                        if im.id in sel_map:
                            im.selected = bool(sel_map[im.id])
                    self.state.recalculate_progress()
                    self._save_arena()
            elif kind == "prompt":
                if isinstance(value, str):
                    self.state.prompt["user_prompt"] = value
                    self._save_arena()
                elif isinstance(value, dict):
                    tmpl = value.get("template") or value.get("user_prompt") or ""
                    self.state.prompt["user_prompt"] = tmpl
                    self._save_arena()
            elif kind == "settings":
                if isinstance(value, dict):
                    # reuse save_settings logic
                    self.state.settings.timeouts.update(value.get("timeouts", {}))
                    self.state.settings.output.update(value.get("output", {}))
                    self.state.settings.highlight.update(value.get("highlight", {}))
                    if "supported_types" in value:
                        self.state.folder["supported_types"] = value["supported_types"]
                    self._save_arena()
            elif kind == "arena":
                # full arena snapshot
                if isinstance(value, dict):
                    # try to restore from dict
                    try:
                        # value is from to_dict() or js shape?
                        if "urls" in value and isinstance(value["urls"], list) and value["urls"] and "url" in value["urls"][0]:
                            # js shape
                            self.state.urls = [UrlRow(
                                id=u.get("id"), url=u.get("url"), enabled=u.get("enabled",True),
                                last_status=u.get("status","unchecked"), error=u.get("last_error")
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
        except Exception as e:
            log.warning(f"_remember_global_edit {kind} failed: {e}")

    def _apply_undo_entry(self, entry):
        if not entry or not isinstance(entry, dict):
            return False
        kind = entry.get("kind")
        value = entry.get("value")
        try:
            if kind == "grid":
                if isinstance(value, str):
                    self.config.set_state(grid_layout=value)
                    self.grid_layout_changed.emit(value)
                    self.grid_layout_persisted.emit(True)
                    self._log(f"↩ Undo grid layout", "info")
            elif kind == "window_states":
                if isinstance(value, dict):
                    self.config.set_state(window_states=value)
                    self._log(f"↩ Undo window states", "info")
            elif kind == "urls":
                if isinstance(value, list):
                    self.state.urls = [UrlRow(
                        id=u.get("id", f"url_{i}"),
                        url=u.get("url",""),
                        enabled=u.get("enabled",True),
                        last_status=u.get("status","unchecked"),
                        last_checked=u.get("last_checked"),
                        error=u.get("last_error") or u.get("error")
                    ) for i, u in enumerate(value)]
                    self._save_arena()
                    self._log(f"↩ Undo URLs ({len(value)} items)", "info")
            elif kind == "folder":
                if isinstance(value, dict):
                    self.state.folder = value
                    self._save_arena()
                    self._log(f"↩ Undo folder", "info")
            elif kind == "queue":
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
            elif kind == "prompt":
                tmpl = value if isinstance(value, str) else (value.get("template") if isinstance(value, dict) else "")
                self.state.prompt["user_prompt"] = tmpl
                self._save_arena()
                self._log(f"↩ Undo prompt", "info")
            elif kind == "settings":
                if isinstance(value, dict):
                    if "timeouts" in value:
                        self.state.settings.timeouts.update(value["timeouts"])
                    if "output" in value:
                        self.state.settings.output.update(value["output"])
                    if "highlight" in value:
                        self.state.settings.highlight.update(value["highlight"])
                    if "supported_types" in value:
                        self.state.folder["supported_types"] = value["supported_types"]
                        self.state.settings.supported_types = value["supported_types"]
                    self._save_arena()
                    self._log(f"↩ Undo settings", "info")
            elif kind == "arena":
                # full snapshot
                if isinstance(value, dict):
                    try:
                        if "urls" in value:
                            self.state.urls = [UrlRow(
                                id=u.get("id"), url=u.get("url"), enabled=u.get("enabled",True),
                                last_status=u.get("status","unchecked"), error=u.get("last_error")
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
            else:
                # unknown kind, try generic
                self._log(f"↩ Undo {kind} (no specific handler)", "info")
            return True
        except Exception as e:
            log.warning(f"_apply_undo_entry {kind} failed: {e}")
            return False

    @Slot(result=str)
    def undo(self):
        result = self.undo_service.undo()
        if not result:
            self._log("⚠ Nothing to undo", "warn")
            self._emit_undo_state()
            return "null"
        hist, idx = self.undo_service.history()
        if idx == -1:
            # undo to empty — restore default/empty for the undone kind
            undone = result.get("undone") or result
            undone_kind = (undone.get("kind") if isinstance(undone, dict) else None) or result.get("kind")
            try:
                if undone_kind == "grid":
                    payload = default_payload()
                    self.config.set_state(grid_layout=payload)
                    self.grid_layout_changed.emit(payload)
                    self.grid_layout_persisted.emit(True)
                    self._log("↩ Undo grid → default", "info")
                elif undone_kind == "window_states":
                    empty_ws = {"closed": [], "minimized": []}
                    self.config.set_state(window_states=empty_ws)
                    self._log("↩ Undo window states → empty", "info")
                elif undone_kind == "urls":
                    self.state.urls = []
                    self._save_arena()
                    self._log("↩ Undo urls → empty", "info")
                elif undone_kind == "folder":
                    self.state.folder = {"root_path": "", "supported_types": [".png",".jpg",".jpeg",".webp"], "ignore_ai_suffix": True}
                    self._save_arena()
                    self._log("↩ Undo folder → empty", "info")
                elif undone_kind == "queue":
                    # keep images but clear selection? For empty we keep as is and log
                    self._log(f"↩ Undo {undone_kind} → empty", "info")
                elif undone_kind == "prompt":
                    self.state.prompt["user_prompt"] = ""
                    self._save_arena()
                    self._log("↩ Undo prompt → empty", "info")
                elif undone_kind == "settings":
                    self._log(f"↩ Undo {undone_kind} → empty", "info")
                else:
                    self._log(f"↩ Undo {undone_kind or result.get('kind')} → empty", "info")
            except Exception as e:
                log.warning(f"undo empty handling failed: {e}")
        else:
            # apply the current pointer's entry (previous state)
            current_entry = hist[idx] if 0 <= idx < len(hist) else None
            if current_entry:
                self._apply_undo_entry(current_entry)
            else:
                self._apply_undo_entry(result)
        self._emit_undo_state()
        return json.dumps(result, ensure_ascii=False)

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
    def get_stack_history(self):
        hist, idx = self.undo_service.stack_projection()
        return json.dumps({"history": hist, "index": idx}, ensure_ascii=False)

    @Slot(str)
    def push_stack_history(self, stack_json: str):
        try:
            blocks = json.loads(stack_json or "[]")
        except json.JSONDecodeError:
            return
        if isinstance(blocks, list):
            self.undo_service.push_stack(blocks)
            self._emit_undo_state()

    @Slot(str, int)
    def save_stack_history(self, history_json: str, index: int):
        try:
            hist = json.loads(history_json or "[]")
        except json.JSONDecodeError:
            return
        if not isinstance(hist, list):
            return
        if not isinstance(index, int):
            index = -1
        self.undo_service.set_stack_projection(hist, index)
        self._emit_undo_state()

    @Slot(result=str)
    def undo_stack(self):
        raw = self.undo()
        try:
            result = json.loads(raw)
            if isinstance(result, dict) and result.get("kind") in ("prompt","arena","urls","settings","queue","folder"):
                return json.dumps(result.get("value"), ensure_ascii=False)
            return "null"
        except Exception:
            return "null"

    @Slot(result=str)
    def redo_stack(self):
        raw = self.redo()
        try:
            result = json.loads(raw)
            if isinstance(result, dict) and result.get("kind") in ("prompt","arena","urls","settings","queue","folder"):
                return json.dumps(result.get("value"), ensure_ascii=False)
            return "null"
        except Exception:
            return "null"

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

    def _emit_highlight_demo(self):
        duration = self.config.get_state("highlight_duration", 3)
        rect = {
            "x": 200,
            "y": 200,
            "width": 320,
            "height": 180,
            "duration": duration,
            "label": "Clicked element"
        }
        self.highlight_rect.emit(json.dumps(rect))

    # ---- CDP Chrome connection (robust, non-blocking to avoid UI freeze) ----
    def _schedule_coro(self, coro):
        """Always run coro in a dedicated thread via asyncio.run to avoid blocking UI thread.
        Previous version tried to use existing event loop which could freeze UI when sync
        fetch_tabs_sync did blocking socket/DNS calls in main thread.
        """
        try:
            import asyncio
            import threading
            def _run():
                try:
                    asyncio.run(coro)
                except Exception as e:
                    log.warning(f"coro thread failed: {e}")
                    try:
                        self._log(f"Async task failed: {e}", "error")
                    except Exception:
                        pass
            threading.Thread(target=_run, daemon=True).start()
        except Exception as e:
            log.warning(f"_schedule_coro failed: {e}")
            try:
                coro.close()
            except Exception:
                pass

    @Slot(result=str)
    def get_tabs(self):
        """Non-blocking: always schedule async fetch in thread, return pending immediately.
        Previous sync fetch_tabs_sync did blocking DNS/socket in UI thread causing freeze.
        """
        if not self.cdp:
            return json.dumps([], ensure_ascii=False)
        # Schedule async fetch in background thread, return pending instantly
        self._schedule_coro(self._do_fetch_tabs())
        return "pending"

    @Slot(result=str)
    def diagnose_chrome(self):
        """Non-blocking diagnose: schedule in thread, return pending, emit logs via signals.
        Previous sync version blocked UI for several seconds doing DNS + socket checks.
        """
        if not self.cdp:
            return json.dumps({"error": "CDP not available"}, ensure_ascii=False)
        self._log(f"🩺 Diagnosing Chrome remote debugging on {self.cdp._host}:{self.cdp._port}… (non-blocking)", "info")
        self._schedule_coro(self._do_diagnose_chrome())
        return "pending"

    async def _do_diagnose_chrome(self):
        try:
            # Run sync diagnose in threadpool to avoid blocking event loop
            import asyncio
            loop = asyncio.get_event_loop()
            diag = await loop.run_in_executor(None, lambda: self.cdp.diagnose_sync())
            self._log(diag.get("summary",""), "info" if "✅" in diag.get("summary","") else "warn")
            for chk in diag.get("checks", []):
                host = chk.get("host")
                if chk.get("port_open"):
                    self._log(f"  · {host}:{self.cdp._port} open — list: {chk.get('list_count')} tabs", "info")
                else:
                    self._log(f"  · {host}:{self.cdp._port} closed — {chk.get('list_error') or chk.get('version_error') or 'no response'}", "warn")
                for t in chk.get("tabs", [])[:5]:
                    self._log(f"    - {t.get('title','')[:60]} — {t.get('url','')}", "success")
            # Also emit tabs if found
            if diag.get("tabs"):
                try:
                    payload = json.dumps([{"id": t.get("id"), "title": t.get("title"), "url": t.get("url"), "ws_url": t.get("ws_url")} for t in diag.get("tabs", [])], ensure_ascii=False)
                    self.tabs_received.emit(payload)
                except Exception:
                    pass
        except Exception as e:
            err = f"Diagnose failed: {e}"
            self._log(err, "error")

    async def _do_fetch_tabs(self):
        try:
            tabs = await self.cdp.fetch_tabs()
            payload = json.dumps([{"id": t.id, "title": t.title, "url": t.url, "ws_url": t.ws_url} for t in tabs], ensure_ascii=False)
            self.tabs_received.emit(payload)
            if not tabs:
                try:
                    diag = self.cdp.diagnose_sync()
                    self._log(diag.get("summary",""), "warn")
                except Exception:
                    pass
        except Exception as e:
            self._log(f"❌ Tab fetch failed: {e}", "error")

    @Slot(str)
    def connect_tab(self, ws_url: str):
        if not self.cdp:
            self._log("CDP client not available", "error")
            return
        self._schedule_coro(self._do_connect_tab(ws_url))

    async def _do_connect_tab(self, ws_url: str):
        try:
            ok = await self.cdp.connect(ws_url)
            if ok:
                self._log(f"🔗 Connected to {ws_url[:60]}", "success")
                self.connection_status.emit("connected")
            else:
                self._log(f"❌ Connect failed — check Chrome still open", "error")
                self.connection_status.emit("error")
        except Exception as e:
            self._log(f"❌ Connect failed: {e}", "error")
            self.connection_status.emit("error")

    @Slot(str)
    def find_tab_by_url(self, query: str):
        """Non-blocking: schedule async matching in thread."""
        if not self.cdp:
            self._log("CDP not available", "error")
            return
        self._schedule_coro(self._do_find_tab(query))

    async def _do_find_tab(self, query: str):
        query = (query or "").strip()
        if not query:
            self._log("⚠ URL field empty", "warn")
            self.tab_match_result.emit(query, "[]")
            return
        try:
            tabs = await self.cdp.fetch_tabs()
            if not tabs:
                try:
                    diag = self.cdp.diagnose_sync()
                    self._log(diag.get("summary","⚠ No Chrome tabs found"), "warn")
                    self._log("💡 Fix: 1) Close ALL Chrome windows. 2) Run: \"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe\" --remote-debugging-port=9222 --user-data-dir=\"C:\\arena-images-chrome\" 3) Open https://arena.ai in that NEW Chrome window. 4) Click Diagnose. 5) Open http://127.0.0.1:9222/json/list — you should see JSON.", "warn")
                except Exception:
                    self._log("⚠ No Chrome tabs found — start Chrome with --remote-debugging-port=9222 --user-data-dir=\"C:\\arena-images-chrome\"", "warn")
                self.tab_match_result.emit(query, "[]")
                return
            tab_dicts = [{"id": t.id, "title": t.title, "url": t.url, "ws_url": t.ws_url} for t in tabs]
            matches = best_matches(query, tab_dicts)
            if not matches:
                self._log(f"❌ No tab matches “{query}”. Available: " + "; ".join(f"{t.title} — {t.url}" for t in tabs[:5]), "error")
                self.tab_match_result.emit(query, "[]")
                return
            for m in matches[:3]:
                self._log(f"  · match ({m['kind']}): {m['title']} — {m['url']}", "success")
            self.tab_match_result.emit(query, json.dumps(matches, ensure_ascii=False))
        except Exception as e:
            self._log(f"❌ Tab matching failed: {e}", "error")
            self.tab_match_result.emit(query, "[]")

    # URL bookmarks (from old app, now using arena_presets)
    @Slot(result=str)
    def get_url_presets(self):
        try:
            presets = self.config.presets.get_url_presets()
            return json.dumps(presets, ensure_ascii=False)
        except Exception:
            return "[]"

    @Slot(str)
    def add_url_preset(self, url: str):
        url = (url or "").strip()
        if not url:
            self._log("⚠ URL field empty — nothing added", "warn")
            return
        try:
            if self.config.presets.add_url_preset(url):
                self._log(f"💾 URL bookmark added: {url}", "success")
            else:
                self._log(f"ℹ URL bookmark already exists: {url}", "info")
            payload = json.dumps(self.config.presets.get_url_presets(), ensure_ascii=False)
            self.url_presets_updated.emit(payload)
            self.presets_changed.emit("urls", payload)
        except Exception as e:
            self._log(f"Add bookmark failed: {e}", "error")

    @Slot(str)
    def remove_url_preset(self, url: str):
        try:
            if self.config.presets.remove_url_preset(url):
                self._log(f"🗑 URL bookmark removed: {url}", "warn")
            payload = json.dumps(self.config.presets.get_url_presets(), ensure_ascii=False)
            self.url_presets_updated.emit(payload)
            self.presets_changed.emit("urls", payload)
        except Exception as e:
            self._log(f"Remove bookmark failed: {e}", "error")

    @Slot(str)
    def set_last_url_preset(self, url: str):
        url = (url or "").strip()
        if not url:
            return
        self.config.set_state(last_url_preset=url)
        self._log(f"🔖 Bookmark remembered: {url}", "info")

    # Arena presets (full)
    @Slot(result=str)
    def list_arena_presets(self):
        try:
            presets = self.config.presets.list_arena_presets()
            payload = json.dumps(presets, ensure_ascii=False)
            self.presets_changed.emit("arena", payload)
            return payload
        except Exception as e:
            return json.dumps([], ensure_ascii=False)

    @Slot(str, result=str)
    def save_arena_preset(self, name: str):
        try:
            js_state = self._arena_to_js()
            cdp_cfg = {
                "host": self.config.get_state("cdp_host", "127.0.0.1"),
                "port": self.config.get_state("cdp_port", 9222),
                "user_data_dir": self.config.get_state("cdp_user_data_dir", "C:\\arena-images-chrome"),
                "extra_args": self.config.get_state("cdp_extra_args", ""),
            }
            doc = {
                "name": name,
                "urls": js_state.get("urls", []),
                "folder": js_state.get("folder", {}),
                "prompt": js_state.get("prompt", {}),
                "settings": js_state.get("settings", {}),
                "images": js_state.get("images", []),
                "cdp": cdp_cfg,
                "updated_at": datetime.utcnow().isoformat() + "Z",
                "app_version": "arena-1.0",
            }
            self.config.presets.save_arena_preset(name, doc)
            self.list_arena_presets()
            self._log(f"Arena preset saved: {name}", "success")
            return json.dumps({"ok": True, "name": name})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def load_arena_preset(self, name: str):
        try:
            doc = self.config.presets.load_arena_preset(name)
            if not doc:
                return json.dumps({"ok": False, "error": "not found"})
            # restore
            if "urls" in doc:
                self.state.urls = [UrlRow(
                    id=u.get("id", f"url_{i}"),
                    url=u.get("url",""),
                    enabled=u.get("enabled",True),
                    last_status=u.get("status","unchecked"),
                    error=u.get("last_error")
                ) for i, u in enumerate(doc.get("urls", []))]
            if "folder" in doc:
                self.state.folder.update(doc["folder"])
            if "prompt" in doc:
                tmpl = doc["prompt"].get("template") if isinstance(doc["prompt"], dict) else str(doc["prompt"])
                self.state.prompt["user_prompt"] = tmpl
            if "settings" in doc:
                s = doc["settings"]
                if isinstance(s, dict):
                    if "timeouts" in s:
                        self.state.settings.timeouts.update(s["timeouts"])
                    if "output" in s:
                        self.state.settings.output.update(s["output"])
                    if "highlight" in s:
                        self.state.settings.highlight.update(s["highlight"])
                    if "supported_types" in s:
                        self.state.folder["supported_types"] = s["supported_types"]
            if "cdp" in doc and isinstance(doc["cdp"], dict):
                c = doc["cdp"]
                host = c.get("host", "127.0.0.1")
                port = c.get("port", 9222)
                user_data_dir = c.get("user_data_dir", "C:\\arena-images-chrome")
                extra = c.get("extra_args", "")
                self.config.set_state(cdp_host=host, cdp_port=int(port), cdp_user_data_dir=user_data_dir, cdp_extra_args=extra)
                if self.cdp:
                    try:
                        self.cdp.set_host_port(host, int(port))
                    except Exception:
                        pass
            self.state.recalculate_progress()
            self._save_arena()
            self._log(f"Arena preset loaded: {name}", "success")
            return json.dumps({"ok": True, "name": name})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def delete_arena_preset(self, name: str):
        try:
            if self.config.presets.delete_arena_preset(name):
                self.list_arena_presets()
                self._log(f"Arena preset deleted: {name}", "info")
                return json.dumps({"ok": True})
            return json.dumps({"ok": False, "error": "not found"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    # Prompt presets
    @Slot(result=str)
    def list_prompt_presets(self):
        try:
            presets = self.config.presets.list_prompt_presets()
            return json.dumps(presets, ensure_ascii=False)
        except Exception:
            return "[]"

    @Slot(str, str, result=str)
    def save_prompt_preset(self, name: str, template: str):
        try:
            self.config.presets.save_prompt_preset(name, template)
            self._log(f"Prompt preset saved: {name}", "success")
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def load_prompt_preset(self, name: str):
        try:
            doc = self.config.presets.load_prompt_preset(name)
            if not doc:
                return json.dumps({"ok": False, "error": "not found"})
            tmpl = doc.get("template","")
            self.state.prompt["user_prompt"] = tmpl
            self._save_arena()
            return json.dumps({"ok": True, "template": tmpl})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def delete_prompt_preset(self, name: str):
        try:
            if self.config.presets.delete_prompt_preset(name):
                return json.dumps({"ok": True})
            return json.dumps({"ok": False, "error": "not found"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    # Highlight via CDP
    @Slot(str, str, int, str, result=str)
    def highlight_selector(self, selector: str, color: str, duration_ms: int, caption: str):
        if not self.cdp or not self.cdp.is_connected:
            # fallback to UI overlay
            rect = {
                "x": 200, "y": 200, "width": 320, "height": 180,
                "duration": duration_ms / 1000 if duration_ms>0 else 2,
                "label": caption or selector,
                "color": color
            }
            self.highlight_rect.emit(json.dumps(rect))
            return json.dumps({"ok": True, "fallback": True})
        # schedule async highlight
        self._schedule_coro(self._do_highlight(selector, color, duration_ms, caption))
        return json.dumps({"ok": True})

    async def _do_highlight(self, selector: str, color: str, duration_ms: int, caption: str):
        try:
            js = build_highlight_js(selector, color or "#FF0000", duration_ms or 2000, caption or selector, clear_first=True)
            result_json = await self.cdp.evaluate(js)
            if result_json:
                try:
                    data = json.loads(result_json) if isinstance(result_json, str) else result_json
                    if data.get("found") and data.get("rect"):
                        r = data["rect"]
                        rect = {
                            "x": r.get("x",0), "y": r.get("y",0),
                            "width": r.get("width",100), "height": r.get("height",100),
                            "duration": (duration_ms or 2000)/1000,
                            "label": caption or selector,
                            "color": color
                        }
                        self.highlight_rect.emit(json.dumps(rect))
                        self._log(f"🔍 Highlighted {selector} at {r}", "success")
                    else:
                        self._log(f"⚠ Highlight not found: {selector}", "warn")
                except Exception as e:
                    self._log(f"Highlight parse failed: {e}", "warn")
        except Exception as e:
            self._log(f"Highlight failed: {e}", "error")

    @Slot(result=str)
    def clear_highlights(self):
        if not self.cdp or not self.cdp.is_connected:
            return json.dumps({"ok": True})
        self._schedule_coro(self._do_clear_highlights())
        return json.dumps({"ok": True})

    async def _do_clear_highlights(self):
        try:
            js = build_clear_js()
            await self.cdp.evaluate(js)
            self._log("Highlights cleared", "info")
        except Exception as e:
            self._log(f"Clear highlights failed: {e}", "error")

    # ---- CDP config user decides port and user-data-dir ----
    @Slot(result=str)
    def get_cdp_config(self):
        try:
            host = self.config.get_state("cdp_host", "127.0.0.1")
            port = self.config.get_state("cdp_port", 9222)
            user_data_dir = self.config.get_state("cdp_user_data_dir", "C:\\arena-images-chrome")
            extra = self.config.get_state("cdp_extra_args", "")
            payload = {
                "host": host,
                "port": int(port),
                "user_data_dir": user_data_dir,
                "extra_args": extra,
                "base_url": f"http://{host}:{port}",
                "is_connected": bool(self.cdp and self.cdp.is_connected),
                "current_host": self.cdp._host if self.cdp else host,
                "current_port": self.cdp._port if self.cdp else int(port),
            }
            return json.dumps(payload, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @Slot(str, result=str)
    def set_cdp_config(self, config_json: str):
        try:
            data = json.loads(config_json or "{}")
            host = data.get("host") or data.get("cdp_host") or "127.0.0.1"
            port = data.get("port") or data.get("cdp_port") or 9222
            user_data_dir = data.get("user_data_dir") or data.get("cdp_user_data_dir") or "C:\\arena-images-chrome"
            extra = data.get("extra_args") or data.get("cdp_extra_args") or ""
            # validate
            try:
                port_i = int(port)
                if not (1 <= port_i <= 65535):
                    return json.dumps({"ok": False, "error": "port must be 1-65535"})
            except:
                return json.dumps({"ok": False, "error": "invalid port"})
            # save to session
            self.config.set_state(cdp_host=host, cdp_port=port_i, cdp_user_data_dir=user_data_dir, cdp_extra_args=extra)
            # update cdp client
            if self.cdp:
                try:
                    self.cdp.set_host_port(host, port_i)
                except Exception:
                    pass
            self._log(f"CDP config saved: {host}:{port_i} dir={user_data_dir}", "success")
            return json.dumps({"ok": True, "host": host, "port": port_i, "user_data_dir": user_data_dir})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def get_chrome_launch_command(self):
        try:
            host = self.config.get_state("cdp_host", "127.0.0.1")
            port = self.config.get_state("cdp_port", 9222)
            user_data_dir = self.config.get_state("cdp_user_data_dir", "C:\\arena-images-chrome")
            extra = self.config.get_state("cdp_extra_args", "")
            # Windows command
            win_cmd = f'"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port={port} --user-data-dir="{user_data_dir}"'
            if extra:
                win_cmd += f" {extra}"
            # Also with URL placeholder
            win_cmd_with_url = win_cmd + " https://arena.ai"
            # Linux/Mac
            linux_cmd = f'google-chrome --remote-debugging-port={port} --user-data-dir="{user_data_dir}"'
            if extra:
                linux_cmd += f" {extra}"
            payload = {
                "host": host,
                "port": int(port),
                "user_data_dir": user_data_dir,
                "extra_args": extra,
                "windows": win_cmd,
                "windows_with_url": win_cmd_with_url,
                "linux": linux_cmd,
                "test_url": f"http://{host}:{port}/json/list",
            }
            return json.dumps(payload, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @Slot(str, result=str)
    def cdp_attach_image_test(self, image_id: str):
        if not self.cdp or not self.cdp.is_connected:
            return json.dumps({"ok": False, "error": "CDP not connected"})
        # Find image
        img = None
        for im in self.state.images:
            if im.id == image_id or (not image_id and im.selected):
                img = im
                break
        if not img:
            # fallback first selected
            sel = [i for i in self.state.images if i.selected]
            if sel:
                img = sel[0]
        if not img:
            return json.dumps({"ok": False, "error": "No image found, select one in queue"})
        self._log(f"🧪 Testing attach for {img.absolute_path}", "info")
        self._schedule_coro(self._do_cdp_attach_test(img.absolute_path))
        return json.dumps({"ok": True, "path": img.absolute_path})

    async def _do_cdp_attach_test(self, image_path: str):
        try:
            from app.browser.cdp_arena import CDPArenaController
            ctrl = CDPArenaController(self.cdp, log_callback=lambda m: self._log(m, "info"))
            ok, reason = await ctrl.attach_image(image_path)
            if ok:
                self._log(f"✅ Attach test success: {reason}", "success")
            else:
                self._log(f"❌ Attach test failed: {reason}", "error")
        except Exception as e:
            self._log(f"Attach test exception: {e}", "error")

    @Slot(str, result=str)
    def cdp_insert_prompt_test(self, prompt_text: str):
        if not self.cdp or not self.cdp.is_connected:
            return json.dumps({"ok": False, "error": "CDP not connected"})
        txt = prompt_text or self.state.prompt.get("user_prompt","") or "Test prompt [JOB-ID: test123]"
        self._log(f"🧪 Testing prompt insert: {txt[:80]}...", "info")
        self._schedule_coro(self._do_cdp_prompt_test(txt))
        return json.dumps({"ok": True})

    async def _do_cdp_prompt_test(self, prompt_text: str):
        try:
            from app.browser.cdp_arena import CDPArenaController
            ctrl = CDPArenaController(self.cdp, log_callback=lambda m: self._log(m, "info"))
            ok, reason = await ctrl.insert_prompt(prompt_text)
            if ok:
                self._log(f"✅ Prompt insert success: {reason}", "success")
                verified, vreason = await ctrl.verify_prompt(prompt_text)
                self._log(f"Verify prompt: {verified} {vreason}", "info" if verified else "warn")
            else:
                self._log(f"❌ Prompt insert failed: {reason}", "error")
        except Exception as e:
            self._log(f"Prompt test exception: {e}", "error")

    @Slot(result=str)
    def cdp_test_full_flow(self):
        if not self.cdp or not self.cdp.is_connected:
            return json.dumps({"ok": False, "error": "CDP not connected"})
        sel = [i for i in self.state.images if i.selected]
        if not sel:
            return json.dumps({"ok": False, "error": "No selected image"})
        prompt = self.state.prompt.get("user_prompt","")
        if not prompt:
            return json.dumps({"ok": False, "error": "Empty prompt"})
        self._log(f"🧪 Testing full flow: attach + prompt + submit (without waiting)", "info")
        self._schedule_coro(self._do_cdp_full_flow_test(sel[0].absolute_path, prompt))
        return json.dumps({"ok": True})

    async def _do_cdp_full_flow_test(self, image_path: str, prompt_template: str):
        try:
            from app.browser.cdp_arena import CDPArenaController
            from app.utils.correlation import generate_correlation_id, build_final_prompt
            ctrl = CDPArenaController(self.cdp, log_callback=lambda m: self._log(m, "info"))
            baseline = await ctrl.capture_baseline()
            self._log(f"Baseline {baseline.get('output_count')} outputs", "info")
            ok, reason = await ctrl.attach_image(image_path)
            self._log(f"Attach: {ok} {reason}", "success" if ok else "error")
            if not ok:
                return
            cid = generate_correlation_id()
            final = build_final_prompt(cid, prompt_template)
            ok, reason = await ctrl.insert_prompt(final)
            self._log(f"Insert prompt [{cid}]: {ok} {reason}", "success" if ok else "error")
            if not ok:
                return
            ok, reason = await ctrl.submit()
            self._log(f"Submit: {ok} {reason}", "success" if ok else "error")
        except Exception as e:
            self._log(f"Full flow test exception: {e}", "error")

    @Slot(str, result=str)
    def refresh_users(self):
        # compatibility with old app: just emit arena state
        self._emit_arena_state()
        return json.dumps({"ok": True})

