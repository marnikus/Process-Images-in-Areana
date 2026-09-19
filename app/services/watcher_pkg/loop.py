"""Watcher loop — passive per-page checks with a hard disabled gate."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict

log = logging.getLogger("watcher")


@dataclass
class LoopDeps:
    config: Any
    state: Any
    cdp_probe: Any
    handlers: Any
    notifier: Callable
    logger: Callable


def probe_pages(probe) -> list:
    """Get normalized pages while retaining lightweight test probes."""
    if hasattr(probe, "get_pages"):
        return probe.get_pages()
    cdp = probe.get()
    return [("primary", cdp)] if cdp else []


async def detect_page(probe, cdp):
    """Use structured detection, retaining the old fake-probe seam."""
    if hasattr(probe, "detect_captcha"):
        return await probe.detect_captcha(cdp)
    return await probe.check_captcha(cdp)


async def inspect_pages(loop, pages) -> None:
    """Run independent CAPTCHA and generation decisions for every page."""
    for page_id, cdp in pages:
        loop.handlers._current_page_id = page_id
        signal = await detect_page(loop.cdp_probe, cdp)
        if await loop.handlers.handle_captcha(cdp, signal):
            continue
        is_gen, details = await loop.cdp_probe.check_generation(cdp)
        if await loop.handlers.handle_generation(cdp, is_gen, details):
            continue
        await loop.handlers.handle_clear(cdp, signal, is_gen)


async def publish_watching(loop) -> Dict[str, Any]:
    """Publish passive state unless a page remains in a waiting state."""
    if not loop.state.waiting_kind:
        loop.state.status = "watching"
    await loop._notify()
    return loop.state.to_dict()


class WatcherLoop:
    """Run passive checks only while explicitly enabled."""

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
        cfg = {"enabled": self.config.enabled,
               "check_interval_ms": self.config.check_interval_ms,
               "captcha_timeout_sec": self.config.captcha_timeout_sec,
               "generation_timeout_sec": self.config.generation_timeout_sec,
               "auto_pause_jobs": self.config.auto_pause_jobs}
        payload = {**state, "config": cfg}
        for cb in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(payload)
                else:
                    cb(payload)
            except Exception as exc:
                log.debug(f"Watcher callback failed: {exc}")

    async def check_once(self) -> Dict[str, Any]:
        """Passively inspect every connected page; disabled means no probe."""
        if not self.config.enabled:
            self.state.status = "idle"
            await self._notify()
            return self.state.to_dict()
        self.state.checks_count += 1
        self.state.last_check = time.time()
        pages = probe_pages(self.cdp_probe)
        if not pages:
            return await publish_watching(self)
        await inspect_pages(self, pages)
        return await publish_watching(self)

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
                except Exception as exc:
                    self._logger(f"Watcher check failed: {exc}", "error")
                    log.exception("Watcher loop error")
                await asyncio.sleep(self.config.check_interval_ms / 1000.0)
        except asyncio.CancelledError:
            pass
        finally:
            self.state.status = "idle"
