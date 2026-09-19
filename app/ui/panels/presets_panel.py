"""Presets Panel — Bridge panel mixin (W1.6 split)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
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

from app.core.models import UrlRow
from app.core.action_blocks import default_stack, stack_to_dicts

log = logging.getLogger("arena")


class ArenaPresetPanel:

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
            doc = self._arena_preset_doc(name, self._arena_to_js())
            self.config.presets.save_arena_preset(name, doc)
            self.list_arena_presets()
            self._log(f"Arena preset saved: {name}", "success")
            return json.dumps({"ok": True, "name": name})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def _arena_preset_doc(self, name: str, js_state: dict) -> dict:
        """Full preset document: urls/folder/prompt/settings/images + cdp/blocks/cooldown."""
        return {
            "name": name,
            "urls": js_state.get("urls", []),
            "folder": js_state.get("folder", {}),
            "prompt": js_state.get("prompt", {}),
            "settings": js_state.get("settings", {}),
            "images": js_state.get("images", []),
            "cdp": self._preset_cdp_cfg(),
            "action_blocks": self._preset_action_blocks(),
            "cooldown": self._preset_cooldown_cfg(),
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "app_version": "arena-1.0",
        }

    def _preset_cdp_cfg(self) -> dict:
        """CDP connection settings snapshot for a preset."""
        return {
            "host": self.config.get_state("cdp_host", "127.0.0.1"),
            "port": self.config.get_state("cdp_port", 9222),
            "user_data_dir": self.config.get_state("cdp_user_data_dir", "C:\\arena-images-chrome"),
            "extra_args": self.config.get_state("cdp_extra_args", ""),
        }

    def _preset_action_blocks(self):
        """Current action blocks (or defaults) to include in a preset."""
        try:
            action_blocks = self.config.get_state("action_blocks", None)
            if action_blocks is None:
                from app.core.action_blocks import default_stack, stack_to_dicts
                action_blocks = stack_to_dicts(default_stack())
            return action_blocks
        except Exception:
            return []

    def _preset_cooldown_cfg(self) -> dict:
        """Cooldown settings snapshot for a preset."""
        return {
            "enabled": self.config.get_state("cooldown_enabled", True),
            "min_seconds": self.config.get_state("cooldown_min_seconds", 300),
            "captcha_penalty_seconds": self.config.get_state("cooldown_captcha_penalty_seconds", 900),
            "rate_limit_penalty_seconds": self.config.get_state("cooldown_rate_limit_penalty_seconds", 1800),
        }

    @Slot(str, result=str)
    def load_arena_preset(self, name: str):
        try:
            doc = self.config.presets.load_arena_preset(name)
            if not doc:
                return json.dumps({"ok": False, "error": "not found"})
            self._load_preset_urls(doc)
            self._load_preset_folder_prompt(doc)
            self._load_preset_settings(doc)
            self._load_preset_cdp(doc)
            self._load_preset_blocks(doc)
            self._load_preset_cooldown(doc)
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


class PromptPresetPanel:

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


class ArenaPresetRestorePanel:
    """Restore sections of an arena preset into live state (W1.6 split)."""

    def _load_preset_urls(self, doc: dict):
        """Restore url rows from a preset doc."""
        if "urls" in doc:
            self.state.urls = [UrlRow(
                id=u.get("id", f"url_{i}"),
                url=u.get("url", ""),
                enabled=u.get("enabled", True),
                last_status=u.get("status", "unchecked"),
                error=u.get("last_error")
            ) for i, u in enumerate(doc.get("urls", []))]

    def _load_preset_folder_prompt(self, doc: dict):
        """Restore folder + prompt template from a preset doc."""
        if "folder" in doc:
            self.state.folder.update(doc["folder"])
        if "prompt" in doc:
            tmpl = doc["prompt"].get("template") if isinstance(doc["prompt"], dict) else str(doc["prompt"])
            self.state.prompt["user_prompt"] = tmpl

    def _load_preset_settings(self, doc: dict):
        """Restore settings sub-dicts (timeouts/output/highlight/types)."""
        if "settings" not in doc:
            return
        st = doc["settings"]
        if not isinstance(st, dict):
            return
        if "timeouts" in st:
            self.state.settings.timeouts.update(st["timeouts"])
        if "output" in st:
            self.state.settings.output.update(st["output"])
        if "highlight" in st:
            self.state.settings.highlight.update(st["highlight"])
        if "supported_types" in st:
            self.state.folder["supported_types"] = st["supported_types"]

    def _load_preset_cdp(self, doc: dict):
        """Restore CDP host/port/user-data-dir (config + live client)."""
        if "cdp" not in doc or not isinstance(doc["cdp"], dict):
            return
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

    def _load_preset_blocks(self, doc: dict):
        """Restore action blocks from a preset doc (emit update signal)."""
        if "action_blocks" not in doc or not isinstance(doc["action_blocks"], list):
            return
        try:
            self.config.set_state(action_blocks=doc["action_blocks"])
            self.action_blocks_updated.emit(json.dumps(doc["action_blocks"], ensure_ascii=False))
            self._log(f"Restored {len(doc['action_blocks'])} action blocks from preset", "info")
        except Exception as e:
            log.warning(f"Failed to restore action blocks from preset: {e}")

    def _load_preset_cooldown(self, doc: dict):
        """Restore cooldown settings from a preset doc (clamped)."""
        if "cooldown" not in doc or not isinstance(doc["cooldown"], dict):
            return
        try:
            from app.core.cooldown import clamp_seconds
            cd = doc["cooldown"]
            self.config.set_state(
                cooldown_enabled=bool(cd.get("enabled", True)),
                cooldown_min_seconds=clamp_seconds(cd.get("min_seconds", 300), 300),
                cooldown_captcha_penalty_seconds=clamp_seconds(cd.get("captcha_penalty_seconds", 900), 900),
                cooldown_rate_limit_penalty_seconds=clamp_seconds(cd.get("rate_limit_penalty_seconds", 1800), 1800))
            self._log("Restored cooldown settings from preset", "info")
        except Exception as e:
            log.warning(f"Failed to restore cooldown from preset: {e}")
            self.state.recalculate_progress()
            self._save_arena()
            self._log(f"Arena preset loaded: {name}", "success")
            return json.dumps({"ok": True, "name": name})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})
