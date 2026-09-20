"""Read-only live UI serialization; imports services/core, never probes CDP.

ideal-size: a small serializer leaf, separate from frozen PagePool/PageInfo.
PauseClock is charged AFTER a settle. These are last-settled numbers, not a
live captcha deadline. Missing clocks remain unknown; OFF reads no clocks.
"""
import json
import math

from app.services.captcha.policy import captcha_in_scope
from app.services.live.debug_view import live_view
from app.ui.services import arena_serialize as js


def _pause_evidence(pool, tab_id) -> dict:
    try:
        _, controller = pool.get_clients(tab_id)
        clock = getattr(controller, "pause_clock", None)
        if clock is None:
            return {}
        remaining = clock.remaining()
        pause = {"absorbed_s": clock.total, "cap_s": clock.cap_s,
                 "remaining_s": remaining if math.isfinite(remaining) else None}
        return {"pause": pause}
    except Exception:
        return {}  # a detached controller has no measurable pause


def pool_snapshot(bridge) -> dict:
    """One existing snapshot plus optional clock evidence; no mutation."""
    pool = bridge._page_pool
    snapshot = pool.status_snapshot()
    scope = captcha_in_scope(bridge)
    if not scope:
        return {**snapshot, "waits_in_scope": False}
    pages = [{**page, **_pause_evidence(pool, page["tab_id"])}
             for page in snapshot["pages"]]
    return {**snapshot, "pages": pages, "waits_in_scope": True}


def publish_debug(bridge) -> None:
    """Read-only heartbeat on existing signals, with no persistence side effect."""
    view = live_view(bridge)
    progress = {**bridge.state.progress, "run_state": view["run_state"], "live": view}
    bridge.progress_updated.emit(json.dumps(progress, ensure_ascii=False))
    bridge.page_pool_updated.emit(json.dumps(pool_snapshot(bridge), ensure_ascii=False))


def initial_arena_state(bridge) -> dict:
    """Initial read includes the same live data as subsequent progress pushes."""
    state = js.arena_to_js(bridge.state)
    state["progress"] = {**state["progress"], "live": live_view(bridge)}
    return state
