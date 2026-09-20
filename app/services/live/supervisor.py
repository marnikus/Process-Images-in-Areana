"""The always-live run (S5, D-5 / D-8, I-47).

`run_live` replaces "one batch then idle". Each turn of the loop plans a
pass from a fresh read (`plan_pass`: claimable images, enabled URL rows, the
tab a checked row owns); when there is nothing to do — no work, no usable
tab, Chrome down — the loop logs one throttled line and waits on the S4 bus
(any queue commit, URL commit or pool change wakes it; `WAIT_S` bounds the
wait so time-based changes such as a cooldown ending are seen too). The run
ends only on Stop-after-current or Cancel. The pass body is unchanged: the
orchestrator's `prepare_batch → _try_parallel → _await_batch_gate →
_run_sequential` lane, which has no lifecycle opinion any more.

`set_run_state` is the ONLY writer of `bridge._run_state` (and of the
persisted `AppState.run_state`, L-2). Layer: services → services/core.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from app.services import auto_connect as ac
from app.services import batch_orchestrator as bo

from .bus import LiveBus, live_bus
from .feed import eligible_images

WAIT_S = 1.0            # one bus wait; time-based changes (cooldowns) are re-planned at this cadence
WAIT_LINE_MS = 30_000   # one status line per reason per window

REASON_LINES = {  # wait reason → (line template, level); a lookup, never an if/elif chain (RULE 19)
    "no_work": ("🟢 Run live — {n} queued images; waiting for work (Reset / Retry / scan re-queues)", "info"),
    "no_tab": ("🟡 Run live — {n} queued, no usable checked tab in pool — check a URL row linked to a live tab — pool: {pool}", "warn"),
    "cdp_down": ("🔴 Run live — {n} queued, Chrome not connected — waiting for CDP", "error"),
}


@dataclass
class PassPlan:
    """What one pass would do, read fresh (never carries the bridge)."""

    images: list = field(default_factory=list)
    urls: list = field(default_factory=list)
    allowed: set = field(default_factory=set)
    tab_id: str = ""
    reason: str = ""    # "" = work to do; else a REASON_LINES key


@dataclass
class LiveState:
    """Observable loop state for the debug view (S9) and the harness."""

    reason: str = ""    # current wait reason, "" while a pass runs / before the first plan
    passes: int = 0
    last_pass_at: float = 0.0


def live_state(bridge: Any) -> LiveState:
    state = getattr(bridge, "_live_state", None)
    if state is None:
        state = bridge._live_state = LiveState()
    return state


def set_run_state(bridge: Any, value: str) -> None:
    """The one writer (D-8): the runtime flag and the persisted AppState field move together (L-2)."""
    bridge._run_state = value
    try:
        bridge.state.run_state = value
    except Exception:
        pass


def is_live(bridge: Any) -> bool:
    """The flags are the truth: neither Cancel nor Stop-after-current has been asked."""
    return not getattr(bridge, "_cancel_requested", False) and not getattr(bridge, "_stop_after", False)


def _cdp_connected(bridge: Any) -> bool:
    cdp = getattr(bridge, "cdp", None)
    return bool(cdp is not None and getattr(cdp, "is_connected", True))


def _current_tab(bridge: Any) -> str:
    return getattr(bridge.cdp, "_current_tab_id", "") or ""


async def plan_pass(bridge: Any) -> PassPlan:
    """Fresh read: claimable images, enabled rows, the checked tab — or the reason to wait."""
    urls = [u for u in bridge.state.urls if u.enabled]
    plan = PassPlan(images=eligible_images(bridge.state.images), urls=urls, allowed=ac.enabled_tab_ids(urls))
    if not plan.images:
        plan.reason = "no_work"
    elif not _cdp_connected(bridge):
        plan.reason = "cdp_down"
    else:
        plan.tab_id = await bo.resolve_and_claim_tab(bridge, _current_tab(bridge), plan.allowed)
        plan.reason = "" if plan.tab_id else "no_tab"
    return plan


async def wait_reason(bridge: Any, plan: PassPlan, bus: LiveBus) -> None:
    """One throttled line per reason, then wait for a wake (or `WAIT_S`) — never end the run."""
    live_state(bridge).reason = plan.reason
    template, level = REASON_LINES[plan.reason]
    if bus.throttle(plan.reason, WAIT_LINE_MS):
        bridge._log(template.format(n=len(plan.images), pool=bo._pool_summary(bo._pool_of(bridge))), level)
    await bus.wait(WAIT_S)


async def run_pass(bridge: Any, plan: PassPlan) -> None:
    """One pass through the existing lane; the sequential/parallel decision stays in the orchestrator."""
    state = live_state(bridge)
    state.reason = ""
    ctx = await bo.prepare_batch(bridge, plan)
    if not await bo._try_parallel(ctx) and await bo._await_batch_gate(ctx):
        await bo._run_sequential(ctx)
    state.passes += 1
    state.last_pass_at = time.time()
    pass_tail(bridge, plan)


def pass_tail(bridge: Any, plan: PassPlan) -> None:
    """Log-only end of a pass (the run stays live)."""
    left = len(eligible_images(bridge.state.images))
    bridge._log(f"✅ Pass complete — {len(plan.images)} planned, {left} still queued", "info")


def end_tail(bridge: Any) -> None:
    """The run ended by itself (Stop-after-current or a cancel flag seen between images)."""
    if getattr(bridge, "_cancel_requested", False):
        bridge._log("🏁 Batch cancelled by user", "warn")
    else:
        bridge._log("🏁 Batch complete", "success")
    set_run_state(bridge, "idle")
    bridge._emit_arena_state()


def cancelled_tail(bridge: Any) -> None:
    """The future was cancelled (Cancel button): line + idle + emit (per-image settle already ran)."""
    bridge._log("🏁 Batch cancelled", "warn")
    set_run_state(bridge, "idle")
    bridge._emit_arena_state()


def crashed_tail(bridge: Any, error: Exception) -> None:
    """Unexpected crash: cancelled-vs-crash line + idle + emit."""
    if "Cancelled" in str(error) or getattr(bridge, "_cancel_requested", False):
        bridge._log(f"🏁 Batch cancelled: {error}", "warn")
    else:
        bridge._log(f"Batch runner crashed: {error}", "error")
    import traceback
    traceback.print_exc()
    set_run_state(bridge, "idle")
    bridge._emit_arena_state()


async def run_live(bridge: Any) -> None:
    """The always-live run: pass while there is work, wait otherwise; ends only on stop/cancel."""
    bus = live_bus(bridge)
    set_run_state(bridge, "running")
    try:
        while is_live(bridge):
            plan = await plan_pass(bridge)
            if plan.reason:
                await wait_reason(bridge, plan, bus)
            else:
                await run_pass(bridge, plan)
        end_tail(bridge)
    except asyncio.CancelledError:
        cancelled_tail(bridge)
        raise
    except Exception as e:
        crashed_tail(bridge, e)
