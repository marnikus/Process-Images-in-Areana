"""Captcha policy — scope (I-48, D-23), the wait cap (D-14R) and the wait reason (D-15).

"Is captcha work allowed right now?" has exactly one answer: the Watcher
switch. Every pipeline gate (`single_job_runner.check_security`,
`_handle_security`, the settler install in `wait_for_output`, and the
`handle_captcha` choke point) asks `captcha_in_scope`; nothing else reads
`watcher_enabled`. Watcher OFF ⇒ no probe, overlay, pool mark, stat,
recording, penalty, log line or pause — zero captcha activity.

While ON, the wait is bounded by ONE knob (`watcher_captcha_timeout_sec`):
`pause_cap_seconds` reads it, `pause_budget` bounds it by what the
generation wait's `PauseClock` has left, `WaitDeadline` composes it into
the `stop` predicate `cooldown_service.wait_captcha_cleared` already takes
(that module stays untouched), and `wait_reason` owns the overlay wording.

Layer: services. Imports `.signals` and `app.core`; never ui, never the SDK.
"""
# ideal-size: ~120 lines reason=every captcha decision that is not the wait
# itself lives here so each has one owner (RULE 10): scope, cap, budget,
# deadline, wording. Splitting them would spread the switch over files.

from __future__ import annotations

import time
from typing import Any, Callable

from .signals import SolveOutcome

CAP_MIN_S, CAP_MAX_S, CAP_DEFAULT_S = 10, 3600, 300
_PAUSED = "solve it in Chrome; this job's timeout is paused"
_WAIT_REASONS = {  # (solver loop running, key stored) → what the overlay says (D-15)
    (True, True): "Captcha Watcher is solving it (2Captcha SDK)",
    (True, False): f"Watcher ON, no 2Captcha key — {_PAUSED}",
    (False, True): f"Watcher ON, solver not running — {_PAUSED}",
    (False, False): f"Watcher ON, no 2Captcha key — {_PAUSED}",
}


def watcher_enabled(bridge: Any) -> bool:
    """The Watcher switch, read per call (fail-closed: missing/broken ⇒ False)."""
    try:
        return bool(bridge.config.get_state("watcher_enabled", False))
    except Exception:
        return False


def solver_running(bridge: Any) -> bool:
    """Is the isolated Captcha Watcher loop running on this bridge? (fail closed)."""
    try:
        watcher = getattr(bridge, "_captcha_watcher", None)
        return bool(watcher is not None and watcher.running)
    except Exception:
        return False


def has_solver_key(bridge: Any) -> bool:
    """A solver key is stored — never the key itself (fail closed)."""
    try:
        svc = bridge._captcha_service()
        return bool(svc is not None and svc.keys.load().api_key)
    except Exception:
        return False


def captcha_in_scope(bridge: Any) -> bool:
    """Captcha work is allowed iff the Watcher is ON — the switch and nothing else."""
    return watcher_enabled(bridge)


def out_of_scope() -> SolveOutcome:
    """The choke point's answer while OFF (callers map statuses, never None)."""
    return SolveOutcome(status="out_of_scope", reason="watcher off")


def pause_cap_seconds(bridge: Any) -> int:
    """The one knob (D-14R): `watcher_captcha_timeout_sec`, clamped 10…3600, default 300."""
    try:
        raw = int(bridge.config.get_state("watcher_captcha_timeout_sec", CAP_DEFAULT_S))
    except Exception:
        return CAP_DEFAULT_S
    return max(CAP_MIN_S, min(CAP_MAX_S, raw))


def pause_budget(bridge: Any, ctrl: Any) -> float:
    """Seconds this captcha wait may take: the knob, bounded by the wait's remaining pause (R22)."""
    cap = float(pause_cap_seconds(bridge))
    clock = getattr(ctrl, "pause_clock", None)
    return cap if clock is None else min(cap, float(clock.remaining()))


def wait_reason(bridge: Any) -> str:
    """The overlay's wording while the pipeline waits (in scope only; never a lie about solving)."""
    return _WAIT_REASONS[(solver_running(bridge), has_solver_key(bridge))]


class WaitDeadline:
    """A wall-clock cap composed into the `stop` predicate the wait already accepts (D-14R)."""

    def __init__(self, cap_s: float, clock: Callable[[], float] = time.monotonic):
        self.cap_s = float(cap_s)
        self._clock = clock
        self._start = clock()

    def expired(self) -> bool:
        return self._clock() - self._start >= self.cap_s

    def stop_or(self, stop: Callable[[], bool]) -> Callable[[], bool]:
        """`stop()` (the user) or the cap — whichever comes first ends the wait."""
        return lambda: bool(stop()) or self.expired()
