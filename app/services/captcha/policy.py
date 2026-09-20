"""Captcha scope policy — the ONE reader of the Watcher switch (I-48, D-23).

"Is captcha work allowed right now?" has exactly one answer: the Watcher
switch. Every pipeline gate (`single_job_runner.check_security`,
`_handle_security`, the settler install in `wait_for_output`, and the
`handle_captcha` choke point) asks `captcha_in_scope`; nothing else reads
`watcher_enabled`. Watcher OFF ⇒ no probe, overlay, pool mark, stat,
recording, penalty, log line or pause — zero captcha activity.

Layer: services. Imports only `.signals`; never ui, never the SDK.
"""
# ideal-size: ~55 lines reason=one decision (scope) plus its two read-only
# companions (loop running, key stored) — a policy file is deliberately
# small so the switch has one owner (RULE 10).

from __future__ import annotations

from typing import Any

from .signals import SolveOutcome


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
