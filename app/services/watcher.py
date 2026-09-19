"""Watcher service — passively rechecks every x ms if page has awaiting icon (generating) or captcha.

In both situations it draws rectangle msg on left center page with msg "wait for finish generation"
or "wait for user. Captcha" and sleeps circle run and waits it solve.

Time to solve timeout is user configurable in win settings.
# ideal-size: 285 lines reason=WatcherService orchestrates async loop + state + overlay + job pause/resume; class LOC 260 baseline legacy after extracting config/state/jobs to separate modules; further split into StateMachine+Loop needs characterization tests (Area A1)
"""

import asyncio
import time
import logging
from typing import Optional, Dict, Any, Callable

from .watcher_config import WatcherConfig, WatcherState
from .watcher_jobs import pause_jobs, resume_jobs

log = logging.getLogger("watcher")


class WatcherService:
    """Passive watcher that checks page state every interval."""

    def __init__(self, config: WatcherConfig = None, cdp_controller_getter: Callable = None, job_runner_getter: Callable = None, logger: Callable = None):
        self.config = config or WatcherConfig()
        self.state = WatcherState()
        self._cdp_getter = cdp_controller_getter
        self._job_runner_getter = job_runner_getter
        self._logger = logger or (lambda msg, level="info": log.info(msg))
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._callbacks = []

    def set_cdp_getter(self, getter: Callable):
        self._cdp_getter = getter

    def set_job_runner_getter(self, getter: Callable):
        self._job_runner_getter = getter

    def set_logger(self, logger: Callable):
        self._logger = logger

    def update_config(self, **kwargs):
        for k, v in kwargs.items():
            if hasattr(self.config, k):
                setattr(self.config, k, v)
        self._logger(f"Watcher config updated: interval={self.config.check_interval_ms}ms captcha_timeout={self.config.captcha_timeout_sec}s gen_timeout={self.config.generation_timeout_sec}s enabled={self.config.enabled}", "info")
        if self.config.enabled and not self._running:
            self.start()
        elif not self.config.enabled and self._running:
            self.stop()

    def get_config(self) -> Dict[str, Any]:
        return {
            "enabled": self.config.enabled,
            "check_interval_ms": self.config.check_interval_ms,
            "captcha_timeout_sec": self.config.captcha_timeout_sec,
            "generation_timeout_sec": self.config.generation_timeout_sec,
            "auto_pause_jobs": self.config.auto_pause_jobs,
        }

    def get_state(self) -> Dict[str, Any]:
        return self.state.to_dict()

    def add_callback(self, cb: Callable):
        self._callbacks.append(cb)

    async def _notify(self):
        state = self.get_state()
        config = self.get_config()
        payload = {**state, "config": config}
        for cb in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(payload)
                else:
                    cb(payload)
            except Exception as e:
                log.debug(f"Watcher callback failed: {e}")

    def start(self):
        if self._running:
            return
        self._running = True
        self.state.status = "watching"
        try:
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._loop())
        except RuntimeError:
            self._task = None
        self._logger(f"👁️ Watcher started — checking every {self.config.check_interval_ms}ms", "success")

    def ensure_task(self):
        if not self.config.enabled:
            return
        if self._task and not self._task.done():
            return
        try:
            loop = asyncio.get_running_loop()
            if not self._running:
                self._running = True
                self.state.status = "watching"
            self._task = loop.create_task(self._loop())
            self._logger(f"👁️ Watcher task ensured — interval {self.config.check_interval_ms}ms", "info")
        except RuntimeError:
            pass

    def stop(self):
        self._running = False
        self.state.status = "idle"
        if self._task:
            self._task.cancel()
            self._task = None
        self._logger("👁️ Watcher stopped", "warn")

    async def _loop(self):
        try:
            while self._running:
                try:
                    await self.check_once()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self._logger(f"Watcher check failed: {e}", "error")
                    log.exception("Watcher loop error")
                await asyncio.sleep(self.config.check_interval_ms / 1000.0)
        except asyncio.CancelledError:
            pass
        finally:
            self.state.status = "idle"

    def _get_cdp(self):
        return self._cdp_getter() if self._cdp_getter else None

    async def _check_captcha(self, cdp) -> bool:
        try:
            return bool(await cdp.is_security_dialog_visible())
        except Exception as e:
            self._logger(f"Watcher captcha check error: {e}", "warn")
            return False

    async def _check_generation(self, cdp):
        try:
            return await cdp.is_generating()
        except Exception as e:
            return False, {"error": str(e)}

    def _pause_jobs(self):
        pause_jobs(self.config, self._job_runner_getter)

    def _resume_jobs(self):
        resume_jobs(self.config, self._job_runner_getter)

    async def _show_overlay(self, cdp, msg, kind, timeout):
        try:
            await cdp.show_watcher_overlay(msg, kind=kind, timeout_sec=timeout)
        except Exception as e:
            self._logger(f"Watcher overlay show failed: {e}", "warn")

    async def _hide_overlay(self, cdp):
        try:
            await cdp.hide_watcher_overlay()
        except Exception:
            pass

    async def _handle_captcha(self, cdp, is_captcha: bool):
        from .watcher_overlay import build_captcha_msg, should_start_captcha_waiting, is_captcha_timeout

        self.state.last_captcha_detected = is_captcha
        if not is_captcha:
            return False
        if should_start_captcha_waiting(self.state.waiting_kind):
            self.state.waiting_since = time.time()
            self.state.waiting_kind = "captcha"
            self.state.captcha_waits += 1
            self.state.status = "waiting_captcha"
            self._logger(f"🛡️ Watcher: Captcha detected — {build_captcha_msg(self.config.captcha_timeout_sec)}, pausing jobs", "warn")
            await self._show_overlay(cdp, "wait for user. Captcha", "captcha", self.config.captcha_timeout_sec)
            self._pause_jobs()
            await self._notify()
        else:
            if is_captcha_timeout(self.state.waiting_since, self.config.captcha_timeout_sec):
                elapsed = int(time.time() - (self.state.waiting_since or time.time()))
                self._logger(f"⏰ Watcher: Captcha timeout {elapsed}s limit {self.config.captcha_timeout_sec}s", "error")
                await self._notify()
        return True

    async def _handle_generation(self, cdp, is_gen: bool, details: Dict[str, Any]):
        from .watcher_overlay import build_generation_msg, should_start_generation_waiting, is_generation_timeout

        self.state.last_generation_details = details
        if not is_gen:
            return False
        if should_start_generation_waiting(self.state.waiting_kind):
            self.state.waiting_since = time.time()
            self.state.waiting_kind = "generation"
            self.state.generation_waits += 1
            self.state.status = "waiting_generation"
            self._logger(f"⏳ Watcher: {build_generation_msg(details, self.config.generation_timeout_sec)}, pausing jobs", "warn")
            await self._show_overlay(cdp, "wait for finish generation", "generation", self.config.generation_timeout_sec)
            self._pause_jobs()
            await self._notify()
        else:
            if is_generation_timeout(self.state.waiting_since, self.config.generation_timeout_sec):
                elapsed = int(time.time() - (self.state.waiting_since or time.time()))
                self._logger(f"⏰ Watcher: Generation timeout {elapsed}s limit {self.config.generation_timeout_sec}s", "error")
                await self._notify()
        return True

    async def _handle_clear_if_needed(self, cdp, is_captcha: bool, is_gen: bool):
        from .watcher_overlay import should_clear_overlay, build_clear_msg

        if not should_clear_overlay(self.state.waiting_kind, is_captcha, is_gen):
            return False
        kind = self.state.waiting_kind
        elapsed = int(time.time() - (self.state.waiting_since or time.time()))
        self._logger(f"✅ Watcher: {build_clear_msg(kind, elapsed)}, resuming", "success")
        await self._hide_overlay(cdp)
        self._resume_jobs()
        self.state.waiting_since = None
        self.state.waiting_kind = None
        self.state.status = "watching"
        await self._notify()
        return True

    async def check_once(self) -> Dict[str, Any]:
        """Single check — orchestrator ≤20 LOC (C1)."""
        self.state.checks_count += 1
        self.state.last_check = time.time()
        cdp = self._get_cdp()
        if not cdp:
            self.state.status = "watching"
            await self._notify()
            return self.get_state()
        is_captcha = await self._check_captcha(cdp)
        if await self._handle_captcha(cdp, is_captcha):
            return self.get_state()
        is_gen, gen_details = await self._check_generation(cdp)
        if await self._handle_generation(cdp, is_gen, gen_details):
            return self.get_state()
        await self._handle_clear_if_needed(cdp, is_captcha, is_gen)
        self.state.status = "watching"
        await self._notify()
        return self.get_state()

    async def force_clear(self):
        cdp = self._cdp_getter() if self._cdp_getter else None
        if cdp:
            try:
                await cdp.hide_watcher_overlay()
            except Exception:
                pass
        self.state.waiting_since = None
        self.state.waiting_kind = None
        self.state.status = "watching"
        await self._notify()
        self._logger("Watcher overlay cleared manually", "info")
