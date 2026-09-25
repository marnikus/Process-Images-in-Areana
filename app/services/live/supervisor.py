"""Live supervisor — the always-live run (S5, D-5 / D-8, I-47).

`run_live(bridge)` replaces "one batch then idle": every pass re-plans from
the live queue / URL rows / pool (`plan_pass`), runs the existing lane
(`batch_orchestrator.run_pass`), and when there is nothing to do it
**waits** on the S4 bus instead of ending — no work, no usable tab, all
tabs cooling and CDP down are wait states with one throttled line each
(`REASON_LINES`, one per 5 min per reason and one on every reason change).
Only the user ends it: Stop (`cancel_current` cancels the future) or
Stop-after-current (`_stop_after`, the pass finishes its image first).

`set_run_state` is the ONLY writer of `bridge._run_state` — it also writes
the persisted `AppState.run_state` (L-2) and emits. The orchestrator and
the dispatcher are pass bodies with no lifecycle opinion.

Layer: services — core + sibling services; never Qt or panels.
"""

from __future__ import annotations

import asyncio
import traceback
from dataclasses import dataclass, field

from app.browser.page_status import PageStatus, is_firefox
from app.services import auto_connect as ac
from app.services.batch_orchestrator import pool_summary, resolve_and_claim_tab, run_pass
from app.services.cooldown_service import is_stuck_status

from .bus import LiveBus, live_bus
from .feed import PROCESSING_REFUSAL, queued_images, recover_stale_processing

__all__ = ["PassPlan", "REASON_LINES", "PROCESSING_REFUSAL", "run_live", "set_run_state",
           "plan_pass", "is_live", "wait_reason", "announce_live"]

WAIT_S = 1.0            # bus poll fallback
THROTTLE_MS = 300_000   # one wait line per reason per 5 min

REASON_LINES = {
    "no images": ("🟢 Run live — 0 queued images (Reset/Retry or Scan adds work instantly)", "info"),
    "no tab": ("🟡 No usable checked tab — run stays live, retrying (pool: {pool})", "warn"),
    "all cooling": ("⏳ All tabs cooling — next ready in {next_ready} (run stays live)", "info"),
    "cdp down": ("🔌 Chrome disconnected — run stays live, reconnecting (pool: {pool})", "warn"),
}


@dataclass
class PassPlan:
    """One pass, planned from a fresh read (no bridge reference; keeps params ≤3)."""

    images: list = field(default_factory=list)
    urls: list = field(default_factory=list)
    allowed: set = field(default_factory=set)
    tab_id: str = ""
    reason: str = ""


def set_run_state(bridge, value: str) -> None:
    """The one writer (D-8): attribute + persisted `AppState.run_state` + emit."""
    bridge._run_state = value
    try:
        bridge.state.run_state = value
    except AttributeError:
        pass
    bridge._emit_arena_state()


def is_live(bridge) -> bool:
    """The run continues while neither Stop nor Stop-after was asked (flags are the truth)."""
    return not getattr(bridge, "_cancel_requested", False) and not getattr(bridge, "_stop_after", False)


def _cdp_down(bridge) -> bool:
    return not getattr(getattr(bridge, "cdp", None), "is_connected", False)


def _waiting_on_cdp(bridge, plan) -> bool:
    """CDP down AND no free allowed Firefox worker to fall back on (D-9)."""
    return _cdp_down(bridge) and not _firefox_ready(bridge, plan.allowed)


def _firefox_ready(bridge, allowed: set) -> bool:
    """A free, allowed Firefox page is a worker even with Chrome's CDP down (D-9)."""
    pool = getattr(bridge, "_page_pool", None)
    if pool is None:
        return False
    try:
        with pool._lock:
            return any(is_firefox(page) and page.tab_id in allowed and page.is_free()
                       for page in pool._pages.values())
    except AttributeError:
        return False


def _cooling(page: dict) -> bool:
    """A snapshot page that cannot take a job right now: timer still running, or busy-like."""
    if page.get("status") == PageStatus.COOLDOWN.value:
        return int(page.get("cooldown_remaining", 0) or 0) > 0
    return is_stuck_status(page.get("status"))


def _all_cooling(bridge, allowed: set) -> bool:
    """Every allowed pooled tab is cooling / busy — nothing can take a job now."""
    pool = getattr(bridge, "_page_pool", None)
    if pool is None or not allowed:
        return False
    try:
        pages = [p for p in pool.status_snapshot().get("pages", []) if p.get("tab_id") in allowed]
    except Exception:
        return False
    return bool(pages) and all(_cooling(p) for p in pages)


async def plan_pass(bridge) -> PassPlan:
    """Fresh read every pass: queued images, enabled rows, allowed tabs, primary tab, blocking reason."""
    plan = PassPlan(images=queued_images(bridge),
                    urls=[u for u in bridge.state.urls if u.enabled])
    plan.allowed = ac.enabled_tab_ids(plan.urls)
    if not plan.images:
        plan.reason = "no images"
    elif _waiting_on_cdp(bridge, plan):
        plan.reason = "cdp down"
    elif _all_cooling(bridge, plan.allowed):
        plan.reason = "all cooling"
    else:
        current = getattr(bridge.cdp, "_current_tab_id", "") or ""
        plan.tab_id = await resolve_and_claim_tab(bridge, current, plan.allowed)
        plan.reason = "" if plan.tab_id else "no tab"
    return plan


def _next_ready(bridge, allowed: set) -> str:
    """MM:SS until the soonest allowed tab leaves cooldown ('--:--' when unknown)."""
    try:
        pages = bridge._page_pool.status_snapshot().get("pages", [])
        secs = min(int(p.get("cooldown_remaining", 0) or 0) for p in pages if p.get("tab_id") in allowed)
    except (AttributeError, ValueError):
        return "--:--"
    return f"{secs // 60:02d}:{secs % 60:02d}"


async def wait_reason(bridge, plan: PassPlan, bus: LiveBus) -> None:
    """One throttled line per reason (plus one on every change), then wait for a wake or the poll."""
    template, level = REASON_LINES[plan.reason]
    changed = getattr(bridge, "_live_reason", None) != plan.reason
    bridge._live_reason = plan.reason
    if bus.throttle(f"live:{plan.reason}", THROTTLE_MS) or changed:  # throttle first: it records the window
        pool = getattr(bridge, "_page_pool", None)
        bridge._log(template.format(pool=pool_summary(pool), next_ready=_next_ready(bridge, plan.allowed)), level)
    await bus.wait(WAIT_S)


def announce_live(bridge, queued: int) -> None:
    """Start pressed while the run is live: one line, no second loop (the caller wakes the bus)."""
    bridge._log(f"🟢 Run already live — queue re-checked ({queued} queued)", "info")


def _pass_tail(bridge) -> None:
    """After a pass: the run stays live; Stop / Stop-after end it with the pinned markers."""
    bridge._live_reason = None
    if getattr(bridge, "_cancel_requested", False):
        bridge._log("🏁 Batch cancelled by user", "warn")
    elif getattr(bridge, "_stop_after", False):
        bridge._log("🏁 Batch complete", "success")
    else:
        bridge._log(f"🏁 Pass complete — run stays live ({len(queued_images(bridge))} queued)", "info")


def _cancelled_tail(bridge) -> None:
    bridge._log("🏁 Batch cancelled", "warn")


def _crash_tail(bridge, error: Exception) -> None:
    """Unexpected crash of a pass: loud line + traceback; the loop ends (RULE 4: say what broke)."""
    bridge._log(f"Batch runner crashed: {error}", "error")
    traceback.print_exc()


async def run_live(bridge) -> None:
    """The live loop: plan → wait or pass → tail, until Stop / Stop-after; `idle` is written once, here."""
    bus = live_bus(bridge)
    bus.attach(asyncio.get_running_loop())
    recover_stale_processing(bridge)
    set_run_state(bridge, "running")
    try:
        while is_live(bridge):
            plan = await plan_pass(bridge)
            if plan.reason:
                await wait_reason(bridge, plan, bus)
                continue
            await run_pass(bridge, plan)
            _pass_tail(bridge)
    except asyncio.CancelledError:
        _cancelled_tail(bridge)
        raise
    except Exception as e:
        _crash_tail(bridge, e)
    finally:
        set_run_state(bridge, "idle")
