"""Watcher service facade — C13 P2 split into state/loop/cdp/handlers/jobs_ctrl, RULE18 file ≤150, methods ≤10."""
from __future__ import annotations
import logging
from typing import Callable, Dict, Any

from .watcher_config import WatcherConfig, WatcherState
from .watcher_pkg.cdp import WatcherCDP
from .watcher_pkg.jobs_ctrl import WatcherJobCtrl
from .watcher_pkg.handlers import WatcherHandlers, HandlerDeps
from .watcher_pkg.loop import WatcherLoop, LoopDeps

log = logging.getLogger("watcher")

class WatcherService:
    """Facade delegating to loop/cdp/handlers/job_ctrl — ≤10 methods, ≤150 LOC."""

    def __init__(self, config: WatcherConfig = None, cdp_controller_getter: Callable = None, job_runner_getter: Callable = None, logger: Callable = None):
        self.config = config or WatcherConfig()
        self.state = WatcherState()
        self._logger = logger or (lambda msg, level="info": log.info(msg))
        self._cdp_probe = WatcherCDP(cdp_controller_getter, self._logger)
        self._job_ctrl = WatcherJobCtrl(self.config, job_runner_getter)
        h_deps = HandlerDeps(config=self.config, state=self.state, cdp_probe=self._cdp_probe, job_ctrl=self._job_ctrl, logger=self._logger, notifier=self._notify_proxy)
        self._handlers = WatcherHandlers(h_deps)
        l_deps = LoopDeps(config=self.config, state=self.state, cdp_probe=self._cdp_probe, handlers=self._handlers, notifier=self._notify_proxy, logger=self._logger)
        self._loop = WatcherLoop(l_deps)

    async def _notify_proxy(self):
        await self._loop.notify()

    def set_cdp_getter(self, getter: Callable):
        self._cdp_probe._cdp_getter = getter

    def set_job_runner_getter(self, getter: Callable):
        self._job_ctrl.set_getter(getter)

    def set_logger(self, logger: Callable):
        self._logger = logger
        self._cdp_probe._logger = logger
        self._loop._logger = logger
        self._handlers._logger = logger

    def update_config(self, **kwargs):
        for k, v in kwargs.items():
            if hasattr(self.config, k):
                setattr(self.config, k, v)
        self._logger(f"Watcher config updated: interval={self.config.check_interval_ms}ms captcha_timeout={self.config.captcha_timeout_sec}s gen_timeout={self.config.generation_timeout_sec}s enabled={self.config.enabled}", "info")
        if self.config.enabled and not self._loop._running:
            self.start()
        elif not self.config.enabled and self._loop._running:
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
        self._loop.add_callback(cb)

    def start(self):
        self._loop.start()

    def ensure_task(self):
        self._loop.ensure_task()

    def stop(self):
        self._loop.stop()

    async def check_once(self) -> Dict[str, Any]:
        return await self._loop.check_once()

    async def force_clear(self):
        pages = self._cdp_probe.get_pages()
        for _page_id, cdp in pages:
            try:
                await cdp.hide_watcher_overlay()
            except Exception:
                pass
        self.state.waiting_since = None
        self.state.waiting_kind = None
        self.state.status = "watching"
        await self._loop.notify()
        self._logger("Watcher overlay cleared manually", "info")
