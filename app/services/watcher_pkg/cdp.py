"""Watcher CDP probe — pure CDP calls, ≤100 LOC."""
from __future__ import annotations
from typing import Callable, Dict, Any

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
