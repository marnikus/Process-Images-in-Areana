"""Who holds the reconciler's pass flag, and what ending a pass owes the queue.

A stdlib-only leaf, deliberately: `cooldown_service` imports the I-79 handover, and
the handover has to be able to END a pass without dragging the reconciler in.
When it reached for `live.reconcile` directly the import closed a cycle —
`cooldown_service → new_tab → live.reconcile → reconcile_rows → run_state →
cooldown_service` — and `import app.services.cooldown_service` started failing
outright (audit #4 N7, found by the full suite, not by the focused one).

So the flag and the queue live here, and the pass itself is injected by the one
caller that has it.

Two writers of `_auto_scan_running` exist and are not allowed to drift: the
reconciler's own `reconcile_once`, and the new-tab handover. Both acquire here
and both release here. Releasing owes the queue: a manual Reparse that met a
running holder is queued with the log line "runs right after the current pass",
and I-68(a) is a promise about the moment that pass ends — so whoever ends it
must be the one that fires it (N1).

RULE 18: file ~60, func 4-20 LOC, imports stdlib only.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

FLAG = "_auto_scan_running"
QUEUED = "_reparse_queued"
DRAIN = "_reparse_drain"


def is_held(bridge) -> bool:
    """True while any holder — a reconcile pass or a new-tab handover — owns the flag."""
    return bool(getattr(bridge, FLAG, False))


def take(bridge) -> None:
    """Claim the flag. Check-then-take must stay await-free to stay atomic on one loop."""
    setattr(bridge, FLAG, True)


def release(bridge) -> None:
    """The ONE place a holder gives the flag up, and it owes the queue a run (N1).

    With no drain installed there is nothing to run the queued pass into, and the
    flag is still released: the queue then waits for the next pass, exactly as it
    did before this function existed. No failure mode is added, only one removed.
    """
    setattr(bridge, FLAG, False)
    if not getattr(bridge, QUEUED, False):
        return
    drain = getattr(bridge, DRAIN, None)
    if drain is None:
        return
    setattr(bridge, QUEUED, False)
    drain()


def install_drain(bridge, run_pass: Callable[[], Awaitable]) -> None:
    """Teach `release()` how to run a pass. `run_pass` is the caller's own, so this
    leaf never has to import the reconciler to start one."""
    setattr(bridge, DRAIN, lambda: asyncio.ensure_future(run_pass()))


def is_queued(bridge) -> bool:
    return bool(getattr(bridge, QUEUED, False))


def mark_queued(bridge) -> bool:
    """Queue a manual pass; False when one is already queued (log it once, not twice)."""
    if is_queued(bridge):
        return False
    setattr(bridge, QUEUED, True)
    return True


def clear_queued(bridge) -> None:
    setattr(bridge, QUEUED, False)
