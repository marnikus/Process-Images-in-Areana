"""Captcha Panel — Bridge panel mixin (W1.6 split)."""

from __future__ import annotations

import asyncio
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


log = logging.getLogger("arena")


class CaptchaPanel:

    def _captcha_service(self):
        """Lazy CaptchaService (key store + stats + solver); config dir = session store dir."""
        svc = getattr(self, "_captcha_service_obj", None)
        if svc is None:
            from app.services.captcha import CaptchaService
            svc = self._captcha_service_obj = CaptchaService(str(self.config.dir), self._log)
        return svc

    @Slot(str, result=str)
    def set_captcha_settings(self, payload_json: str):
        """Save 2Captcha key/enable/timeout; key stays local (masked in reply)."""
        try:
            data = json.loads(payload_json or "{}")
            key = str(data.get("api_key", "") or "").strip()
            enabled = bool(data.get("enabled", False))
            timeout = int(data.get("solve_timeout_sec", 180))
            result = self._captcha_service().apply_settings(key, enabled, timeout)
            self._log(f"🔐 2Captcha settings saved (key={'set' if key else 'empty'}, enabled={result['enabled']}, timeout={timeout}s)", "success")
            if result["enabled"]:
                asyncio.create_task(self._captcha_service().refresh_balance())
        except Exception as e:
            result = {"ok": False, "error": str(e)}
        return json.dumps(result, ensure_ascii=False)

    @Slot(result=str)
    def get_captcha_status(self):
        """Key mask + balance + last error; raw key never leaves the store."""
        try:
            svc = self._captcha_service()
            if svc.status_payload().get("has_key"):
                asyncio.create_task(svc.refresh_balance())  # fire-and-forget, next call shows it
            return json.dumps({"ok": True, **svc.status_payload()}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def get_captcha_stats(self):
        """Local solve counters + auto success rate + balance (API stat)."""
        try:
            return json.dumps({"ok": True, **self._captcha_service().stats_payload()}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    async def _settle_captcha_at(self, ctrl, tab_id, correlation_id, source):
        """Gate on visible, then auto-solve or wait; raise on stop (shared by 4 sites)."""
        try:
            if not await ctrl.is_security_dialog_visible():
                return
        except Exception:
            return
        from app.services.captcha import CaptchaCtx, handle_captcha
        stop = lambda: bool(self._stop_reason(tab_id)) if self._run_stop_requested(tab_id) else False
        def log(msg, level="info"):
            self._log(f"[{correlation_id}] {msg}", level)
        outcome = await handle_captcha(CaptchaCtx(ctrl=ctrl, pool=self._page_pool, bridge=self,
                                                  tab_id=tab_id, source=source, stop=stop, log=log))
        if outcome.status == "stopped":
            raise RuntimeError(f"{self._stop_reason(tab_id)} during CAPTCHA at {source}")

    @Slot(str, result=str)
    def stop_tab_job(self, tab_id: str):
        """Abort the live job on this tab; it fails as Aborted."""
        try:
            from app.services.cooldown_service import request_tab_abort
            if request_tab_abort(self._page_pool, tab_id):
                self._log(f"⛔ Stop requested for job on {(tab_id or '')[:12]}", "warn")
                self._emit_pool_status()
                return json.dumps({"ok": True})
            return json.dumps({"ok": False, "error": "no live job on this tab"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})
