"""Watcher CDP calls; keep target discovery in targets.py."""
from __future__ import annotations

import asyncio
from typing import Callable

from app.browser.dom_highlight import WatcherOverlaySpec
from .targets import WatcherTarget  # compatibility export for existing integrations
from .overlay_calls import show_overlay as _show_target


class WatcherCDP:
    def __init__(self, cdp_getter: Callable | None, logger: Callable):
        self._cdp_getter = cdp_getter
        self._logger = logger

    def get(self):
        return self._cdp_getter() if self._cdp_getter else None

    async def check_captcha(self, cdp):
        return await _check_captcha(cdp, self._logger)

    async def check_generation(self, cdp):
        return await _check_generation(cdp)

    async def show_overlay(self, cdp, spec: WatcherOverlaySpec):
        return await _show_overlay(cdp, spec, self._logger)

    async def hide_overlay(self, cdp, owner_key=""):
        return await _hide_overlay(cdp, owner_key)


async def check_page_error(cdp, logger) -> str | None:
    try:
        return await asyncio.wait_for(cdp.scan_page_errors(), 3.0)
    except Exception as exc:
        _warn(logger, f"Watcher page-error check unanswered: {exc}")
        return None


async def _check_captcha(cdp, logger):
    try:
        return bool(await asyncio.wait_for(cdp.is_security_dialog_visible(), 3.0))
    except Exception as exc:
        _warn(logger, f"Watcher captcha check unanswered: {exc}")
        return None


async def _check_generation(cdp):
    try:
        return await asyncio.wait_for(cdp.is_generating(), 5.0)
    except Exception as exc:
        return False, {"unanswered": True, "error": str(exc)}


async def _show_overlay(cdp, spec, logger):
    try:
        return await _show_target(cdp, spec)
    except Exception as exc:
        _warn(logger, f"Watcher overlay show failed: {exc}")
        return False


async def _hide_overlay(cdp, owner_key):
    try:
        return await cdp.hide_watcher_overlay(owner_key=owner_key)
    except Exception:
        return False


def _warn(logger, message):
    logger(message, "warn")
