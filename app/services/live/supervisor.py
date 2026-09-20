# ideal-size: ~200 lines reason=S5 budget — one live-loop module: plan, wait, pass dispatch, tails; splitting would scatter one loop that always changes together (RULE 18.2)
"""live/supervisor (S5) — the always-live run (I-47).

`run_live` replaces "one batch then idle": the run survives no-work /
no-tab / all-cooling / CDP-down by waiting on the LiveBus, and stop or
cancel is the only way out. Exactly one writer owns the run state
(`set_run_state`, D-8 — also fixes L-2: `AppState.run_state` was
persisted but never written). `plan_pass` is the ONLY place that reads
queue/URL/pool liveness; the orchestrator keeps the lane decision
(`dispatch_pass`), the pass bodies have no lifecycle opinions.
"""

from __future__ import annotations

import asyncio
import traceback
from dataclasses import dataclass

from app.core.run_scope import eligible_images
from app.services import auto_connect as ac
from app.services.cooldown_service import resolve_primary_tab
from app.services.live.bus import live_bus
from app.services.live.feed import recover_stale_processing

WAIT_S = 1.0            # one bus wait per idle tick
THROTTLE_MS = 120_000   # one wait line per two minutes per reason

REASON_LINES = {
    "no_work": ("🟢 Run live — {queued} queued images — reset / scan / retry adds work", "success"),
    "no_tab": ("🟡 Run live — no usable checked tab — connect a tab to resume", "warn"),
    "all_cooling": ("🟡 Run live — every checked tab is cooling down — waiting", "warn"),
    "cdp_down": ("🔴 Run live — Chrome not connected — reconnect to resume", "error"),
}


@dataclass
class PassPlan:
    """One pass's fresh read (S5) — never carries the bridge."""

    images: list
    urls: list
    allowed: set
    tab_id: str
    reason: str


def set_run_state(bridge, value: str) -> None:
    """The ONLY run-state writer (D-8/L-2): attr + persisted AppState + emit."""
    bridge._run_state = value
    try:
        bridge.state.run_state = value
    except Exception:
        pass
    try:
        bridge._emit_arena_state()
    except Exception:
        pass


def is_live(bridge) -> bool:
    """Flags are the truth — never the label."""
    return not getattr(bridge, "_cancel_requested", False) and not getattr(bridge, "_stop_after", False)


def plan_pass(bridge) -> PassPlan:
    """Fresh read of queue/URL/pool liveness — never cached (S5).

    Failed images wait for an explicit Retry (revive -> pending); the
    live loop never auto-retries them.
    """
    urls = [u for u in bridge.state.urls if u.enabled]
    allowed = ac.enabled_tab_ids(urls)
    images = [i for i in eligible_images(bridge.state.images) if i.status != "failed"]
    if not images:
        return PassPlan(images, urls, allowed, "", "no_work")
    cdp = getattr(bridge, "cdp", None)
    if not cdp or not getattr(cdp, "is_connected", False):
        return PassPlan(images, urls, allowed, "", "cdp_down")
    pool = getattr(bridge, "_page_pool", None)
    total, free = ac.counts_in(pool, allowed)
    if pool is not None and total and not free:
        return PassPlan(images, urls, allowed, "", "all_cooling")
    want = resolve_primary_tab(pool, getattr(cdp, "_current_tab_id", "") or "", allowed)
    if not want:
        return PassPlan(images, urls, allowed, "", "no_tab")
    return PassPlan(images, urls, allowed, want, "ok")


async def wait_reason(bridge, plan, bus) -> None:
    """One throttled wait line + one bus wait; never ends the run."""
    template, level = REASON_LINES.get(plan.reason, ("🟡 Run live — waiting ({reason})", "warn"))
    if bus.throttle(plan.reason, THROTTLE_MS):
        bridge._log(template.format(queued=len(plan.images), reason=plan.reason), level)
    await bus.wait(WAIT_S)


async def run_pass(bridge, plan) -> None:
    """One pass: prepare from the plan, then the orchestrator's lane."""
    from app.services.batch_orchestrator import dispatch_pass, prepare_batch

    ctx = await prepare_batch(bridge, plan)
    if ctx is not None:
        await dispatch_pass(ctx)


def pass_tail(bridge, plan) -> None:
    """Pass done — the loop re-plans; no run-state write here (S5)."""
    bridge._log(f"↻ Pass complete — {len(plan.images)} image(s) planned", "info")


def completed_tail(bridge) -> None:
    """Run ended by stop-after: the pinned '🏁 Batch complete' line + idle."""
    bridge._log("🏁 Batch complete", "success")
    set_run_state(bridge, "idle")


def cancelled_tail(bridge, error=None) -> None:
    """Run ended by cancel — or an honestly reported crash — then idle."""
    if error is None:
        bridge._log("🏁 Batch cancelled", "warn")
    elif "Cancelled" in str(error) or getattr(bridge, "_cancel_requested", False):
        bridge._log(f"🏁 Batch cancelled: {error}", "warn")
    else:
        bridge._log(f"Batch runner crashed: {error}", "error")
        traceback.print_exc()
    set_run_state(bridge, "idle")


async def run_live(bridge) -> None:
    """The always-live run: plan → run or wait, until stop or cancel (S5)."""
    set_run_state(bridge, "running")
    bus = live_bus(bridge)
    try:
        bus.attach(asyncio.get_running_loop())
    except RuntimeError:
        pass
    try:
        while is_live(bridge):
            recover_stale_processing(bridge)
            plan = plan_pass(bridge)
            if plan.reason == "ok":
                await run_pass(bridge, plan)
                pass_tail(bridge, plan)
                await asyncio.sleep(0)  # fairness: never starve the loop
                continue
            await wait_reason(bridge, plan, bus)
        if getattr(bridge, "_cancel_requested", False):
            cancelled_tail(bridge)
        else:
            completed_tail(bridge)
    except asyncio.CancelledError:
        cancelled_tail(bridge)
        raise
    except Exception as e:
        cancelled_tail(bridge, e)
