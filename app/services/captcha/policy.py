"""Captcha policy — the ONE reader of the Watcher switch (S2, RULE 10).

Scope question: "is pipeline captcha work allowed right now?" The answer is
the Watcher switch (`watcher_enabled`) and nothing else — never the stored
key, never the solver loop. Those two only change the *wording* of a wait.

Watcher OFF ⇒ the pipeline performs no captcha activity of any kind: no
probe, no `waiting_captcha` row, no stat, recording, overlay, penalty or
🛡 line (D-23). Watcher ON ⇒ detect and wait only; the isolated Captcha
Watcher (`app.services.captcha_watcher`) remains the sole solver (RULE 20).

Imports: same package (`.signals`) only. Services never import panels.
Every reader fails closed (a broken config means OFF).
"""

from __future__ import annotations

from .signals import SolveOutcome


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
