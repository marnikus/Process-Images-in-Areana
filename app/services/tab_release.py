"""Tab release — what Stop and Cancel do to the *tab* (the operator's side).

`cooldown_service.finish_page_after_job` is the release a **finished** job
performs, and it lives inside the job task. That is the wrong owner when the
operator kills the job: Cancel cancels the very future that would have run it,
and Stop only raises a flag that a parked `await` may never read. Both left the
page holding its image, its busy status and no timer — the reported bug.

So the release is a step the *action* owns, not the dying task. One pipeline,
three callers (Stop button, Cancel run, and any future operator abort):

    clear the stop flag → forget the image → hide the waiting overlay
    → reset the page to a new chat → arm base+penalty cooldown → repaint

Every step is individually failure-tolerant: a dead CDP connection must never
strand a tab in "processing forever" (RULE 4 — report it, then keep going).
The new-chat reset is deliberately run **without** a cancel hook: the release
runs *because* the user cancelled, so honouring the cancel flag here is what
made the existing mechanic a no-op.

Imports downward only: `browser.new_chat` + `cooldown_service` (siblings), no
Qt, no UI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, List

from app.browser.new_chat import ResetCtx, reset_to_new_chat
from app.core.cooldown import clamp_seconds, format_remaining
from app.services.cooldown_service import (
    clear_tab_abort,
    load_config,
    set_tab_image,
    start_cooldown,
)

log = logging.getLogger("arena")

# The operator penalty on top of the normal pause (spec default 5 min).
# Overridable per user via `cooldown_stop_penalty_seconds` — one control for
# one decision (RULE 10); the base pause stays `cooldown_min_seconds`.
STOP_PENALTY_SECONDS = 300
PENALTY_KEY = "cooldown_stop_penalty_seconds"
RESET_TIMEOUT_SEC = 20.0


@dataclass
class ReleaseCtx:
    """One tab being released (parameter object — RULE 19 step 4).

    Carries no cancel hook on purpose: the release is the response to a cancel,
    so it must not abort on one.
    """

    pool: Any
    bridge: Any
    tab_id: str
    ctrl: Any = None
    reason: str = "stopped by user"


def _log(bridge, message: str, level: str = "info") -> None:
    """Report a step (RULE 2); a dead bridge never breaks the release."""
    try:
        bridge._log(message, level)
    except Exception:
        pass


def _label(ctx: ReleaseCtx) -> str:
    """The readable tab handle every view prints (D-7)."""
    try:
        from app.browser.page_pool import tab_label_of
        return tab_label_of(ctx.pool, ctx.tab_id)
    except Exception:
        return str(ctx.tab_id or "")[:12]


def penalty_seconds(bridge) -> int:
    """Operator penalty in seconds — user value when set, else the default."""
    try:
        get_state = getattr(getattr(bridge, "config", None), "get_state", None)
        if get_state is None:
            return STOP_PENALTY_SECONDS
        return clamp_seconds(get_state(PENALTY_KEY, STOP_PENALTY_SECONDS),
                             STOP_PENALTY_SECONDS)
    except Exception:
        return STOP_PENALTY_SECONDS


async def _hide_overlay(ctx: ReleaseCtx) -> None:
    """Remove the waiting window from the page (existing mechanic)."""
    hide = getattr(ctx.ctrl, "hide_watcher_overlay", None)
    if hide is None:
        return
    try:
        await hide()
    except Exception as e:
        _log(ctx.bridge, f"⚠ Overlay not cleared on {_label(ctx)} ({e})", "warn")


async def _reset_page(ctx: ReleaseCtx) -> None:
    """Return the tab to a clean new chat (existing mechanic, no cancel hook)."""
    if ctx.ctrl is None:
        return
    client = getattr(ctx.ctrl, "cdp", None) or ctx.ctrl
    try:
        ok, why = await reset_to_new_chat(ResetCtx(
            ctrl=ctx.ctrl, client=client, engine=ctx.bridge,
            timeout_sec=RESET_TIMEOUT_SEC, cancel_check=None))
    except Exception as e:
        ok, why = False, str(e)
    if not ok:
        _log(ctx.bridge, f"⚠ New-chat reset failed on {_label(ctx)} ({why}) — releasing anyway", "warn")


def _arm_cooldown(ctx: ReleaseCtx) -> int:
    """Base pause + operator penalty; 0 when the user turned cooldown off."""
    cfg = load_config(getattr(getattr(ctx.bridge, "config", None), "get_state", None)
                      or (lambda _k, d=None: d))
    if not cfg.enabled:
        return 0
    total = max(0, int(cfg.min_seconds)) + penalty_seconds(ctx.bridge)
    if total <= 0:
        return 0
    return total if start_cooldown(ctx.pool, ctx.tab_id, total, ctx.reason) else 0


def _settle_steady(ctx: ReleaseCtx) -> None:
    """No pause configured — hand the tab back ready rather than busy (RULE 4)."""
    try:
        ctx.pool.mark_steady(ctx.tab_id)
    except Exception:
        pass


def _emit(bridge) -> None:
    try:
        bridge._emit_pool_status()
    except Exception:
        pass


def _report_result(ctx: ReleaseCtx, seconds: int) -> None:
    """One honest closing line — the silence after 'Stop requested' was the bug."""
    label = _label(ctx)
    if seconds > 0:
        _log(ctx.bridge, f"⛔ Tab {label} released — cooling {format_remaining(seconds)} "
                         f"({ctx.reason})", "warn")
        return
    _log(ctx.bridge, f"⛔ Tab {label} released — ready now ({ctx.reason})", "warn")


async def release_tab(ctx: ReleaseCtx) -> bool:
    """Put one interrupted tab back to a usable state. False = unknown tab."""
    try:
        if ctx.pool is None or ctx.pool.get_page(ctx.tab_id) is None:
            return False
    except Exception:
        return False
    clear_tab_abort(ctx.pool, ctx.tab_id)
    set_tab_image(ctx.pool, ctx.tab_id, None)
    await _hide_overlay(ctx)
    await _reset_page(ctx)
    seconds = _arm_cooldown(ctx)
    if seconds <= 0:
        _settle_steady(ctx)
    _emit(ctx.bridge)
    _report_result(ctx, seconds)
    return True


def _active_tab_ids(pool) -> List[str]:
    """Pooled tabs that currently hold an image (the ones a cancel interrupts)."""
    try:
        with pool._lock:
            return [tid for tid, page in pool._pages.items()
                    if getattr(page, "current_image", None)]
    except Exception:
        return []


def _ctrl_for(pool, tab_id: str):
    """This tab's controller from the pool, or None when it has none."""
    try:
        _client, ctrl = pool.get_clients(tab_id)
        return ctrl
    except Exception:
        return None


def tab_needs_release(pool, tab_id: str) -> bool:
    """Is there anything to release — a live job, or a busy-like leftover?

    A genuinely idle, steady tab is *empty*, not broken (RULE 4): releasing it
    would hand an idle worker a cooldown penalty it never earned.
    """
    try:
        page = pool.get_page(tab_id) if pool else None
    except Exception:
        return False
    if page is None:
        return False
    return bool(getattr(page, "current_image", None)) or bool(page.is_busy())


def start_tab_release(bridge, tab_id: str, reason: str = "stopped by user") -> bool:
    """Schedule one tab's release from a Qt slot (sync caller, async pipeline).

    Returns whether the work was scheduled, not whether it finished — the slot
    must not block the UI thread on CDP round trips.
    """
    pool = getattr(bridge, "_page_pool", None)
    if pool is None or not tab_id or not tab_needs_release(pool, tab_id):
        return False
    ctx = ReleaseCtx(pool=pool, bridge=bridge, tab_id=tab_id,
                     ctrl=_ctrl_for(pool, tab_id), reason=reason)
    try:
        from app.services.run_state import schedule_coro
        return schedule_coro(bridge, release_tab(ctx)) is not None
    except Exception as e:
        _log(bridge, f"⚠ Could not start release for {tab_id[:12]} ({e})", "warn")
        return False


def start_release_active_tabs(bridge, reason: str = "cancelled by user") -> bool:
    """Schedule the cancel-wide release (same seam, every working tab).

    The working set is snapshotted **synchronously**: the cancelled job task
    clears `current_image` in its own `finally`, so deciding the list later
    would race that cleanup and release nothing.
    """
    pool = getattr(bridge, "_page_pool", None)
    if pool is None:
        return False
    tab_ids = _active_tab_ids(pool)
    if not tab_ids:
        return False
    try:
        from app.services.run_state import schedule_coro
        return schedule_coro(bridge, release_tabs(bridge, tab_ids, reason)) is not None
    except Exception as e:
        _log(bridge, f"⚠ Could not start release sweep ({e})", "warn")
        return False


async def release_tabs(bridge, tab_ids, reason: str = "cancelled by user") -> int:
    """Release a known set of tabs; returns how many were released."""
    pool = getattr(bridge, "_page_pool", None)
    if pool is None:
        return 0
    released = 0
    for tab_id in tab_ids or []:
        ctx = ReleaseCtx(pool=pool, bridge=bridge, tab_id=tab_id,
                         ctrl=_ctrl_for(pool, tab_id), reason=reason)
        try:
            if await release_tab(ctx):
                released += 1
        except Exception as e:
            _log(bridge, f"⚠ Release failed for {tab_id[:12]} ({e})", "warn")
    return released


async def release_active_tabs(bridge, reason: str = "cancelled by user") -> int:
    """Release every tab a cancelled run left working; returns the count."""
    pool = getattr(bridge, "_page_pool", None)
    if pool is None:
        return 0
    return await release_tabs(bridge, _active_tab_ids(pool), reason)
