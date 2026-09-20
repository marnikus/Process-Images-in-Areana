"""Watcher-scope policy: the one predicate that owns the switch (S2).

Scope IS the switch — solver/key state only affects wording (S3), never scope.
Import direction: this module imports `.signals` only (same package, acyclic);
services never import panels.
"""

from __future__ import annotations

import time
from typing import Any

from .signals import SolveOutcome


def watcher_enabled(bridge: Any) -> bool:
    """The Watcher switch; missing/raising config reads OFF (fail closed)."""
    try:
        return bool(bridge.config.get_state("watcher_enabled", False))
    except Exception:
        return False


def solver_running(bridge: Any) -> bool:
    """The isolated Watcher loop runs on this bridge (fail closed)."""
    try:
        return bool(getattr(bridge, "_captcha_watcher", None).running)
    except Exception:
        return False


def has_solver_key(bridge: Any) -> bool:
    """A stored solver key exists (bool only — the key is never logged)."""
    try:
        return bool(bridge._captcha_service().keys.load().api_key)
    except Exception:
        return False


def captcha_in_scope(bridge: Any) -> bool:
    """Scope IS the switch — key/loop state never widen it (RULE 10)."""
    return watcher_enabled(bridge)


def out_of_scope() -> SolveOutcome:
    """The OFF outcome: callers map statuses, never None."""
    return SolveOutcome(status="out_of_scope", reason="watcher off")


def pause_cap_seconds(bridge: Any) -> int:
    """The captcha cap knob for the pause budget, clamped 10…3600 (default 300)."""
    try:
        raw = int(bridge.config.get_state("watcher_captcha_timeout_sec", 300))
    except Exception:
        return 300
    return max(10, min(3600, raw))


def wait_reason(bridge: Any) -> str:
    """Overlay WHY line: solving words only with a key AND a running loop (D-15)."""
    if has_solver_key(bridge) and solver_running(bridge):
        return "Captcha Watcher is solving it (2Captcha SDK)"
    return "solve it in Chrome — the generation timeout is paused while you solve"


class WaitDeadline:
    """Cap deadline composed into the wait's stop predicate (D-14R)."""

    def __init__(self, cap_s: float) -> None:
        self.cap_s = float(cap_s)
        self.start = time.monotonic()

    def expired(self) -> bool:
        """True once cap_s seconds have elapsed since construction."""
        return time.monotonic() - self.start >= self.cap_s

    def stop_or(self, stop):
        """stop OR the cap, with this deadline attached for outcome mapping."""
        deadline = self

        def wrapped() -> bool:
            if stop is not None and stop():
                return True
            return deadline.expired()

        wrapped.deadline = self
        return wrapped
