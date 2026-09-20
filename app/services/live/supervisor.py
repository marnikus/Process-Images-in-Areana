"""S5: the always-live run supervisor — wait on the bus, pass on work, end only on stop.

The supervisor owns the run lifecycle: `set_run_state` is the only writer of the
run's own running/idle transitions (user-intent slots in run_control keep theirs;
D-8/L-2). `run_live` never ends on an empty queue, a missing tab, or a cooling
pool — it waits on the live bus and dispatches the next pass when work arrives.
"""

import asyncio
from dataclasses import dataclass, field

from app.core.run_scope import run_scope
from app.services import auto_connect as ac
from app.services.cooldown_service import resolve_primary_tab
from app.services.live.bus import live_bus

REASON_LINES = {
    "no_work": ("🟢 Run live — {queued} queued images", "info"),
    "no_tab": ("🟢 Run live — waiting for a tab", "warn"),
    "all_cooling": ("🟢 Run live — all tabs cooling", "info"),
    "cdp_down": ("🟢 Run live — CDP disconnected", "warn"),
}


@dataclass
class PassPlan:
    """Next-pass snapshot: queue/URL liveness + tab + wait reason (no bridge)."""

    images: list = field(default_factory=list)
    urls: list = field(default_factory=list)
    allowed: set = field(default_factory=set)
    tab_id: str = ""
    reason: str = "no_work"

    @property
    def ready(self) -> bool:
        return self.reason == "ready"


def set_run_state(bridge, value) -> None:
    """The run lifecycle's only writer (user-intent slots keep theirs)."""
    bridge._run_state = value


def is_live(bridge) -> bool:
    """Neither stop flag set — flags are the truth, never the label."""
    return not getattr(bridge, "_cancel_requested", False) and not getattr(bridge, "_stop_after", False)


def _snapshot_pages(pool) -> list:
    """Pooled page entries, best effort (read-only, no eval)."""
    try:
        return pool.status_snapshot().get("pages", []) if pool else []
    except Exception:
        return []


def _plan_tab(pool, current: str, allowed) -> str:
    """Pure tab read: resolve without claiming, moving, or logging."""
    try:
        return resolve_primary_tab(pool, current or "", allowed)
    except Exception:
        return current or ""


def _cooling_pages(pool, allowed) -> list:
    """Checked pooled tabs currently cooling (read-only, no eval)."""
    return [p for p in _snapshot_pages(pool)
            if p.get("tab_id", "") in allowed and p.get("status") == "cooldown"]


def _cdp_down(bridge) -> bool:
    """CDP missing or disconnected: nothing can run."""
    return not bridge.cdp or not bridge.cdp.is_connected


def _tab_plan(pool, current: str, allowed) -> tuple:
    """Tab decision: a ready tab id, else ('', wait reason)."""
    tab = _plan_tab(pool, current, allowed)
    cooling = {p.get("tab_id", "") for p in _cooling_pages(pool, allowed)}
    if tab and tab not in cooling:
        return tab, "ready"
    if cooling:
        return "", "all_cooling"
    return "", "no_tab"


def plan_pass(bridge) -> PassPlan:
    """Next-pass snapshot: queue/URL liveness + tab + reason (pure read)."""
    urls = [u for u in bridge.state.urls if u.enabled]
    images = run_scope(bridge.state.images)
    allowed = ac.enabled_tab_ids(urls)
    if _cdp_down(bridge):
        return PassPlan(images, urls, allowed, "", "cdp_down")
    if not images:
        return PassPlan(images, urls, allowed, "", "no_work")
    pool = getattr(bridge, "_page_pool", None)
    current = getattr(bridge.cdp, "_current_tab_id", "") or ""
    tab_id, reason = _tab_plan(pool, current, allowed)
    return PassPlan(images, urls, allowed, tab_id, reason)


async def wait_reason(bridge, plan: PassPlan, bus) -> None:
    """Throttled wait line, then sleep on the bus (never ends the run)."""
    template, level = REASON_LINES[plan.reason]
    marker = template.format(queued=len(plan.images))
    if bridge._live_marker != marker:
        bridge._live_marker = marker
        bridge._log(marker, level)
    await bus.wait(1.0)


async def run_pass(bridge, plan: PassPlan) -> None:
    """One live pass through the existing lane (the lane decides inside)."""
    from app.services.batch_orchestrator import _run_guarded
    await _run_guarded(bridge, plan, False)


def pass_tail(bridge, plan: PassPlan) -> None:
    """Per-pass seam: the next wait re-announces (test-9 lever wraps this)."""
    bridge._live_marker = ""


def cancelled_tail(bridge) -> None:
    """Stop line + emit (the caller idles — stop is stop)."""
    bridge._log("🏁 Batch cancelled", "warn")
    bridge._emit_arena_state()


def completed_tail(bridge) -> None:
    """Run-end line + emit (the caller idles)."""
    if getattr(bridge, "_cancel_requested", False):
        bridge._log("🏁 Batch cancelled by user", "warn")
    else:
        bridge._log("🏁 Batch complete", "success")
    bridge._emit_arena_state()


def _cancel_batch(bridge) -> None:
    """Cancelled run: line + idle + emit (settle happens per-image)."""
    cancelled_tail(bridge)
    set_run_state(bridge, "idle")


def _crash_batch(bridge, error: Exception) -> None:
    """Unexpected crash: cancelled-vs-crash line + idle + emit."""
    if "Cancelled" in str(error) or getattr(bridge, "_cancel_requested", False):
        bridge._log(f"🏁 Batch cancelled: {error}", "warn")
    else:
        bridge._log(f"Batch runner crashed: {error}", "error")
    import traceback
    traceback.print_exc()
    set_run_state(bridge, "idle")
    bridge._emit_arena_state()


async def run_live(bridge) -> None:
    """The always-live run: plan → pass-or-wait, ending only on stop."""
    set_run_state(bridge, "running")
    bridge._live_marker = ""
    bus = live_bus(bridge)
    try:
        while is_live(bridge):
            plan = plan_pass(bridge)
            if plan.ready:
                await run_pass(bridge, plan)
                pass_tail(bridge, plan)
            else:
                await wait_reason(bridge, plan, bus)
    except asyncio.CancelledError:
        _cancel_batch(bridge)
        raise
    if getattr(bridge, "_cancel_requested", False):
        _cancel_batch(bridge)
    else:
        completed_tail(bridge)
        set_run_state(bridge, "idle")


async def run_batch(bridge) -> None:
    """One pass with batch semantics: idle when the pass ends (compat entry)."""
    from app.services.batch_orchestrator import _run_guarded
    try:
        await _run_guarded(bridge, plan_pass(bridge), True)
    except asyncio.CancelledError:
        _cancel_batch(bridge)
        raise
    except Exception as e:
        _crash_batch(bridge, e)
    else:
        set_run_state(bridge, "idle")
