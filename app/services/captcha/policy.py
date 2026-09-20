"""Captcha policy — the ONE reader of the Watcher switch (S2, RULE 10).

Scope question: "is pipeline captcha work allowed right now?" The answer is
the Watcher switch (`watcher_enabled`) and nothing else — never the stored
key, never the solver loop. Those two only change the *wording* of a wait.

Watcher OFF ⇒ the pipeline performs no captcha activity of any kind: no
probe, no `waiting_captcha` row, no stat, recording, overlay, penalty or
🛡 line (D-23). Watcher ON ⇒ detect and wait only; the isolated Captcha
Watcher (`app.services.captcha_watcher`) remains the sole solver (RULE 20).

S3 adds the wait's *bound*: `pause_cap_seconds` (the one knob,
`watcher_captcha_timeout_sec`, D-14R), `wait_reason` (D-15 wording) and
`WaitDeadline` — the cap composed into the `stop` predicate that
`wait_captcha_cleared` already takes, so that function stays untouched.

Imports: stdlib + same package (`.signals`) only. Services never import
panels. Every reader fails closed (a broken config means OFF / default).
"""

from __future__ import annotations

import time
from typing import Callable

from .signals import SolveOutcome

CAP_MIN_S, CAP_MAX_S, CAP_DEFAULT_S = 10, 3600, 300

# (has a solver key) → who is expected to clear the dialog (RULE 19: a lookup, not a chain)
_WAIT_REASON = {
    True: "Captcha Watcher is solving it (2Captcha SDK) — generation timeout paused",
    False: "solve it in Chrome — the Watcher has no solver key; generation timeout paused",
}


def watcher_enabled(bridge) -> bool:
    """The Watcher switch, read live on every call (no cache, fail closed)."""
    try:
        return bool(bridge.config.get_state("watcher_enabled", False))
    except Exception:
        return False


def captcha_in_scope(bridge) -> bool:
    """One control per decision: pipeline captcha work is allowed iff the switch is ON."""
    return watcher_enabled(bridge)


def solver_running(bridge) -> bool:
    """Is the isolated Captcha Watcher loop running? Wording only — never scope."""
    try:
        watcher = getattr(bridge, "_captcha_watcher", None)
        return bool(watcher is not None and watcher.running)
    except Exception:
        return False


def has_solver_key(bridge) -> bool:
    """Is a solver key stored for the active provider? Wording only — the key is never read out."""
    try:
        svc = bridge._captcha_service()
        return bool(svc.keys.load().api_key)
    except Exception:
        return False


def out_of_scope() -> SolveOutcome:
    """The outcome `handle_captcha` returns without touching the page (Watcher OFF)."""
    return SolveOutcome(status="out_of_scope", reason="watcher off")


def pause_cap_seconds(bridge) -> int:
    """The one captcha-wait knob (`watcher_captcha_timeout_sec`), clamped 10…3600, default 300."""
    try:
        value = int(bridge.config.get_state("watcher_captcha_timeout_sec", CAP_DEFAULT_S))
    except Exception:
        return CAP_DEFAULT_S
    return max(CAP_MIN_S, min(CAP_MAX_S, value))


def wait_reason(bridge) -> str:
    """Overlay WHY line while in scope: names the solver only when a key exists (D-15)."""
    return _WAIT_REASON[has_solver_key(bridge)]


class WaitDeadline:
    """The cap as a predicate: composes into the `stop` the wait already honours."""

    def __init__(self, cap_s: float):
        self.cap_s = float(cap_s)
        self.start = time.monotonic()

    def expired(self) -> bool:
        return time.monotonic() - self.start >= self.cap_s

    def stop_or(self, stop: Callable[[], bool] | None) -> Callable[[], bool]:
        """A predicate that is True on the caller's stop OR at the cap."""
        return lambda: bool(stop and stop()) or self.expired()
