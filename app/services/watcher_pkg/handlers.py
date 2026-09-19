"""Watcher decisions — one page at a time, with CAPTCHA isolated here."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict

from app.services.captcha.signals import CaptchaSignal
from app.services.watcher_captcha import build_request
from app.services.watcher_config import WatcherState


@dataclass
class HandlerDeps:
    """Dependencies for page decisions; no image-job service is accepted."""

    config: Any
    state: Any
    cdp_probe: Any
    job_ctrl: Any
    logger: Callable
    notifier: Callable
    captcha_solver: Any = None


def _as_signal(value: CaptchaSignal | bool) -> CaptchaSignal:
    """Accept the former boolean probe API while using structured signals."""
    return value if isinstance(value, CaptchaSignal) else CaptchaSignal(visible=bool(value))


def _state_for(handler) -> WatcherState:
    """Return persistent state for one tab; legacy callers use aggregate state."""
    page_id = handler._current_page_id
    if not page_id or page_id == "primary":
        return handler.state
    return handler._page_states.setdefault(page_id, WatcherState())


def _aggregate_status(states):
    if any(item.waiting_kind == "captcha" for item in states):
        return "waiting_captcha"
    if any(item.waiting_kind for item in states):
        return "waiting_generation"
    return "watching"


def _sync_state(handler) -> None:
    """Expose a compact aggregate while page state remains independent."""
    states = [handler.state, *handler._page_states.values()]
    waiting = next((item for item in states if item.waiting_kind), None)
    handler.state.waiting_kind = waiting.waiting_kind if waiting else None
    handler.state.waiting_since = waiting.waiting_since if waiting else None
    handler.state.status = _aggregate_status(states)
    handler.state.captcha_waits = sum(item.captcha_waits for item in states)
    handler.state.generation_waits = sum(item.generation_waits for item in states)


def _start_captcha_wait(handler, state: WatcherState) -> None:
    """Record a page wait and pause jobs once for all active pages."""
    state.waiting_since = time.time()
    state.waiting_kind = "captcha"
    state.captcha_waits += 1
    state.status = "waiting_captcha"
    handler._logger("Watcher detected CAPTCHA on the monitored page", "warn")
    if handler.config.auto_pause_jobs and not handler._paused_jobs:
        handler.job_ctrl.pause()
        handler._paused_jobs = True


def _solver_reason(handler, signal: CaptchaSignal) -> str:
    solver = handler._captcha_solver
    if solver is None:
        return "Watcher CAPTCHA requires manual action"
    if not solver.enabled():
        return "Watcher CAPTCHA solver unavailable; manual action required"
    if not signal.solvable:
        return "Watcher CAPTCHA has no supported sitekey; manual action required"
    return ""


async def _solve_if_enabled(handler, cdp, signal: CaptchaSignal) -> str:
    """Call the SDK facade only from an enabled Watcher."""
    reason = _solver_reason(handler, signal)
    if reason:
        handler._logger(reason, "warn")
        return "manual"
    request = build_request(cdp, handler._current_page_id or "primary", signal)
    result = await handler._captcha_solver.solve(request)
    if result.status != "solved":
        handler._logger(f"Watcher CAPTCHA requires manual action: {result.reason}", "warn")
    return result.status


async def _log_captcha_timeout(handler, state: WatcherState) -> None:
    """Report an ongoing wait without restarting it."""
    since = state.waiting_since or time.time()
    if time.time() - since >= handler.config.captcha_timeout_sec:
        elapsed = int(time.time() - since)
        handler._logger(f"Watcher CAPTCHA timeout after {elapsed}s", "error")
        await handler._notify()


async def _finish_page(handler, cdp, state: WatcherState, message: str) -> None:
    """Hide one page overlay and resume after all pages are clear."""
    await handler.cdp_probe.hide_overlay(cdp)
    state.waiting_since = None
    state.waiting_kind = None
    state.status = "watching"
    active = any(item.waiting_kind for item in handler._page_states.values())
    if state is handler.state:
        active = active or bool(handler.state.waiting_kind)
    if handler._paused_jobs and not active:
        handler.job_ctrl.resume()
        handler._paused_jobs = False
    handler._logger(message, "success")
    await handler._notify()


async def _start_generation_wait(handler, cdp, state, details):
    from ..watcher_overlay import build_generation_msg
    state.waiting_since = time.time()
    state.waiting_kind = "generation"
    state.generation_waits += 1
    state.status = "waiting_generation"
    msg = build_generation_msg(details, handler.config.generation_timeout_sec)
    handler._logger(f"Watcher: {msg}", "info")
    await handler.cdp_probe.show_overlay(cdp, "wait for finish generation",
                                         "generation", handler.config.generation_timeout_sec)
    if handler.config.auto_pause_jobs and not handler._paused_jobs:
        handler.job_ctrl.pause()
        handler._paused_jobs = True
    await handler._notify()


async def _handle_generation(handler, cdp, is_gen, details):
    from ..watcher_overlay import should_start_generation_waiting, is_generation_timeout
    state = _state_for(handler)
    state.last_generation_details = details
    if not is_gen:
        return False
    if should_start_generation_waiting(state.waiting_kind):
        await _start_generation_wait(handler, cdp, state, details)
        return True
    if is_generation_timeout(state.waiting_since, handler.config.generation_timeout_sec):
        handler._logger("Watcher generation timeout", "error")
        await handler._notify()
    return True


class WatcherHandlers:
    """Handle passive checks while retaining independent state per tab."""

    def __init__(self, deps: HandlerDeps):
        self.config = deps.config
        self.state = deps.state
        self.cdp_probe = deps.cdp_probe
        self.job_ctrl = deps.job_ctrl
        self._logger = deps.logger
        self._notify = deps.notifier
        self._captcha_solver = deps.captcha_solver
        self._paused_jobs = False
        self._page_states: dict[str, WatcherState] = {}
        self._current_page_id = "primary"

    async def handle_captcha(self, cdp, signal: CaptchaSignal | bool):
        """Show, solve, or leave one page in a manual-required state."""
        signal = _as_signal(signal)
        state = _state_for(self)
        state.last_captcha_detected = signal.visible
        if not signal.visible:
            return False
        if state.waiting_kind == "captcha":
            await _log_captcha_timeout(self, state)
            return True
        _start_captcha_wait(self, state)
        await self.cdp_probe.show_overlay(cdp, "wait for user. Captcha", "captcha",
                                          self.config.captcha_timeout_sec)
        outcome = await _solve_if_enabled(self, cdp, signal)
        if outcome == "solved":
            await _finish_page(self, cdp, state, "Watcher solved CAPTCHA")
        _sync_state(self)
        return True

    async def handle_generation(self, cdp, is_gen: bool, details: Dict[str, Any]):
        """Track generation independently of CAPTCHA for one page."""
        result = await _handle_generation(self, cdp, is_gen, details)
        _sync_state(self)
        return result

    async def handle_clear(self, cdp, signal: CaptchaSignal | bool, is_gen: bool):
        """Clear only this page's overlay after its conditions clear."""
        from ..watcher_overlay import should_clear_overlay, build_clear_msg
        signal = _as_signal(signal)
        state = _state_for(self)
        if not should_clear_overlay(state.waiting_kind, signal.visible, is_gen):
            return False
        kind = state.waiting_kind
        elapsed = int(time.time() - (state.waiting_since or time.time()))
        await _finish_page(self, cdp, state, build_clear_msg(kind, elapsed))
        _sync_state(self)
        return True
