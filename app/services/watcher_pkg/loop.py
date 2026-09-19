"""Watcher loop — check_once orchestration ≤20 LOC, loop ≤30 LOC, params ≤4 via deps."""
from __future__ import annotations
import asyncio
import time
import logging
from dataclasses import dataclass
from typing import Dict, Any, Callable

log = logging.getLogger("watcher")

@dataclass
class LoopDeps:
    config: Any
    state: Any
    cdp_probe: Any
    handlers: Any
    notifier: Callable
    logger: Callable

class WatcherLoop:
    def __init__(self, deps: LoopDeps):
        self.config = deps.config
        self.state = deps.state
        self.cdp_probe = deps.cdp_probe
        self.handlers = deps.handlers
        self._notify = deps.notifier
        self._logger = deps.logger
        self._running = False
        self._task = None
        self._callbacks = []

    def add_callback(self, cb):
        self._callbacks.append(cb)

    async def notify(self):
        state = self.state.to_dict()
        cfg = {
            "enabled": self.config.enabled,
            "check_interval_ms": self.config.check_interval_ms,
            "captcha_timeout_sec": self.config.captcha_timeout_sec,
            "generation_timeout_sec": self.config.generation_timeout_sec,
            "auto_pause_jobs": self.config.auto_pause_jobs,
        }
        payload = {**state, "config": cfg}
        for cb in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(payload)
                else:
                    cb(payload)
            except Exception as e:
                log.debug(f"Watcher callback failed: {e}")

    async def check_once(self) -> Dict[str, Any]:
        self.state.checks_count += 1
        self.state.last_check = time.time()
        cdp = self.cdp_probe.get()
        if not cdp:
            self.state.status = "watching"
            await self._notify()
            return self.state.to_dict()
        is_captcha = await self.cdp_probe.check_captcha(cdp)
        if await self.handlers.handle_captcha(cdp, is_captcha):
            return self.state.to_dict()
        is_gen, gen_details = await self.cdp_probe.check_generation(cdp)
        if await self.handlers.handle_generation(cdp, is_gen, gen_details):
            return self.state.to_dict()
        await self.handlers.handle_clear(cdp, is_captcha, is_gen)
        self.state.status = "watching"
        await self._notify()
        return self.state.to_dict()

    def start(self):
        if self._running:
            return
        self._running = True
        self.state.status = "watching"
        try:
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._run())
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
            self._task = loop.create_task(self._run())
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

    async def _run(self):
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
