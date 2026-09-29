"""Per-tab Watcher episodes, terminal page errors and aggregate job pause."""
from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass
from app.utils.page_errors import match_page_error
from .cdp import check_page_error
from .targets import WatcherTarget
from .handlers import HandlerDeps, WatcherHandlers
from .generation import end_generation_on_error
from .jobs_ctrl import WatcherJobCtrl
from .state_publisher import WatcherStatePublisher
from ..watcher_config import WatcherState


@dataclass
class PageMonitor:
    """One worker's Watcher state and its own overlay/error baseline."""
    target: WatcherTarget
    state: WatcherState
    handlers: WatcherHandlers
    error_baseline: str = ""
    error_baseline_ready: bool = False
    available: bool = True

    @property
    def owner_key(self) -> str:
        return f"watcher:{self.target.tab_id}"


class WatcherPages:
    """Coordinates page-local episodes while pausing the run once in aggregate."""

    def __init__(self, deps):
        self.config, self.state = deps.config, deps.state
        self.probe, self.handlers = deps.cdp_probe, deps.handlers
        self._logger, self._notify = deps.logger, deps.notifier
        self._pages: dict[str, PageMonitor] = {}
        self._paused_tabs: set[str] = set()
        self._totals = {"generation_waits": 0, "captcha_waits": 0}
        self._summary = WatcherStatePublisher(self.state, self._totals)

    def set_logger(self, logger) -> None:
        self._logger = logger

    async def check(self, targets: list[WatcherTarget]) -> None:
        """Probe each target, retire vanished pages, then update aggregate state."""
        active = {target.tab_id for target in targets}
        await self._retire_missing(active)
        await asyncio.gather(*(self._check_bounded(target) for target in targets))
        self._sync_pause()
        self._summary.publish(list(self._pages.values()))
        await self._notify()

    async def _check_bounded(self, target: WatcherTarget) -> None:
        """Bound each independent target pass so one frozen page cannot stall the pool."""
        monitor = self._monitor(target)
        client = getattr(target.cdp, "cdp", target.cdp) if target.cdp is not None else None
        if client is None or not getattr(client, "is_connected", True):
            monitor.available = False
            self._log_target(target, "CDP target unavailable; preserving its current episode", "warn")
            return
        monitor.available = True
        try:
            await asyncio.wait_for(self._check_target(target), timeout=15.0)
        except asyncio.TimeoutError:
            self._log_target(target, "Watcher page pass unanswered; preserving its current episode", "warn")
        except Exception as exc:
            self._log_target(target, f"Watcher page pass failed: {exc}", "warn")

    async def _check_target(self, target: WatcherTarget) -> None:
        monitor = self._monitor(target)
        corpus = await _capture_error_baseline(monitor)
        if await _probe_captcha(monitor):
            return
        generating, details = await self.probe.check_generation(target.cdp)
        await _apply_generation_result(monitor, generating, details, corpus)

    def _monitor(self, target: WatcherTarget) -> PageMonitor:
        existing = self._pages.get(target.tab_id)
        if existing is not None:
            existing.target = target
            return existing
        page_config = copy.copy(self.config)
        page_config.auto_pause_jobs = False
        state = WatcherState()
        owner = f"watcher:{target.tab_id}"
        logger = lambda message, level="info": self._log_target(target, message, level)
        page_job_ctrl = WatcherJobCtrl(page_config, self.handlers.job_ctrl._getter)
        deps = HandlerDeps(page_config, state, self.probe, page_job_ctrl,
                           logger, _quiet_notify, owner)
        monitor = PageMonitor(target, state, WatcherHandlers(deps))
        self._pages[target.tab_id] = monitor
        return monitor

    async def _retire_missing(self, active: set[str]) -> None:
        for tab_id in tuple(self._pages):
            if tab_id in active:
                continue
            monitor = self._pages.pop(tab_id)
            self._totals["generation_waits"] += monitor.state.generation_waits
            self._totals["captcha_waits"] += monitor.state.captcha_waits
            await self.probe.hide_overlay(monitor.target.cdp, monitor.owner_key)
            self._logger(f"👁️ Watcher: worker {monitor.target.label} left the pool — its episode cleared", "info")

    def _sync_pause(self) -> None:
        waiting = {tab_id for tab_id, page in self._pages.items()
                   if page.state.waiting_kind in ("captcha", "generation")}
        if waiting and not self._paused_tabs:
            self.handlers.job_ctrl.pause()
        elif self._paused_tabs and not waiting:
            self.handlers.job_ctrl.resume()
        self._paused_tabs = waiting

    def _log_target(self, target: WatcherTarget, message: str, level: str) -> None:
        self._logger(f"[{target.label} {target.tab_id[:12]}] {message}", level)

    async def clear(self) -> None:
        """Remove all Watcher leases and release one aggregate pause if held."""
        for page in tuple(self._pages.values()):
            self._totals["generation_waits"] += page.state.generation_waits
            self._totals["captcha_waits"] += page.state.captcha_waits
            await self.probe.hide_overlay(page.target.cdp, page.owner_key)
        self._pages.clear()
        if self._paused_tabs:
            self.handlers.job_ctrl.resume()
        self._paused_tabs.clear()
        self._summary.publish([])
        self.state.status = "watching"
        self.state.waiting_kind = self.state.waiting_since = None
        await self._notify()


async def _quiet_notify():
    await asyncio.sleep(0)


async def _capture_error_baseline(monitor):
    probe = monitor.handlers.cdp_probe
    corpus = await check_page_error(monitor.target.cdp, probe._logger)
    if corpus is not None and not monitor.error_baseline_ready:
        monitor.error_baseline, monitor.error_baseline_ready = corpus, True
    return corpus


async def _probe_captcha(monitor) -> bool:
    cdp, handlers = monitor.target.cdp, monitor.handlers
    captcha = await handlers.cdp_probe.check_captcha(cdp)
    if captcha is None:
        await _hold_on_captcha_error(monitor, cdp)
        return True
    return bool(await handlers.handle_captcha(cdp, captcha))


async def _hold_on_captcha_error(monitor, cdp) -> None:
    probe, handlers = monitor.handlers.cdp_probe, monitor.handlers
    generating, details = await probe.check_generation(cdp)
    if isinstance(details, dict) and details.get("unanswered"):
        await handlers.handle_generation(cdp, False, details)
    elif monitor.state.waiting_kind == "generation":
        await handlers.handle_generation(cdp, generating, details)
    else:
        monitor.state.last_generation_details = details


async def _apply_generation_result(monitor, generating, details, corpus) -> None:
    handlers, cdp = monitor.handlers, monitor.target.cdp
    if isinstance(details, dict) and details.get("unanswered"):
        await handlers.handle_generation(cdp, False, details)
        return
    if await _handle_generation_error(monitor, generating, corpus):
        return
    if await handlers.handle_generation(cdp, generating, details):
        return
    await handlers.handle_clear(cdp, False, generating)
    if corpus is not None and not generating and monitor.state.waiting_kind is None:
        monitor.error_baseline, monitor.error_baseline_ready = corpus, True


async def _handle_generation_error(monitor, generating, corpus) -> bool:
    if corpus is None:
        return False
    if not monitor.error_baseline_ready:
        monitor.error_baseline, monitor.error_baseline_ready = corpus, True
        return False
    error = match_page_error(corpus, monitor.error_baseline)
    waiting = monitor.state.waiting_kind == "generation"
    starting = generating and monitor.state.waiting_kind is None
    if error and (waiting or starting):
        await end_generation_on_error(monitor.handlers._generation, monitor.target.cdp, error)
        monitor.error_baseline = corpus
        return True
    if not waiting:
        monitor.error_baseline = corpus
    return False
