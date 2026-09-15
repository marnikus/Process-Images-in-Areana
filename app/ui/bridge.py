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

    def __init__(self, config_manager: ConfigManager, state_path: Path, parent=None):
        super().__init__(parent)
        self.config = config_manager
        self.state_path = Path(state_path)
        self.state = load_state(self.state_path)
        self._run_state = "idle"
        self._exported_paths = {}

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
        payload = {
            "theme": theme,
            "state": {
                "grid_layout": grid_layout,
                "window_states": window_states,
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
        return True

    @Slot(result=str)
    def reset_grid_layout(self):
        payload = default_payload()
        self.config.set_state(grid_layout=payload, window_states={"closed": [], "minimized": []})
        self.grid_layout_changed.emit(payload)
        self.grid_layout_persisted.emit(True)
        self._log("Grid layout reset to default", "info")
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
        self.config.set_state(window_states={"closed": closed, "minimized": minimized})
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
        item = UrlRow.create(url, enabled=True)
        self.state.urls.append(item)
        self._save_arena()
        return json.dumps({"ok": True, "id": item.id})

    @Slot(str, result=str)
    def remove_url(self, url_id: str):
        before = len(self.state.urls)
        self.state.urls = [u for u in self.state.urls if u.id != url_id]
        if len(self.state.urls) == before:
            return json.dumps({"ok": False, "error": "not found"})
        self._save_arena()
        return json.dumps({"ok": True})

    @Slot(str, result=str)
    def toggle_url(self, url_id: str):
        for u in self.state.urls:
            if u.id == url_id:
                u.enabled = not u.enabled
                self._save_arena()
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

    @Slot(result=str)
    def pick_folder(self):
        if QFileDialog is None:
            return json.dumps({"ok": False, "error": "No file dialog"})
        folder = QFileDialog.getExistingDirectory(None, "Select image folder")
        if not folder:
            return json.dumps({"ok": False, "cancelled": True})
        self.state.folder["root_path"] = folder
        self._save_arena()
        return json.dumps({"ok": True, "path": folder})

    @Slot(str, result=str)
    def set_folder_path(self, path: str):
        p = Path(path)
        if not p.exists() or not p.is_dir():
            return json.dumps({"ok": False, "error": "Folder does not exist"})
        self.state.folder["root_path"] = str(p)
        self._save_arena()
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

    @Slot(str, bool, result=str)
    def set_image_selected(self, img_id: str, selected: bool):
        for img in self.state.images:
            if img.id == img_id:
                img.selected = bool(selected)
                if selected and img.status == "skipped":
                    img.status = "pending"
                self.state.recalculate_progress()
                self._save_arena()
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
                return json.dumps({"ok": True})
        return json.dumps({"ok": False, "error": "not found"})

    @Slot(str, result=str)
    def set_prompt(self, template: str):
        self.state.prompt["user_prompt"] = template
        self._save_arena()
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

    @Slot(result=str)
    def start_run(self):
        self._run_state = "running"
        self._log("Run started (stub — browser automation to be integrated)", "info")
        self._emit_highlight_demo()
        self._emit_arena_state()
        return json.dumps({"ok": True})

    @Slot(result=str)
    def pause_run(self):
        self._run_state = "paused"
        self._log("Paused", "warn")
        self._emit_arena_state()
        return json.dumps({"ok": True})

    @Slot(result=str)
    def resume_run(self):
        self._run_state = "running"
        self._log("Resumed", "info")
        self._emit_arena_state()
        return json.dumps({"ok": True})

    @Slot(result=str)
    def stop_after_current(self):
        self._run_state = "stopping"
        self._log("Will stop after current", "warn")
        self._emit_arena_state()
        return json.dumps({"ok": True})

    @Slot(result=str)
    def cancel_current(self):
        self._run_state = "idle"
        self._log("Current cancelled", "warn")
        self._emit_arena_state()
        return json.dumps({"ok": True})

    @Slot(str, result=str)
    def highlight_image(self, img_id: str):
        self._emit_highlight_demo()
        return json.dumps({"ok": True})

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
