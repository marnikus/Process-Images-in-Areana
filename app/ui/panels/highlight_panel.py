"""Highlight Panel — Bridge panel mixin (W1.6 split)."""

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

from app.browser.dom_highlight import build_highlight_js, build_clear_js
from app.browser.probe_selectors import textarea_primary



class HighlightPanel:

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
            spec = (selector, color, duration_ms, caption)
            js = build_highlight_js(selector, {"color": color or "#FF0000", "highlight_ms": duration_ms or 2000, "caption": caption or selector, "clear_first": True})
            result_json = await self.cdp.evaluate(js)
            if result_json:
                data = json.loads(result_json) if isinstance(result_json, str) else result_json
                self._report_highlight_result(data, spec)
        except Exception as e:
            self._log(f"Highlight failed: {e}", "error")

    def _report_highlight_result(self, data: dict, spec: tuple):
        """Emit highlight_rect for a found rect; warn otherwise.
        spec = (selector, color, duration_ms, caption)."""
        selector = spec[0]
        try:
            if data.get("found") and data.get("rect"):
                self._emit_highlight_rect(data["rect"], spec)
                self._log(f"🔍 Highlighted {selector} at {data['rect']}", "success")
            else:
                self._log(f"⚠ Highlight not found: {selector}", "warn")
        except Exception as e:
            self._log(f"Highlight parse failed: {e}", "warn")

    def _emit_highlight_rect(self, r: dict, spec: tuple):
        """highlight_rect signal payload from a JS rect."""
        selector, color, duration_ms, caption = spec
        rect = {
            "x": r.get("x", 0), "y": r.get("y", 0),
            "width": r.get("width", 100), "height": r.get("height", 100),
            "duration": (duration_ms or 2000) / 1000,
            "label": caption or selector,
            "color": color
        }
        self.highlight_rect.emit(json.dumps(rect))

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
            await ctrl.highlight_selector(textarea_primary(), color="#FF0000", duration_ms=duration_ms, caption=f"Image {img_id[:8]}" if img_id else "Clicked element")
            self.highlight_rect.emit(json.dumps({"x":200,"y":200,"width":320,"height":180,"duration":duration,"label":f"Image {img_id}" if img_id else "Clicked element"}))
        except Exception as e:
            self._log(f"Highlight failed: {e}", "warn")
