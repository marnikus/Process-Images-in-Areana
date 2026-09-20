"""Captcha scope — one predicate owns "is captcha work allowed now?" (S2, D-23).

Watcher OFF ⇒ captcha out of scope: no probe, overlay, pool mark, stats,
recording, penalty, `🛡` line, pause. The pipeline gates read
`captcha_in_scope`; nothing here starts/stops anything or caches the
switch (it is re-read per call, live in both directions).

Layer: services — imports only the sibling `.signals` (acyclic); services
never import ui (RULE 10: one control per decision — the Watcher switch).
"""

import time
from typing import Callable, Optional

from .signals import SolveOutcome

PAUSE_MIN_S = 10      # D-14R: one knob — watcher_captcha_timeout_sec bounds
PAUSE_MAX_S = 3600    # both the wait and the pause; clamped to a sane range
PAUSE_DEFAULT_S = 300


def watcher_enabled(bridge) -> bool:
    """The Watcher switch (fail closed): session key `watcher_enabled`."""
    try:
        return bool(bridge.config.get_state("watcher_enabled", False))
    except Exception:
        return False


def solver_running(bridge) -> bool:
    """Is the isolated Captcha Watcher loop running on this bridge? (fail closed)."""
    try:
        watcher = getattr(bridge, "_captcha_watcher", None)
        return bool(watcher is not None and watcher.running)
    except Exception:
        return False


def has_solver_key(bridge) -> bool:
    """Has the owner stored a key for the ACTIVE provider? (fail closed)."""
    try:
        fn = getattr(bridge, "_captcha_service", None)
        svc = fn() if fn is not None else None
        settings = svc.keys.load() if svc is not None else None
        return bool(settings is not None and settings.key_for(settings.provider))
    except Exception:
        return False


def captcha_in_scope(bridge) -> bool:
    """One control per decision (RULE 10): scope == the Watcher switch."""
    return watcher_enabled(bridge)


def out_of_scope() -> SolveOutcome:
    """The honest outcome when the Watcher is OFF (RULE 4: empty ≠ broken)."""
    return SolveOutcome(status="out_of_scope", reason="watcher off")


def pause_cap_seconds(bridge) -> int:
    """The one knob (D-14R): `watcher_captcha_timeout_sec`, clamped, fail-safe."""
    try:
        raw = bridge.config.get_state("watcher_captcha_timeout_sec", PAUSE_DEFAULT_S)
        return max(PAUSE_MIN_S, min(PAUSE_MAX_S, int(raw)))
    except Exception:
        return PAUSE_DEFAULT_S


def wait_reason(bridge) -> str:
    """The overlay's WHY line (D-15): never claim solving without a key."""
    if has_solver_key(bridge):
        return "Captcha Watcher is solving it (2Captcha SDK)"
    return ("Watcher ON, no 2Captcha key — solve it in Chrome; "
            "this job's timeout is paused")


class WaitDeadline:
    """One cap for one captcha wait (D-14R): the wait ends at the cap.

    Composed into the `stop` predicate `wait_captcha_cleared` already
    accepts — that module keeps its 4-param signature and its pinned
    never-gives-up behaviour (tests/test_cooldown_service.py:604-618).
    """

    def __init__(self, cap_s: float):
        self.cap_s = float(cap_s)
        self.start = time.monotonic()

    def expired(self) -> bool:
        return self.cap_s > 0 and time.monotonic() - self.start >= self.cap_s

    def stop_or(self, stop: Optional[Callable[[], bool]]) -> Callable[[], bool]:
        """Cap-expiry OR the caller's own stop — whichever comes first."""
        def combined() -> bool:
            return self.expired() or bool(stop is not None and stop())
        return combined
