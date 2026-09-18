"""Per-page passive captcha monitor — the run flow's twin of the watcher.

The watcher rechecks every tick per page and never trusts one bad probe; it
detects captchas reliably. This module ports that principle into a running
job: a per-page asyncio task probes `is_security_dialog_visible` every
PAGE_CHECK_INTERVAL_SEC; on the first visible tick of an encounter it calls
`settle` (the SAME `handle_captcha` choke point every other site uses —
provider auto-solve or manual wait), then stays quiet until the dialog
clears. A cleared-then-visible-again dialog is a NEW encounter.

Fail-open everywhere (RULE 9): probe errors are counted, never acted on; the
monitor self-terminates after MAX_CONSECUTIVE_ERRORS (dead page/CDP must not
leak a polling loop). `SettleGuard` makes boundary checks, the wait-loop
settler, and this monitor mutually exclusive per ctrl — one encounter is
handled exactly once.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

log = logging.getLogger("arena")

PAGE_CHECK_INTERVAL_SEC = 0.5  # the watcher's passive cadence, per page
MAX_CONSECUTIVE_ERRORS = 20  # ~10 s of dead probes → self-terminate (fail open)


class SettleGuard:
    """One captcha encounter at a time per ctrl; extra triggers no-op.

    `busy` is safe to poll; `run(fn)` returns False immediately when a settle
    is already in flight, else runs fn under the lock and returns its result.
    Usable as an async context manager (`async with guard: ...`) as well.
    """

    def __init__(self):
        self._lock = asyncio.Lock()

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    async def __aenter__(self) -> "SettleGuard":
        await self._lock.acquire()
        return self

    async def __aexit__(self, *exc) -> None:
        self._lock.release()

    async def run(self, fn: Callable[[], Any]) -> Any:
        if self._lock.locked():
            return False
        async with self._lock:
            return await fn()


class PageMonitor:
    """Passive per-page probe loop → one settle per captcha encounter."""

    def __init__(self, ctrl: Any, settle: Callable[[], Any],
                 interval: float = PAGE_CHECK_INTERVAL_SEC,
                 report: Optional[Callable[[str, str], None]] = None):
        self._ctrl = ctrl
        self._settle = settle
        self.interval = max(0.05, float(interval))
        self._report = report
        self._task: Optional[asyncio.Task] = None
        self._handled = False  # an encounter is being handled / was just handled
        self._errors = 0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if not self.running:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    def _log(self, msg: str, level: str = "info") -> None:
        try:
            if self._report is not None:
                self._report(msg, level)
                return
        except Exception:
            pass
        try:
            log.info(msg)
        except Exception:
            pass

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            try:
                visible = await self._ctrl.is_security_dialog_visible()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._errors += 1
                if self._errors >= MAX_CONSECUTIVE_ERRORS:
                    self._log(f"🛡️ Page captcha monitor stopped after "
                              f"{MAX_CONSECUTIVE_ERRORS} dead probes (page gone?)", "warn")
                    return
                continue
            self._errors = 0
            if not visible:
                self._handled = False  # encounter over — the next one re-triggers
                continue
            if self._handled:
                continue  # already settling this encounter
            self._handled = True
            try:
                await self._settle()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._log(f"Page monitor settle failed (fail-open): {e}", "warn")


def start_page_monitor(ctrl: Any, settle: Callable[[], Any],
                       interval: float = PAGE_CHECK_INTERVAL_SEC,
                       report: Optional[Callable[[str, str], None]] = None) -> PageMonitor:
    """Create, stash on the ctrl, and start one monitor."""
    monitor = PageMonitor(ctrl, settle, interval=interval, report=report)
    ctrl._captcha_monitor = monitor
    monitor.start()
    return monitor


async def stop_page_monitor(target: Any) -> None:
    """Stop a monitor (or the one stashed on a ctrl); never raises."""
    try:
        monitor = target if isinstance(target, PageMonitor) else getattr(target, "_captcha_monitor", None)
        if monitor is None:
            return
        await monitor.stop()
        if getattr(target, "_captcha_monitor", None) is monitor:
            delattr(target, "_captcha_monitor")
    except Exception:
        pass
