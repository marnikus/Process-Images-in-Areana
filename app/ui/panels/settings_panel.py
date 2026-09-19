"""Settings Panel — Bridge panel mixin (W1.6 split)."""

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

from app.core.models import UrlRow
from app.core.persistence import save_preset, load_preset



class SettingsPanel:

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
            self._save_setting_timeouts(data)
            self._save_setting_simple(data)
            self._save_watcher_timeouts(data)
            self._save_arena()
            try:
                self.undo_service.push("settings", self._arena_to_js()["settings"])
                self._emit_undo_state()
            except Exception:
                pass
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def _save_setting_timeouts(self, data: dict):
        """page_load + generation timeout (clamped, synced to watcher)."""
        if "timeout_seconds" in data:
            self.state.settings.timeouts["page_load"] = int(data["timeout_seconds"])
        if "generation_timeout" not in data:
            return
        # User-configurable waiting max time; clamp 30-3600s (allow up to 1h)
        gt = max(30, min(3600, int(data["generation_timeout"])))
        self.state.settings.timeouts["generation"] = gt
        self._log(f"Generation timeout set to {gt}s (waiting max time)", "info")
        try:
            self.config.set_state(watcher_generation_timeout_sec=gt)
            if self._watcher:
                self._watcher.update_config(generation_timeout_sec=gt)
        except Exception:
            pass

    def _save_setting_simple(self, data: dict):
        """retries/suffix/types/overwrite/highlight from the settings window."""
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

    def _save_watcher_timeouts(self, data: dict):
        """Watcher captcha/generation timeouts from the settings window."""
        if "watcher_captcha_timeout_sec" in data:
            try:
                ct = max(10, min(3600, int(data["watcher_captcha_timeout_sec"])))
                self.config.set_state(watcher_captcha_timeout_sec=ct)
                if self._watcher:
                    self._watcher.update_config(captcha_timeout_sec=ct)
                self._log(f"Watcher captcha timeout set to {ct}s (user win setting)", "info")
            except Exception:
                pass
        if "watcher_generation_timeout_sec" in data:
            try:
                gt2 = max(30, min(3600, int(data["watcher_generation_timeout_sec"])))
                self.config.set_state(watcher_generation_timeout_sec=gt2)
                if self._watcher:
                    self._watcher.update_config(generation_timeout_sec=gt2)
                self._log(f"Watcher generation timeout set to {gt2}s (user win setting)", "info")
            except Exception:
                pass

    @Slot(str, result=str)
    def export_preset(self, name: str):
        try:
            preset_path = Path("config") / f"{name}.json"
            save_preset(self.state, preset_path)
            return json.dumps({"ok": True, "path": str(preset_path)})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def _import_preset_sections(self, data: dict):
        """urls/folder/prompt/settings sections of an imported preset."""
        if "urls" in data:
            self.state.urls = [UrlRow(**u) for u in data["urls"]]
        if "folder" in data:
            self.state.folder.update(data["folder"])
        if "prompt" in data:
            self.state.prompt.update(data["prompt"])
        if "settings" in data:
            # settings dict from preset is already AppSettings as dict
            st = data["settings"]
            if isinstance(st, dict):  # handle both old and new formats
                if "timeouts" in st:
                    self.state.settings.timeouts.update(st["timeouts"])
                if "output" in st:
                    self.state.settings.output.update(st["output"])
                if "highlight" in st:
                    self.state.settings.highlight.update(st["highlight"])

    @Slot(result=str)
    def import_preset(self):
        try:
            if QFileDialog is None:
                return json.dumps({"ok": False, "error": "No file dialog"})
            file_path, _ = QFileDialog.getOpenFileName(None, "Import preset JSON", "config", "JSON (*.json)")
            if not file_path:
                return json.dumps({"ok": False, "cancelled": True})
            data = load_preset(Path(file_path))
            self._import_preset_sections(data)
            self.state.recalculate_progress()
            self._save_arena()
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})


class CdpConfigPanel:

    @Slot(result=str)
    def get_cdp_config(self):
        try:
            host = self.config.get_state("cdp_host", "127.0.0.1")
            port = self.config.get_state("cdp_port", 9222)
            user_data_dir = self.config.get_state("cdp_user_data_dir", "C:\\arena-images-chrome")
            extra = self.config.get_state("cdp_extra_args", "")
            url_pattern = self.config.get_state("url_pattern", "arena.ai")
            payload = {
                "host": host,
                "port": int(port),
                "user_data_dir": user_data_dir,
                "extra_args": extra,
                "url_pattern": url_pattern,
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
            fallback = self.config.get_state("url_pattern", "arena.ai")
            cfg = _cdp_config_values(data, fallback)
            port_i, err = _cdp_valid_port(cfg[1])
            if err:
                return err
            self._apply_cdp_config(cfg, port_i)
            return json.dumps({"ok": True, "host": cfg[0], "port": port_i, "user_data_dir": cfg[2]})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def _apply_cdp_config(self, cfg: tuple, port_i: int):
        """Persist CDP config and push host/port to client + pool."""
        host, _, user_data_dir, extra, url_pattern = cfg
        self.config.set_state(cdp_host=host, cdp_port=port_i, cdp_user_data_dir=user_data_dir, cdp_extra_args=extra,
                              url_pattern=url_pattern)
        if self.cdp:
            try:
                self.cdp.set_host_port(host, port_i)
            except Exception:
                pass
        if self._page_pool:
            try:
                self._page_pool._host = str(host)
                self._page_pool._port = int(port_i)
            except Exception:
                pass
        self._log(f"CDP config saved: {host}:{port_i} dir={user_data_dir}", "success")

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
    def refresh_users(self):
        # compatibility with old app: just emit arena state
        self._emit_arena_state()
        return json.dumps({"ok": True})


def _cdp_config_values(data: dict, fallback_pattern: str) -> tuple:
    """(host, port, user_data_dir, extra_args, url_pattern) with defaults."""
    host = data.get("host") or data.get("cdp_host") or "127.0.0.1"
    port = data.get("port") or data.get("cdp_port") or 9222
    user_data_dir = data.get("user_data_dir") or data.get("cdp_user_data_dir") or "C:\\arena-images-chrome"
    extra = data.get("extra_args") or data.get("cdp_extra_args") or ""
    url_pattern = data.get("url_pattern", fallback_pattern)
    url_pattern = url_pattern.strip() if isinstance(url_pattern, str) else "arena.ai"
    return host, port, user_data_dir, extra, url_pattern


def _cdp_valid_port(port):
    """(int port, None) or (None, error json) for a CDP port value."""
    try:
        port_i = int(port)
    except Exception:
        return None, json.dumps({"ok": False, "error": "invalid port"})
    if not (1 <= port_i <= 65535):
        return None, json.dumps({"ok": False, "error": "port must be 1-65535"})
    return port_i, None
