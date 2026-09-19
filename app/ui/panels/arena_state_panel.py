"""Arena State Panel — Bridge panel mixin (W1.6 split)."""

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

from app.core.persistence import save_state

log = logging.getLogger("arena")


class ArenaStatePanel:

    def _log(self, msg: str, level: str = "info"):
        # Emit only arena_log to avoid duplicate logs (previously emitted both log_message and arena_log
        # which JS connected both to LogConsole.log causing double lines)
        try:
            self.arena_log.emit(msg, level)
        except Exception:
            pass
        try:
            # Also try log_message but JS now dedupes? Keep only arena_log for single log
            # self.log_message.emit(msg, level)
            pass
        except Exception:
            pass

    def _save_arena(self):
        try:
            save_state(self.state, self.state_path)
            self._emit_arena_state()
        except Exception as e:
            log.error(f"Failed to save arena state: {e}")
            self.arena_log.emit(f"Failed to save state: {e}", "error")

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

    def _arena_to_js(self):
        """Convert AppState to JS-friendly shape matching old bridge expectations."""
        d = self.state.to_dict()
        return {
            "version": d.get("version"),
            "urls": _arena_urls_js(d),
            "images": _arena_images_js(d),
            "folder": d.get("folder", {}),
            "prompt": {"template": d.get("prompt", {}).get("user_prompt", "")},
            "settings": _arena_settings_js(d),
            "progress": d.get("progress", {}),
            "run_state": d.get("run_state"),
            "jobs": d.get("jobs", []),
        }

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
        js_state = self._arena_to_js()
        return json.dumps(js_state, ensure_ascii=False)

    def _on_cdp_error(self, err_msg: str):
        try:
            self._log(f"CDP error: {err_msg[:500]}", "error")
        except Exception:
            pass
        try:
            self.connection_status.emit("error")
        except Exception:
            pass


def _arena_urls_js(d: dict) -> list:
    """urls -> [{id, url, enabled, status, last_error, last_checked, tab_id}]."""
    return [{
        "id": u.get("id"),
        "url": u.get("url"),
        "enabled": u.get("enabled", True),
        "status": u.get("last_status", "unchecked"),
        "last_error": u.get("error", ""),
        "last_checked": u.get("last_checked"),
        "tab_id": u.get("tab_id", ""),
    } for u in d.get("urls", [])]


def _arena_images_js(d: dict) -> list:
    """images -> expected JS fields (assigned_url, attempts, output_path...)."""
    return [{
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
    } for img in d.get("images", [])]


def _arena_settings_js(d: dict) -> dict:
    """settings -> flattened JS shape (timeouts/output/highlight/browser)."""
    settings_dict = d.get("settings", {})
    timeouts = settings_dict.get("timeouts", {})
    output = settings_dict.get("output", {})
    highlight = settings_dict.get("highlight", {})
    return {
        "timeout_seconds": timeouts.get("page_load", 30),
        "generation_timeout": timeouts.get("generation", 180),
        "max_retries": settings_dict.get("retries", {}).get("max_attempts", 3),
        "naming_suffix": output.get("suffix", "_AI"),
        "supported_types": d.get("folder", {}).get("supported_types", [".png", ".jpg"]),
        "overwrite": output.get("overwrite", False),
        "highlight_duration": highlight.get("duration_seconds", 3),
        "max_concurrent": settings_dict.get("concurrency", 1),
        "browser": settings_dict.get("browser", {}),
        "output": output,
        "highlight": highlight,
        "timeouts": timeouts,
    }
