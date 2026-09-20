"""Watcher-scope policy: the one predicate that owns the switch (S2).

Scope IS the switch — solver/key state only affects wording (S3), never scope.
Import direction: this module imports `.signals` only (same package, acyclic);
services never import panels.
"""

from __future__ import annotations

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
