"""Watcher handlers — captcha/generation/clear decisions, ≤150 LOC, params ≤4 via deps."""
from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Dict, Any, Callable

@dataclass
class HandlerDeps:
    config: Any
    state: Any
    cdp_probe: Any
    job_ctrl: Any
    logger: Callable
    notifier: Callable

class WatcherHandlers:
    def __init__(self, deps: HandlerDeps):
        self.config = deps.config
        self.state = deps.state
        self.cdp_probe = deps.cdp_probe
        self.job_ctrl = deps.job_ctrl
        self._logger = deps.logger
        self._notify = deps.notifier

    async def handle_captcha(self, cdp, is_captcha: bool):
        from ..watcher_overlay import build_captcha_msg, should_start_captcha_waiting, is_captcha_timeout
        self.state.last_captcha_detected = is_captcha
        if not is_captcha:
            return False
        if should_start_captcha_waiting(self.state.waiting_kind):
            self.state.waiting_since = time.time()
            self.state.waiting_kind = "captcha"
            self.state.captcha_waits += 1
            self.state.status = "waiting_captcha"
            self._logger(f"🛡️ Watcher: Captcha detected — {build_captcha_msg(self.config.captcha_timeout_sec)}, pausing jobs", "warn")
            await self.cdp_probe.show_overlay(cdp, "wait for user. Captcha", "captcha", self.config.captcha_timeout_sec)
            self.job_ctrl.pause()
            await self._notify()
        else:
            if is_captcha_timeout(self.state.waiting_since, self.config.captcha_timeout_sec):
                elapsed = int(time.time() - (self.state.waiting_since or time.time()))
                self._logger(f"⏰ Watcher: Captcha timeout {elapsed}s limit {self.config.captcha_timeout_sec}s", "error")
                await self._notify()
        return True

    async def handle_generation(self, cdp, is_gen: bool, details: Dict[str, Any]):
        from ..watcher_overlay import build_generation_msg, should_start_generation_waiting, is_generation_timeout
        self.state.last_generation_details = details
        if not is_gen:
            return False
        if should_start_generation_waiting(self.state.waiting_kind):
            self.state.waiting_since = time.time()
            self.state.waiting_kind = "generation"
            self.state.generation_waits += 1
            self.state.status = "waiting_generation"
            self._logger(f"⏳ Watcher: {build_generation_msg(details, self.config.generation_timeout_sec)}, pausing jobs", "warn")
            await self.cdp_probe.show_overlay(cdp, "wait for finish generation", "generation", self.config.generation_timeout_sec)
            self.job_ctrl.pause()
            await self._notify()
        else:
            if is_generation_timeout(self.state.waiting_since, self.config.generation_timeout_sec):
                elapsed = int(time.time() - (self.state.waiting_since or time.time()))
                self._logger(f"⏰ Watcher: Generation timeout {elapsed}s limit {self.config.generation_timeout_sec}s", "error")
                await self._notify()
        return True

    async def handle_clear(self, cdp, is_captcha: bool, is_gen: bool):
        from ..watcher_overlay import should_clear_overlay, build_clear_msg
        if not should_clear_overlay(self.state.waiting_kind, is_captcha, is_gen):
            return False
        kind = self.state.waiting_kind
        elapsed = int(time.time() - (self.state.waiting_since or time.time()))
        self._logger(f"✅ Watcher: {build_clear_msg(kind, elapsed)}, resuming", "success")
        await self.cdp_probe.hide_overlay(cdp)
        self.job_ctrl.resume()
        self.state.waiting_since = None
        self.state.waiting_kind = None
        self.state.status = "watching"
        await self._notify()
        return True
