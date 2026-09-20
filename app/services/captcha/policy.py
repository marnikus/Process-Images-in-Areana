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
