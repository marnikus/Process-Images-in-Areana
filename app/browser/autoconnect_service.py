"""Auto-connect scheduling — when a detection pass runs (spec 03).

``AutoConnectService`` performs one pass (fetch → select → link → publish).
``ScanScheduler`` repeats it: once immediately on start, then on a timer, and
early whenever Chrome reports a new-tab event. RULE 7 — ``halt()``/``stop()``
are honoured while scanning and while waiting, so closing the app is prompt.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .autoconnect_config import AutoConnectConfig, config_from_getter
from .autoconnect_linker import PageLinker
from .autoconnect_match import select_pages
from .autoconnect_report import startup_message, summarize_scan
from .tab_events import TabEventWatcher

log = logging.getLogger("arena")

Fetcher = Callable[[], Awaitable[List[Any]]]
StatusSink = Callable[[Dict[str, Any]], Any]
Logger = Callable[[str, str], None]


def _noop_log(_msg: str, _level: str = "info") -> None:
    return None


def _in_loop_thread(loop: Optional[asyncio.AbstractEventLoop]) -> bool:
    try:
        return asyncio.get_running_loop() is loop
    except RuntimeError:
        return False


@dataclass
class ServiceHooks:
    """Where a pass reports to: UI signal sink and log writer."""

    on_status: Optional[StatusSink] = None
    logger: Optional[Logger] = None

    def log(self, msg: str, level: str = "info") -> None:
        try:
            (self.logger or _noop_log)(msg, level)
        except Exception as e:  # a broken logger must not break linking
            log.debug(f"auto-connect log failed: {e}")

    def publish(self, report: Dict[str, Any]) -> None:
        if not self.on_status:
            return
        try:
            self.on_status(report)
        except Exception as e:  # UI callback must never kill the pipeline (RULE 5)
            log.warning(f"auto-connect status callback failed: {e}")


class AutoConnectService:
    """One detection + linking pass over the configured CDP endpoint."""

    def __init__(
        self,
        fetch_tabs: Fetcher,
        linker: PageLinker,
        config: Optional[AutoConnectConfig] = None,
        hooks: Optional[ServiceHooks] = None,
    ):
        self._fetch_tabs = fetch_tabs
        self.linker = linker
        self.config = config or AutoConnectConfig()
        self.hooks = hooks or ServiceHooks()
        self._last_result: Dict[str, Any] = {}

    def reload_config(self, get: Callable[[str, Any], Any]) -> AutoConnectConfig:
        """Re-read the stored settings (host, port, pattern, interval, limits)."""
        self.config = config_from_getter(get)
        return self.config

    @property
    def last_report(self) -> Dict[str, Any]:
        return dict(self._last_result)

    async def scan_once(self, reason: str = "manual") -> Dict[str, Any]:
        """Fetch pages, link matches, drop the ones that went away, publish."""
        selection = await self._fetch_selection(self.config)
        report = await self.linker.reconcile(selection, reason=reason)
        report.update(
            {
                "endpoint": self.config.endpoint,
                "enabled": bool(self.config.enabled),
                "url_pattern": self.config.url_pattern,
                "interval_ms": self.config.interval_ms,
            }
        )
        self._last_result = report
        self.hooks.publish(report)
        msg, level = summarize_scan(report)
        self.hooks.log(msg, level)
        return report

    async def _fetch_selection(self, cfg: AutoConnectConfig):
        try:
            tabs = await self._fetch_tabs()
        except Exception as e:  # broken, not empty (RULE 4)
            sel = select_pages([], cfg.patterns, cfg.max_pages)
            sel.error = str(e)
            return sel
        return select_pages(tabs or [], cfg.patterns, cfg.max_pages)


class ScanScheduler:
    """Repeats a service pass: on start, on a timer, and on new-tab events."""

    def __init__(self, service: AutoConnectService, watcher_factory=None):
        self.service = service
        self._watcher_factory = watcher_factory or self._default_watcher
        self._task: Optional[asyncio.Task] = None
        self._watcher: Optional[TabEventWatcher] = None
        self._wake: Optional[asyncio.Event] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stopping = False

    @property
    def running(self) -> bool:
        return bool(self._task and not self._task.done())

    async def run(self) -> None:
        """Start the loop; a second call is a no-op while one is running."""
        if self.running:
            return
        self._loop = asyncio.get_event_loop()
        self._wake = asyncio.Event()
        self._task = asyncio.ensure_future(self._cycle())
        self._start_watcher()
        try:
            await self._task
        finally:
            self._stop_watcher()

    async def _cycle(self) -> None:
        hooks = self.service.hooks
        hooks.log(startup_message(self.service.config), "success")
        while True:
            try:
                await self.service.scan_once(reason="loop")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                hooks.log(f"⚠ Auto-connect scan crashed: {e}", "error")
            if not await self._wait_interval():
                break
        hooks.log("🤖 Auto-connect stopped", "warn")

    async def _wait_interval(self) -> bool:
        """Sleep until the next pass; False once a stop was requested."""
        if self._wake is None:
            self._wake = asyncio.Event()
        seconds = max(0.5, self.service.config.interval_ms / 1000.0)
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass
        self._wake.clear()
        return not self._stopping

    def request_scan(self, reason: str = "event") -> None:
        """Wake the loop early — safe from the watcher thread or the UI thread."""
        wake = self._wake
        if wake is None:
            return
        try:
            loop = self._loop
            if loop and loop.is_running() and not _in_loop_thread(loop):
                loop.call_soon_threadsafe(wake.set)
            else:
                wake.set()
        except Exception as e:
            log.debug(f"request_scan({reason}) failed: {e}")

    def halt(self) -> Optional[asyncio.Task]:
        """Non-awaiting stop (app shutdown): cancel the loop, close event stream."""
        self._stopping = True
        self.request_scan("halt")
        self._stop_watcher()
        task, self._task = self._task, None
        if task and not task.done():
            task.cancel()
            return task
        return None

    async def stop(self) -> None:
        task = self.halt()
        if task:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                log.debug(f"auto-connect loop exit: {e}")
        self._stopping = False
        self.service.hooks.publish({**self.service.last_report, "running": False, "reason": "stopped"})

    def _default_watcher(self) -> TabEventWatcher:
        cfg = self.service.config
        return TabEventWatcher(
            cfg.endpoint,
            on_event=lambda kind: self.request_scan(kind),
            logger=self.service.hooks.log,
        )

    def _start_watcher(self) -> None:
        try:
            watcher = self._watcher_factory()
            self._watcher = watcher if watcher and watcher.start() else None
        except Exception as e:  # events are a bonus — the timer still runs
            self._watcher = None
            log.debug(f"tab event watcher unavailable: {e}")

    def _stop_watcher(self) -> None:
        watcher, self._watcher = self._watcher, None
        if watcher:
            try:
                watcher.stop()
            except Exception as e:
                log.debug(f"tab event watcher stop failed: {e}")
