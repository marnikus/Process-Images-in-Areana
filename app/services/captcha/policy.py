"""Captcha scope — one predicate owns "is captcha work allowed now?" (S2, D-23).

Watcher OFF ⇒ captcha out of scope: no probe, overlay, pool mark, stats,
recording, penalty, `🛡` line, pause. The pipeline gates read
`captcha_in_scope`; nothing here starts/stops anything or caches the
switch (it is re-read per call, live in both directions).

Layer: services — imports only the sibling `.signals` (acyclic); services
never import ui (RULE 10: one control per decision — the Watcher switch).
"""

from .signals import SolveOutcome


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
