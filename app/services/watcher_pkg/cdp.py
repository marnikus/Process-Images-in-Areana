"""Watcher CDP probe — pure CDP calls, ≤100 LOC.

REFACTOR 02: `detect_signal` / `detect_captcha` / `evaluate` add the probe
surface the per-page captcha step (captcha_step.WatcherCaptchaStep) needs —
detect returns a `CaptchaSignal` (None when nothing is on the page) and
evaluate runs the injected token JS. `tab_id` names the watched page; the
watcher tracks a single active page, so callers pass its stable key.
"""
from __future__ import annotations
from typing import Callable, Dict, Any, Optional

from app.services.captcha.signals import CaptchaSignal

class WatcherCDP:
    def __init__(self, cdp_getter: Callable | None, logger: Callable):
        self._cdp_getter = cdp_getter
        self._logger = logger

    def get(self):
        return self._cdp_getter() if self._cdp_getter else None

    async def check_captcha(self, cdp) -> bool:
        try:
            return bool(await cdp.is_security_dialog_visible())
        except Exception as e:
            self._logger(f"Watcher captcha check error: {e}", "warn")
            return False

    async def detect_signal(self, cdp, tab_id: str) -> Optional[CaptchaSignal]:
        """Full detect probe for one page; None when no captcha is shown."""
        try:
            from app.browser.captcha_probes import build_detect_js
            res = await cdp.cdp.evaluate(build_detect_js())
            signal = CaptchaSignal.from_result(res)
            if not signal.visible:
                return None
            signal.page_url = signal.page_url or ""
            return signal
        except Exception as e:
            self._logger(f"Watcher captcha detect failed ({tab_id[:8]}): {e}", "warn")
            return None

    async def detect_captcha(self, cdp, tab_id: str) -> bool:
        """Cheap visibility re-probe (step verify loop): still there?"""
        try:
            return bool(await cdp.is_security_dialog_visible())
        except Exception as e:
            self._logger(f"Watcher captcha re-probe error ({tab_id[:8]}): {e}", "warn")
            return False

    async def evaluate(self, cdp, tab_id: str, js: str) -> Any:
        """Run one JS snippet on the page (token injection)."""
        return await cdp.cdp.evaluate(js)

    async def check_generation(self, cdp):
        try:
            return await cdp.is_generating()
        except Exception as e:
            return False, {"error": str(e)}

    async def show_overlay(self, cdp, msg, kind, timeout):
        try:
            await cdp.show_watcher_overlay(msg, kind=kind, timeout_sec=timeout)
        except Exception as e:
            self._logger(f"Watcher overlay show failed: {e}", "warn")

    async def hide_overlay(self, cdp):
        try:
            await cdp.hide_watcher_overlay()
        except Exception:
            pass
