# ideal-size: ~350 lines reason=frozen 10-slot settings/preset surface plus per-section appliers; save/load/import share the preset wire format and always change together (RULE 18.2)
"""App settings panel — prompt/settings, import-export, arena presets, theme.

Owns the 10 settings slots (R4): thin slots delegate to per-section module
funcs (dispatch tables for scalar settings keys and watcher timeouts, as the
design prescribes). Preset wire formats (state names vs JS names) are applied
by dedicated restore funcs. Imports go panels -> services/core only.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from app.core.models import UrlRow
from app.core.persistence import load_preset, save_preset
from app.services import job_history
from app.services.live import debug_view
from app.services.live.bus import live_bus
from app.services.live.feed import commit_queue
from app.ui.qt_compat import QFileDialog, Slot
from app.ui.services import arena_serialize, undo_entries

log = logging.getLogger("arena")

_TIMEOUT_SPEC = ("timeout_seconds", "timeouts", "page_load", int)
_RETRIES_SPEC = ("max_retries", "retries", "max_attempts", int)
_SUFFIX_SPEC = ("naming_suffix", "output", "suffix", None)
_OVERWRITE_SPEC = ("overwrite", "output", "overwrite", bool)

_WATCHER_TIMEOUTS = (
    ("watcher_captcha_timeout_sec", 10, "captcha_timeout_sec", "Watcher captcha timeout"),
    ("watcher_generation_timeout_sec", 30, "generation_timeout_sec", "Watcher generation timeout"),
)


def push_prompt_undo(bridge, tmpl: str) -> None:
    """Snapshot prompt template to undo (best effort)."""
    try:
        bridge.undo_service.push("prompt", tmpl)
        undo_entries.emit_undo_state(bridge)
    except Exception:
        pass


def push_settings_undo(bridge) -> None:
    """Snapshot settings to undo (best effort)."""
    try:
        js = arena_serialize.arena_to_js(bridge.state)["settings"]
        bridge.undo_service.push("settings", js)
        undo_entries.emit_undo_state(bridge)
    except Exception:
        pass


def apply_simple_key(state, data: dict, spec: tuple) -> None:
    """Copy one scalar key into its settings section (skipped if absent)."""
    key, section, field, coerce = spec
    if key in data:
        value = coerce(data[key]) if coerce else data[key]
        getattr(state.settings, section)[field] = value


def apply_generation_timeout(bridge, data: dict) -> None:
    """Generation timeout: clamp 30-3600s, sync watcher config, log."""
    if "generation_timeout" not in data:
        return
    gt = max(30, min(3600, int(data["generation_timeout"])))
    bridge.state.settings.timeouts["generation"] = gt
    bridge._log(f"Generation timeout set to {gt}s (waiting max time)", "info")
    try:
        bridge.config.set_state(watcher_generation_timeout_sec=gt)
        if bridge._watcher:
            bridge._watcher.update_config(generation_timeout_sec=gt)
    except Exception:
        pass


def apply_supported_types(state, data: dict) -> None:
    """Supported types land on both folder config and settings."""
    if "supported_types" in data:
        state.folder["supported_types"] = data["supported_types"]
        state.settings.supported_types = data["supported_types"]


def apply_highlight_duration(state, config, data: dict) -> None:
    """Highlight duration lands on settings and config state."""
    if "highlight_duration" in data:
        state.settings.highlight["duration_seconds"] = int(data["highlight_duration"])
        config.set_state(highlight_duration=int(data["highlight_duration"]))


def apply_url_interval(bridge, data: dict) -> None:
    """URL reconcile interval: clamp, persist, wake the loop so the next pass uses it (S6)."""
    if debug_view.INTERVAL_KEY not in data:
        return
    ms = debug_view.clamp_interval_ms(data[debug_view.INTERVAL_KEY])
    bridge.config.set_state(**{debug_view.INTERVAL_KEY: ms})
    live_bus(bridge).wake("interval")
    bridge._log(f"🔁 URL reconcile interval set to {ms} ms (Settings)", "info")


def apply_history_limit(bridge, data: dict) -> None:
    """Job-history display count: clamp, persist, re-push the rows, log (mirrors apply_url_interval)."""
    if job_history.LIMIT_KEY not in data:
        return
    n = job_history.clamp_history_limit(data[job_history.LIMIT_KEY])
    bridge.config.set_state(**{job_history.LIMIT_KEY: n})
    job_history.emit_history(bridge)
    bridge._log(f"🗂 Job history shows last {n} jobs", "info")


def apply_watcher_timeouts(bridge, data: dict) -> None:
    """Watcher timeouts from the settings window (each best effort)."""
    for key, lo, update_kw, label in _WATCHER_TIMEOUTS:
        if key in data:
            try:
                v = max(lo, min(3600, int(data[key])))
                bridge.config.set_state(**{key: v})
                if bridge._watcher:
                    bridge._watcher.update_config(**{update_kw: v})
                bridge._log(f"{label} set to {v}s (user win setting)", "info")
            except Exception:
                pass


def apply_preset_settings(state, s: dict, include_folder_types: bool = False) -> None:
    """Apply a settings-dict section (preset wire format)."""
    if not isinstance(s, dict):
        return
    if "timeouts" in s:
        state.settings.timeouts.update(s["timeouts"])
    if "output" in s:
        state.settings.output.update(s["output"])
    if "highlight" in s:
        state.settings.highlight.update(s["highlight"])
    if include_folder_types and "supported_types" in s:
        state.folder["supported_types"] = s["supported_types"]


def build_cdp_snapshot(config) -> dict:
    """CDP connection fields as stored in arena presets."""
    return {
        "host": config.get_state("cdp_host", "127.0.0.1"),
        "port": config.get_state("cdp_port", 9222),
        "user_data_dir": config.get_state("cdp_user_data_dir", "C:\\arena-images-chrome"),
        "extra_args": config.get_state("cdp_extra_args", ""),
    }


def read_action_blocks_snapshot(config) -> list:
    """Action blocks as stored (default stack when none saved yet)."""
    try:
        action_blocks = config.get_state("action_blocks", None)
        if action_blocks is None:
            # Lazy: import failure must degrade to [] (preset still saves).
            from app.core.action_blocks import default_stack, stack_to_dicts
            action_blocks = stack_to_dicts(default_stack())
    except Exception:
        action_blocks = []
    return action_blocks


def build_cooldown_snapshot(config) -> dict:
    """Cooldown fields as stored in arena presets."""
    return {
        "enabled": config.get_state("cooldown_enabled", True),
        "min_seconds": config.get_state("cooldown_min_seconds", 300),
        "captcha_penalty_seconds": config.get_state("cooldown_captcha_penalty_seconds", 900),
        "rate_limit_penalty_seconds": config.get_state("cooldown_rate_limit_penalty_seconds", 1800),
    }


def build_arena_preset_doc(name: str, js_state: dict, config) -> dict:
    """Full arena preset document (JS state + config snapshots)."""
    return {
        "name": name,
        "urls": js_state.get("urls", []),
        "folder": js_state.get("folder", {}),
        "prompt": js_state.get("prompt", {}),
        "settings": js_state.get("settings", {}),
        "images": js_state.get("images", []),
        "cdp": build_cdp_snapshot(config),
        "action_blocks": read_action_blocks_snapshot(config),
        "cooldown": build_cooldown_snapshot(config),
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "app_version": "arena-1.0",
    }


def restore_import_sections(state, data: dict) -> None:
    """Restore urls/folder/prompt from an import doc (state wire format)."""
    if "urls" in data:
        state.urls = [UrlRow(**u) for u in data["urls"]]
    if "folder" in data:
        state.folder.update(data["folder"])
    if "prompt" in data:
        state.prompt.update(data["prompt"])


def restore_preset_urls(state, doc: dict) -> None:
    """Restore URL rows (JS names: status/last_error); default ids by index."""
    if "urls" in doc:
        state.urls = [UrlRow(
            id=u.get("id", f"url_{i}"),
            url=u.get("url", ""),
            enabled=u.get("enabled", True),
            last_status=u.get("status", "unchecked"),
            error=u.get("last_error")
        ) for i, u in enumerate(doc.get("urls", []))]


def restore_preset_folder_prompt(state, doc: dict) -> None:
    """Restore folder config and prompt template (dict or raw string)."""
    if "folder" in doc:
        state.folder.update(doc["folder"])
    if "prompt" in doc:
        tmpl = doc["prompt"].get("template") if isinstance(doc["prompt"], dict) else str(doc["prompt"])
        state.prompt["user_prompt"] = tmpl


def restore_preset_cdp(bridge, doc: dict) -> None:
    """Restore CDP connection fields into config and the live client."""
    if "cdp" in doc and isinstance(doc["cdp"], dict):
        c = doc["cdp"]
        host = c.get("host", "127.0.0.1")
        port = c.get("port", 9222)
        user_data_dir = c.get("user_data_dir", "C:\\arena-images-chrome")
        extra = c.get("extra_args", "")
        bridge.config.set_state(cdp_host=host, cdp_port=int(port),
                                cdp_user_data_dir=user_data_dir, cdp_extra_args=extra)
        if bridge.cdp:
            try:
                bridge.cdp.set_host_port(host, int(port))
            except Exception:
                pass


def restore_preset_action_blocks(bridge, doc: dict) -> None:
    """Restore action blocks into config and emit to the UI."""
    if "action_blocks" in doc and isinstance(doc["action_blocks"], list):
        try:
            bridge.config.set_state(action_blocks=doc["action_blocks"])
            bridge.action_blocks_updated.emit(json.dumps(doc["action_blocks"], ensure_ascii=False))
            bridge._log(f"Restored {len(doc['action_blocks'])} action blocks from preset", "info")
        except Exception as e:
            log.warning(f"Failed to restore action blocks from preset: {e}")


def restore_preset_cooldown(bridge, doc: dict) -> None:
    """Restore cooldown settings (clamped) into config."""
    if "cooldown" in doc and isinstance(doc["cooldown"], dict):
        try:
            from app.core.cooldown import clamp_seconds
            cd = doc["cooldown"]
            bridge.config.set_state(
                cooldown_enabled=bool(cd.get("enabled", True)),
                cooldown_min_seconds=clamp_seconds(cd.get("min_seconds", 300), 300),
                cooldown_captcha_penalty_seconds=clamp_seconds(cd.get("captcha_penalty_seconds", 900), 900),
                cooldown_rate_limit_penalty_seconds=clamp_seconds(cd.get("rate_limit_penalty_seconds", 1800), 1800))
            bridge._log("Restored cooldown settings from preset", "info")
        except Exception as e:
            log.warning(f"Failed to restore cooldown from preset: {e}")


class AppSettingsMixin:
    """Prompt/settings, preset import-export, arena presets, theme."""

    @Slot(str, result=bool)
    def set_theme(self, theme: str):
        self.config.set_state(theme=theme)
        self._log(f"Theme set to {theme}", "info")
        return True

    @Slot(str, result=str)
    def set_prompt(self, template: str):
        self.state.prompt["user_prompt"] = template
        self._save_arena()
        push_prompt_undo(self, template)
        return json.dumps({"ok": True})

    @Slot(str, result=str)
    def save_settings(self, settings_json: str):
        try:
            data = json.loads(settings_json)
            apply_simple_key(self.state, data, _TIMEOUT_SPEC)
            apply_generation_timeout(self, data)
            apply_simple_key(self.state, data, _RETRIES_SPEC)
            apply_simple_key(self.state, data, _SUFFIX_SPEC)
            apply_supported_types(self.state, data)
            apply_simple_key(self.state, data, _OVERWRITE_SPEC)
            apply_highlight_duration(self.state, self.config, data)
            apply_watcher_timeouts(self, data)
            apply_url_interval(self, data)
            apply_history_limit(self, data)
            self._save_arena()
            push_settings_undo(self)
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
            restore_import_sections(self.state, data)
            if "settings" in data:
                apply_preset_settings(self.state, data["settings"])
            commit_queue(self, "preset", undo=False)
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

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
            js_state = arena_serialize.arena_to_js(self.state)
            doc = build_arena_preset_doc(name, js_state, self.config)
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
            restore_preset_urls(self.state, doc)
            restore_preset_folder_prompt(self.state, doc)
            if "settings" in doc:
                apply_preset_settings(self.state, doc["settings"], include_folder_types=True)
            restore_preset_cdp(self, doc)
            restore_preset_action_blocks(self, doc)
            restore_preset_cooldown(self, doc)
            commit_queue(self, "preset", undo=False)
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

    @Slot(str, result=str)
    def refresh_users(self):
        # compatibility with old app: just emit arena state
        self._emit_arena_state()
