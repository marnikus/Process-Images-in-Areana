"""Watcher handlers — captcha/generation/clear decisions, ≤150 LOC, params ≤4 via deps.

The generation wait lives in `generation.py` (start / restart / one-shot timeout, 2026-09-27).
"""
from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Dict, Any, Callable

from app.browser.dom_highlight import WatcherOverlaySpec
from .generation import GenerationWatch

@dataclass
class HandlerDeps:
    config: Any
    state: Any
    cdp_probe: Any
    job_ctrl: Any
    logger: Callable
    notifier: Callable
    overlay_owner_key: str = "watcher:primary"

class WatcherHandlers:
    def __init__(self, deps: HandlerDeps):
        self.config, self.state = deps.config, deps.state
        self.cdp_probe, self.job_ctrl = deps.cdp_probe, deps.job_ctrl
        self._logger, self._notify = deps.logger, deps.notifier
        self._overlay_owner_key, self._captcha_stale = deps.overlay_owner_key, False
        self._generation = GenerationWatch(deps, lambda msg, level: self._logger(msg, level))

    async def handle_captcha(self, cdp, is_captcha: bool):
        return await _handle_captcha(self, cdp, is_captcha)

    async def handle_generation(self, cdp, is_gen: bool, details: Dict[str, Any]):
        """Start / restart (new JOB-ID) / end (timeout, once) — `generation.GenerationWatch`."""
        return await self._generation.handle(cdp, is_gen, details)

    async def handle_clear(self, cdp, is_captcha: bool, is_gen: bool):
        from ..watcher_overlay import should_clear_overlay, build_clear_msg
        if not should_clear_overlay(self.state.waiting_kind, is_captcha, is_gen):
            return False
        kind = self.state.waiting_kind
        elapsed = int(time.time() - (self.state.waiting_since or time.time()))
        self._logger(f"✅ Watcher: {build_clear_msg(kind, elapsed)}, resuming", "success")
        await self.cdp_probe.hide_overlay(cdp, self._overlay_owner_key)
        self.job_ctrl.resume()
        self.state.waiting_since = None
        self.state.waiting_kind = None
        self.state.status = "watching"
        await self._notify()
        return True


async def _handle_captcha(handler, cdp, is_captcha):
    from ..watcher_overlay import build_captcha_msg, should_start_captcha_waiting
    state = handler.state
    state.last_captcha_detected = is_captcha
    if not is_captcha:
        handler._captcha_stale = False
        return False
    if handler._captcha_stale:
        return True
    if should_start_captcha_waiting(state.waiting_kind):
        await _start_captcha(handler, cdp, build_captcha_msg)
    else:
        await _captcha_timeout(handler, cdp)
    return True


async def _start_captcha(handler, cdp, build_message):
    state = handler.state
    timeout = handler.config.captcha_timeout_sec
    state.waiting_since, state.waiting_kind = time.time(), "captcha"
    state.captcha_waits += 1
    state.status = "waiting_captcha"
    handler._logger(f"🛡️ Watcher: Captcha detected — {build_message(timeout)}, pausing jobs", "warn")
    spec = WatcherOverlaySpec("wait for user. Captcha", "captcha", timeout,
                              owner_key=handler._overlay_owner_key)
    await handler.cdp_probe.show_overlay(cdp, spec)
    handler.job_ctrl.pause()
    await handler._notify()


async def _captcha_timeout(handler, cdp):
    from ..watcher_overlay import is_captcha_timeout
    state, timeout = handler.state, handler.config.captcha_timeout_sec
    if not is_captcha_timeout(state.waiting_since, timeout):
        return
    elapsed = int(time.time() - (state.waiting_since or time.time()))
    handler._logger(f"⏰ Watcher: Captcha timeout {elapsed}s limit {timeout}s — "
                    "stopped waiting until the captcha changes", "error")
    await handler.cdp_probe.hide_overlay(cdp, handler._overlay_owner_key)
    state.waiting_since, state.waiting_kind = None, None
    state.status, handler._captcha_stale = "watching", True
    handler.job_ctrl.resume()
    await handler._notify()
