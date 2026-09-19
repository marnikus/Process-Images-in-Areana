# ideal-size: ~150 lines reason=the one gate every solve must pass; gate +
# reasons + audit trail are read as a single unit (RULE 18.2)
"""The **only** captcha choke point in the app (REFACTOR 02).

Contract
--------
1. Captcha solving exists **exclusively** for the Watcher window.
2. Watcher off  -> `solve_if_watcher_on()` returns `skipped(watcher_off)`.
   Nothing is sent to 2captcha, nothing is injected into a page.
3. The job chain (`single_job_runner`, `batch_orchestrator`,
   `multi_page_dispatcher`, `page_pool`, `CHECK_SECURITY` block) **must not
   import the solver at all** — they import `is_solving_enabled()` if they
   need to explain a pause, and otherwise just pause the page.
4. Solving is per page (`tab_id`): one in-flight solve per page, so two tabs
   showing a captcha never share one token.

Import direction: services -> services. No Qt, no browser, no UI.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

from .sdk_client import SdkConfig, SdkSolver
from .signals import CaptchaSignal, SolveOutcome

log = logging.getLogger("captcha.gate")

WATCHER_OFF = "watcher_off"
ALREADY_RUNNING = "solve_already_running_for_page"
DISABLED = "captcha_solving_disabled"


def skipped(reason: str) -> SolveOutcome:
    """Uniform 'we did not solve, and that is fine' result (RULE 9 fail-open)."""
    return SolveOutcome(ok=False, reason=reason, retryable=False, skipped=True)


@dataclass
class GateState:
    """Per-page bookkeeping — small, inspectable, serialisable for the UI."""

    in_flight: Dict[str, float] = field(default_factory=dict)
    last_reason: Dict[str, str] = field(default_factory=dict)
    solved: int = 0
    skipped: int = 0
    failed: int = 0

    def snapshot(self) -> dict:
        return {
            "in_flight": sorted(self.in_flight),
            "solved": self.solved,
            "skipped": self.skipped,
            "failed": self.failed,
            "last_reason": dict(self.last_reason),
        }


class CaptchaGate:
    """Watcher-owned gate. Construct once in `bridge_context.build_context`."""

    def __init__(self,
                 watcher_enabled: Callable[[], bool],
                 settings_getter: Callable[[], SdkConfig],
                 solving_enabled: Callable[[], bool] = lambda: True,
                 logger: Optional[Callable] = None):
        self._watcher_enabled = watcher_enabled
        self._settings = settings_getter
        self._solving_enabled = solving_enabled
        self._log = logger or (lambda msg, level="info": log.info(msg))
        self._lock = threading.Lock()
        self._last_solver: Optional[SdkSolver] = None
        self.state = GateState()

    # ---- read model ----------------------------------------------------
    def is_solving_enabled(self) -> bool:
        """True only when the Watcher window is on *and* solving is armed."""
        return bool(self._watcher_enabled()) and bool(self._solving_enabled())

    def why_disabled(self) -> str:
        if not self._watcher_enabled():
            return WATCHER_OFF
        if not self._solving_enabled():
            return DISABLED
        return ""

    def status(self) -> dict:
        return {"enabled": self.is_solving_enabled(),
                "reason": self.why_disabled(),
                **self.state.snapshot()}

    # ---- the single entry point ----------------------------------------
    def solve_if_watcher_on(self, tab_id: str, sig: CaptchaSignal) -> SolveOutcome:
        """Solve one captcha for one page, or explain why we did not."""
        reason = self.why_disabled()
        if reason:
            return self._record_skip(tab_id, reason)
        if not self._claim(tab_id):
            return self._record_skip(tab_id, ALREADY_RUNNING)
        try:
            return self._run(tab_id, sig)
        finally:
            self._release(tab_id)

    # ---- internals -----------------------------------------------------
    def _claim(self, tab_id: str) -> bool:
        with self._lock:
            if tab_id in self.state.in_flight:
                return False
            self.state.in_flight[tab_id] = time.time()
            return True

    def _release(self, tab_id: str) -> None:
        with self._lock:
            self.state.in_flight.pop(tab_id, None)

    def _record_skip(self, tab_id: str, reason: str) -> SolveOutcome:
        self.state.skipped += 1
        self.state.last_reason[tab_id] = reason
        if reason == WATCHER_OFF:
            self._log("🛡️ Captcha seen but Watcher is OFF — page left to the user", "info")
        return skipped(reason)

    def report(self, task_id: str, good: bool) -> None:
        """Tell 2captcha whether the token worked (refunds bad solves)."""
        if self._last_solver and task_id:
            self._last_solver.report(task_id, good)

    def _run(self, tab_id: str, sig: CaptchaSignal) -> SolveOutcome:
        solver = self._last_solver = SdkSolver(self._settings(), self._log)
        started = time.time()
        outcome = solver.solve(sig)
        took = round(time.time() - started, 1)
        if outcome.ok:
            self.state.solved += 1
            self.state.last_reason[tab_id] = "solved"
            self._log(f"✅ Captcha solved for tab {tab_id[:8]} in {took}s", "success")
        else:
            self.state.failed += 1
            self.state.last_reason[tab_id] = outcome.reason
            self._log(f"❌ Captcha solve failed for tab {tab_id[:8]}: {outcome.reason}", "error")
        outcome.tab_id = tab_id
        outcome.duration_sec = took
        return outcome


_GATE: Optional[CaptchaGate] = None


def install_gate(gate: CaptchaGate) -> CaptchaGate:
    """Register the process-wide gate (called once, from the bridge context)."""
    global _GATE
    _GATE = gate
    return gate


def current_gate() -> Optional[CaptchaGate]:
    return _GATE


def is_solving_enabled() -> bool:
    """Safe for any layer to import — False when no gate is installed."""
    return bool(_GATE and _GATE.is_solving_enabled())
