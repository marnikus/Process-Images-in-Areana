"""The Firefox job lane (I-64): one Ui.Vision macro per machine, then an honest verdict.

`run_uivision_job` is what the dispatcher calls for a page whose lane is `uivision`:
1. wait for the machine gate (one macro at a time; the next starts `delay` seconds
   after the previous one finished — shared with the framework test);
2. plan the run in a worker thread (a fresh session read locates the tab);
3. run it (provision → scoped foreground → launch → savelog);
4. answer `(failed, error)` for the image.

The image is always marked failed (owner decision 2026-09-25): a Ui.Vision macro
produces no output image yet, so even an ok macro says exactly that. Stop (the
run's cancel, or the tab's own Stop) ends the wait and the poll (RULE 7).

The service never imports `app.ui`: the planner and runner arrive in
`UiVisionDeps`, built in ui land (`app/ui/panels/firefox_pool.py`).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.browser.page_pool import tab_label_of
from app.core.tab_alias import CONN_UIVISION, page_conn

from .cooldown_service import is_tab_aborted

POLL_SEC = 0.25
OK_NO_OUTPUT = ("Firefox macro finished OK — no output saved "
                "(image processing via Ui.Vision not implemented yet)")


@dataclass
class UiVisionDeps:
    """What ui land hands the lane (fakes replace it in tests)."""

    plan: Callable[[str], Any]                          # tab id → PoolJob | refusal text (blocking)
    run: Callable[[Any, Callable, Callable], Awaitable[Any]]   # (job, report, stop) → RunResult
    delay_sec: Callable[[], float]                      # the user's inter-run delay


class UiVisionGate:
    """One Ui.Vision macro per machine; the next may start `delay` s after the last one finished.

    Every holder runs on the app's single event loop, so a flag plus a
    "free at" stamp is the whole lock (no thread ever touches it).
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic, sleep=None) -> None:
        self._clock = clock
        self._sleep = sleep or asyncio.sleep
        self._held = False
        self._free_at = 0.0

    @property
    def busy(self) -> bool:
        """A macro runs, or the inter-run delay after the last one has not passed yet."""
        return self._held or self._clock() < self._free_at

    async def acquire(self, stop: Callable[[], bool]) -> bool:
        """Wait for the gate; False when `stop()` turned true first (nothing is held then)."""
        while self.busy:
            if stop():
                return False
            await self._sleep(POLL_SEC)
        self._held = True
        return True

    def release(self, delay_sec: float) -> None:
        """Free the gate; the next holder waits `delay_sec` from now."""
        self._held = False
        self._free_at = self._clock() + max(0.0, float(delay_sec or 0))


def is_uivision_page(pool, tab_id: str) -> bool:
    """True for a pooled page whose lane is `uivision` (a Firefox tab); False when unknown."""
    try:
        page = pool.get_page(tab_id)
    except AttributeError:
        return False
    return page is not None and page_conn(getattr(page, "browser", ""), tab_id) == CONN_UIVISION


def has_uivision_page(pool, allowed) -> bool:
    """Does the checked set hold a Firefox page? Then no CDP socket is needed to run (I-64)."""
    return any(is_uivision_page(pool, tab_id) for tab_id in (allowed or ()))


def uivision_gate(bridge) -> UiVisionGate:
    """The machine-wide gate on the bridge (created on first use)."""
    gate = getattr(bridge, "_uivision_gate", None)
    if gate is None:
        gate = bridge._uivision_gate = UiVisionGate()
    return gate


def verdict_error(result: Any) -> str:
    """The image's error text for one run verdict — always a named reason (RULE 4)."""
    kind = str(getattr(result, "kind", "") or "error")
    message = str(getattr(result, "message", "") or "")
    if kind == "ok":
        return OK_NO_OUTPUT
    if kind == "stopped":
        return f"Cancelled — Firefox macro stopped ({message})"
    return f"Firefox macro {kind}: {message}"


def _stop_check(bridge, tab_id: str) -> Callable[[], bool]:
    pool = getattr(bridge, "_page_pool", None)
    return lambda: bool(getattr(bridge, "_cancel_requested", False)) or is_tab_aborted(pool, tab_id)


def _reporter(bridge, label: str) -> Callable:
    def report(step: str, message: str, level: str = "info") -> None:
        bridge._log(f"🦊 {label} · {step}: {message}", level)
    return report


async def _run_held(bridge, deps: UiVisionDeps, tab_id: str, stop) -> tuple:
    """Plan (thread) → run; the gate is held by the caller."""
    label = tab_label_of(getattr(bridge, "_page_pool", None), tab_id)
    job = await asyncio.get_running_loop().run_in_executor(None, deps.plan, tab_id)
    if isinstance(job, str):
        bridge._log(f"🦊 {label}: not run — {job}", "error")
        return True, f"Firefox job not run — {job}"
    result = await deps.run(job, _reporter(bridge, label), stop)
    return True, verdict_error(result)


async def run_uivision_job(bridge, tab_id: str) -> tuple:
    """(failed, error) for the image after one Ui.Vision macro on `tab_id`."""
    deps = getattr(bridge, "_uivision_deps", None)
    if deps is None:
        return True, "Firefox lane is not wired (no Ui.Vision deps on the bridge)"
    gate, stop = uivision_gate(bridge), _stop_check(bridge, tab_id)
    if gate.busy:
        label = tab_label_of(getattr(bridge, "_page_pool", None), tab_id)
        bridge._log(f"🦊 {label}: waiting for the Ui.Vision slot (one macro at a time)", "info")
    if not await gate.acquire(stop):
        return True, "Cancelled while waiting for the Ui.Vision slot"
    try:
        return await _run_held(bridge, deps, tab_id, stop)
    finally:
        gate.release(deps.delay_sec())
