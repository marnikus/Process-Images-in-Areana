"""Live run supervisor — the always-live run loop (D-8/L-2, S5).

One durable loop replaces "one batch then idle": each pass re-reads the queue,
URL wiring and pool liveness (`plan_pass`), works when there is work
(`run_pass` = the old batch body), and otherwise waits on the S4 LiveBus
(`wait_reason` — waits are bounded and woken by every commit/wake). The loop
ends only via the cancel / stop-after flags (`is_live`) or `CancelledError`.

D-8: exactly one run-state writer — `set_run_state`; the orchestrator and
dispatcher hold no `_run_state =` assignment any more. The persisted
`state.run_state` field follows the attribute (L-2).
"""

from __future__ import annotations

import asyncio
import traceback
from dataclasses import dataclass, field
from typing import Any, List, Set

from app.services import auto_connect as ac
from app.services import batch_orchestrator as bo
from app.services.live.bus import live_bus
from app.services.live.feed import eligible_images

WAIT_SEC = 1.0            # one bounded wait between replans; woken on any commit
REPEAT_MS = 300_000       # an idle reason is announced at most once per 5 min

REASON_LINES = {
    "no_images": ("🟢 Run live — {n} queued images — waiting for queue changes", "info"),
    "cdp_down": ("🟢 Run live — Chrome disconnected — waiting for reconnect", "warn"),
    "no_tab": ("🟢 Run live — no usable checked tab — waiting (link + check a URL row)", "warn"),
    "all_cooling": ("🟢 Run live — all checked tabs cooling — waiting", "info"),
}


@dataclass
class PassPlan:
    """One pass's fresh snapshot; never carries a bridge (span ≤8, RULE 16)."""

    images: List[Any] = field(default_factory=list)
    urls: List[Any] = field(default_factory=list)
    allowed: Set[str] = field(default_factory=set)
    tab_id: str = ""
    reason: str = ""


def is_live(bridge) -> bool:
    """Flags are the truth — this never reads `_run_state`."""
    return not (getattr(bridge, "_cancel_requested", False) or getattr(bridge, "_stop_after", False))


def set_run_state(bridge, value: str) -> None:
    """The ONLY run-state writer (D-8): attribute + persisted field (L-2)."""
    bridge._run_state = value
    state = getattr(bridge, "state", None)
    if state is not None and hasattr(state, "run_state"):
        state.run_state = value


def plan_pass(bridge) -> PassPlan:
    """Fresh read every pass; claims and CDP probes stay in the pass body."""
    images = eligible_images(bridge.state.images)
    urls = [u for u in bridge.state.urls if getattr(u, "enabled", False)]
    plan = PassPlan(images=images, urls=urls, allowed=ac.enabled_tab_ids(urls))
    plan.reason = _pass_reason(bridge, plan)
    return plan


def _pass_reason(bridge, plan: PassPlan) -> str:
    if not plan.images:
        return "no_images"
    cdp = getattr(bridge, "cdp", None)
    if not cdp or not getattr(cdp, "is_connected", False):
        return "cdp_down"
    if not plan.allowed:
        return "no_tab"
    pool = getattr(bridge, "_page_pool", None)
    if pool is None:
        return ""
    total, free = ac.counts_in(pool, plan.allowed)
    return "all_cooling" if total and not free else ""


async def wait_reason(bridge, plan: PassPlan, bus) -> None:
    """Throttled reason line, then one bounded bus wait; never ends the run."""
    template, level = REASON_LINES[plan.reason]
    if bus.throttle(f"live:{plan.reason}", REPEAT_MS):
        bridge._log(template.format(n=len(plan.images)), level)
    await bus.wait(WAIT_SEC)


async def run_pass(bridge, plan: PassPlan) -> bool:
    """One batch body against the plan; False when the claim declined (wait next)."""
    ctx = await bo.prepare_batch(bridge, plan)
    if ctx is None:
        return False
    if await bo._try_parallel(ctx):
        return True
    if not await bo._await_batch_gate(ctx):
        return True
    await bo._run_sequential(ctx)
    bo.pass_complete(ctx)
    return True


def declined_plan(plan: PassPlan) -> PassPlan:
    """A declined claim replans as a no-tab wait (never a hot re-pass loop)."""
    return PassPlan(images=plan.images, urls=plan.urls, allowed=plan.allowed,
                    tab_id=plan.tab_id, reason="no_tab")


def cancelled_tail(bridge) -> None:
    """Task-cancel tail (today's _cancel_batch vocabulary)."""
    bridge._log("🏁 Batch cancelled", "warn")
    bridge._emit_arena_state()


def completed_tail(bridge) -> None:
    """End-of-live-run line; emits stay with the pass/tail that settled last."""
    bridge._log("🟢 Live run ended — Start resumes it anytime", "info")


def crash_tail(bridge, error: Exception) -> None:
    """Unexpected crash (today's _crash_batch vocabulary) ends the run."""
    if "Cancelled" in str(error) or getattr(bridge, "_cancel_requested", False):
        bridge._log(f"🏁 Batch cancelled: {error}", "warn")
    else:
        bridge._log(f"Batch runner crashed: {error}", "error")
        traceback.print_exc()
    bridge._emit_arena_state()


async def run_live(bridge) -> None:
    """Passes while live; waits the bus otherwise; ends only by flags/cancel."""
    bus = live_bus(bridge)
    bridge._live_supervisor = True
    try:
        while is_live(bridge):
            plan = plan_pass(bridge)
            if plan.reason:
                await wait_reason(bridge, plan, bus)
            elif not (await run_pass(bridge, plan)):
                await wait_reason(bridge, declined_plan(plan), bus)
    except asyncio.CancelledError:
        cancelled_tail(bridge)
        raise
    except Exception as error:
        crash_tail(bridge, error)
    finally:
        bridge._live_supervisor = False
        set_run_state(bridge, "idle")
        completed_tail(bridge)
