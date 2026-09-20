"""The ONE reader of the Captcha Watcher switch (D-3, D-23).

Watcher OFF ⇒ captcha is out of scope: no probe, no overlay, no pool mark, no
stats, no recording, no penalty, no log line and (S3) no pause. Watcher ON ⇒ the
pipeline detects and waits; it still never solves (RULE 20) — solving belongs to
`app.services.captcha_watcher`.

# ideal-size: 38 lines reason=one decision (the scope of captcha work); merging it
# into service.py would give that decision a second owner (RULE 10).
Imports: `.signals` only. Services never import `app.ui` (round-1 D-10).
"""
from __future__ import annotations

import time
from typing import Callable

from .signals import SolveOutcome


def watcher_enabled(bridge) -> bool:
    """True only while the user keeps the Watcher switch ON (fail-closed)."""
    try:
        return bool(bridge.config.get_state("watcher_enabled", False))
    except Exception:
        return False


def solver_running(bridge) -> bool:
    """True while the Watcher's solver loop is alive (fail-closed)."""
    watcher = getattr(bridge, "_captcha_watcher", None)
    try:
        return bool(watcher is not None and watcher.running)
    except Exception:
        return False


def has_solver_key(bridge) -> bool:
    """True when a provider key is stored. Never returns or logs the key."""
    try:
        svc = bridge._captcha_service()
        return bool(svc is not None and svc.keys.load().api_key)
    except Exception:
        return False


def captcha_in_scope(bridge) -> bool:
    """The gate every captcha site asks. It is the switch and nothing else."""
    return watcher_enabled(bridge)


def out_of_scope() -> SolveOutcome:
    """What every gate returns while the Watcher is OFF (callers map statuses)."""
    return SolveOutcome(status="out_of_scope", reason="watcher off")


def pause_cap_seconds(bridge) -> int:
    """The ONE knob (D-14R): the generation-pause cap == the captcha wait bound."""
    try:
        raw = float(bridge.config.get_state("watcher_captcha_timeout_sec", 300))
    except Exception:
        return 300
    return int(min(3600, max(10, raw)))


_WAIT_REASONS = {
    True: "Captcha Watcher is solving it (2Captcha SDK)",
    False: "Watcher ON, no 2Captcha key — solve it in Chrome; this job's timeout is paused",
}


def wait_reason(bridge) -> str:
    """The amber overlay line (D-15): who clears the dialog, honestly.

    A running solver HAS a key, so key presence is the switch the words key the
    wording on. Never promises solving without a key, never instructs to turn
    ON a Watcher that can only reach this point because it IS on.
    """
    return _WAIT_REASONS[bool(has_solver_key(bridge))]


class WaitDeadline:
    """Bounds one captcha wait at the cap (D-14R).

    Composed into the `stop` predicate the wait already passes — cooldown's
    `wait_captcha_cleared` keeps its frozen 4-argument seam and its pinned
    "never gives up" behaviour: it is OUR predicate that starts firing.
    """

    def __init__(self, cap_s: float):
        self.cap_s = float(cap_s)
        self.started = time.monotonic()

    def expired(self) -> bool:
        return time.monotonic() - self.started >= self.cap_s

    def stop_or(self, stop: Callable[[], bool] | None) -> Callable[[], bool]:
        """The user's stop, or the cap — composed for one wait."""
        user_stop = stop or (lambda: False)
        return lambda: bool(user_stop()) or self.expired()
