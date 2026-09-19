"""Url Panel — Bridge panel mixin (W1.6 split)."""

from __future__ import annotations

import json
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



class UrlPanel:

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
