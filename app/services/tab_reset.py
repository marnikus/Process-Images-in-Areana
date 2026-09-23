# ideal-size: 330 lines reason=one cohesive "put a tab back into a known state" pipeline shared by Stop/Cancel/Clear time (D-1); a second file would duplicate the park, its fields reset and its three log lines
"""Stop / Cancel / Clear-time — the one reset pipeline for a pooled tab (D-1).

The user's report: after Cancel the row kept its image, the tab stayed busy, no
countdown appeared, and Stop answered `{"ok": true}` while nothing happened —
because a leftover `current_image` was trusted as proof of a live job (F-1).

The rule here is one: **the run decides liveness** (D-2). While a run is alive a
busy tab has a real job → Stop is the cooperative abort and the job's own finish
parks the tab. With no live run a busy-looking tab is stale → this pipeline (hide
the waiting window, New Chat, clear the job fields, arm the configured pause)
repairs it. Nothing here ever claims success it did not earn.

Imports: services -> browser/core only (panels call in).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.browser.new_chat import ResetCtx, reset_to_new_chat
from app.browser.page_status import PageStatus
from app.core.cooldown import format_remaining
from app.services.cooldown_service import (
    clear_tab_abort,
    force_reset_page,
    load_config,
    request_tab_abort,
    reset_cooldown,
    start_cooldown,
)
from app.services.run_state import batch_active, schedule_coro, tab_label_of

STOP_REASON = "stopped by user"
CANCEL_REASON = "run cancelled"
UNWIND_WAIT_SEC = 5.0     # how long Cancel lets the doomed run leave its job
RESET_TIMEOUT_SEC = 15.0  # a park must not hang the background loop
_POLL_SEC = 0.2
_OVERLAY_ATTR = "hide_watcher_overlay"
_BUSY_LIKE = frozenset({PageStatus.BUSY, PageStatus.WAITING_GENERATION, PageStatus.WAITING_CAPTCHA})


def _log(bridge: Any, message: str, level: str = "info") -> None:
    """Report (RULE 2) — a missing logger never breaks a reset."""
    try:
        bridge._log(message, level)
    except Exception:
        pass


def _emit(bridge: Any) -> None:
    """Push the pool snapshot the row reads."""
    try:
        bridge._emit_pool_status()
    except Exception:
        pass


def _persist(bridge: Any) -> None:
    """Persist the pause so a restart cannot restore the cleared one (D-3)."""
    try:
        bridge._persist_cooldowns()
    except Exception:
        pass


def _refuse(error: str) -> dict:
    """The honest negative answer — never a silent success (F-1)."""
    return {"ok": False, "error": error}


def _pool(bridge: Any):
    """The pooled tabs, or None when the pool was never started."""
    return getattr(bridge, "_page_pool", None)


def _live_run(bridge: Any) -> bool:
    """A run owns tabs right now (the tracked batch future, I-45)."""
    return batch_active(bridge)


def _image_of(page) -> str:
    """The image a page claims to process ('' when none)."""
    return str(getattr(page, "current_image", "") or "")


def _is_busy_like(page) -> bool:
    """Busy/waiting/error: a status a finished run can leave behind."""
    try:
        return page.status in _BUSY_LIKE or page.status == PageStatus.ERROR
    except Exception:
        return False


def _needs_reset(page) -> bool:
    """A tab Stop/Cancel must touch: it is busy-like or still carries an image."""
    return _is_busy_like(page) or bool(_image_of(page))


def _pages(pool: Any) -> list:
    """Snapshot of (tab_id, page) taken under the pool lock."""
    try:
        with pool._lock:
            return list(pool._pages.items())
    except Exception:
        return []


def _remaining(pool: Any, tab_id: str) -> int:
    """Live countdown of a tab (0 when it is gone)."""
    try:
        page = pool.get_page(tab_id)
        return page.remaining_seconds() if page is not None else 0
    except Exception:
        return 0


def stop_cancel_seconds(bridge: Any) -> int:
    """Park seconds = the configured pause (D-6), 0 when cooldowns are off."""
    try:
        cfg = load_config(bridge.config.get_state)
    except Exception:
        return 0
    return int(cfg.min_seconds) if cfg.enabled else 0


def stop_request(bridge: Any, tab_id: str) -> dict:
    """Stop = abort a live job, or repair a tab no run owns — never a lie (D-3)."""
    pool = _pool(bridge)
    if pool is None:
        return _refuse("pool not initialized")
    page = pool.get_page(tab_id)
    if page is None:
        return _refuse("unknown tab")
    if _live_run(bridge):
        return _abort_live(bridge, pool, tab_id)
    return _park_stale(bridge, pool, tab_id, page)


def _abort_live(bridge: Any, pool: Any, tab_id: str) -> dict:
    """A real job keeps its page: cooperative abort, its finish parks the tab."""
    if not request_tab_abort(pool, tab_id):
        return _refuse("no live job on this tab")
    label = tab_label_of(pool, tab_id)
    _log(bridge, f"⛔ Stop requested for tab {label} — job aborts, then cooldown", "warn")
    _emit(bridge)
    return {"ok": True, "mode": "abort"}


def _park_stale(bridge: Any, pool: Any, tab_id: str, page) -> dict:
    """Nothing owns this tab any more: reset it and arm the pause."""
    if not _needs_reset(page):
        return _refuse("no live job on this tab")
    seconds = stop_cancel_seconds(bridge)
    label = tab_label_of(pool, tab_id)
    _log(bridge, f"♻️ Stop: tab {label} has no live job — reset and pause "
                 f"{format_remaining(seconds)}", "warn")
    schedule_coro(bridge, park_tab(bridge, tab_id, STOP_REASON, seconds))
    return {"ok": True, "mode": "reset", "seconds": seconds}


async def park_tab(bridge: Any, tab_id: str, reason: str, seconds: int) -> bool:
    """Reset one tab to a clean state and arm its pause; never raises (D-3)."""
    pool = _pool(bridge)
    page = pool.get_page(tab_id) if pool is not None else None
    if page is None:
        return False
    label = tab_label_of(pool, tab_id)
    await _reset_page(bridge, pool, tab_id, label)
    _forget_job(pool, tab_id)
    left = _arm_pause(pool, tab_id, seconds, reason)
    _log(bridge, _park_line(label, left), "warn")
    _emit(bridge)
    _persist(bridge)
    return True


async def _reset_page(bridge: Any, pool: Any, tab_id: str, label: str) -> None:
    """Overlay off + New Chat — best effort, one line when it fails (F-3)."""
    client, ctrl = _clients(pool, tab_id)
    if ctrl is None:
        return
    await _hide_overlay(ctrl)
    try:
        ok, detail = await reset_to_new_chat(_reset_ctx(bridge, client, ctrl))
    except Exception as e:
        ok, detail = False, str(e)
    if not ok:
        _log(bridge, f"⚠ New-chat reset failed for {label} ({detail}) — state reset anyway", "warn")


def _reset_ctx(bridge: Any, client: Any, ctrl: Any) -> ResetCtx:
    """ResetCtx for the park — a cancelled run must not abort the reset."""
    return ResetCtx(ctrl=ctrl, client=client, engine=bridge, timeout_sec=RESET_TIMEOUT_SEC,
                    cancel_check=lambda: False)


def _clients(pool: Any, tab_id: str) -> tuple:
    """(client, controller) of a pooled tab; (None, None) when it has no socket."""
    try:
        return pool.get_clients(tab_id)
    except Exception:
        return None, None


async def _hide_overlay(ctrl: Any) -> None:
    """Remove the waiting window — a dead socket never blocks the park (F-3)."""
    hide = getattr(ctrl, _OVERLAY_ATTR, None)
    if hide is None:
        return
    try:
        await hide()
    except Exception:
        pass


def _forget_job(pool: Any, tab_id: str) -> None:
    """Drop the leftover job fields and its abort flag (D-2)."""
    try:
        with pool._lock:
            page = pool._pages.get(tab_id)
            if page is None:
                return
            page.current_image = None
            page.current_job_id = None
            page.busy_since = None
    except Exception:
        pass
    clear_tab_abort(pool, tab_id)


def _arm_pause(pool: Any, tab_id: str, seconds: int, reason: str) -> int:
    """Arm the pause, debt dropped; returns the live remaining seconds."""
    try:
        with pool._lock:
            page = pool._pages.get(tab_id)
            if page is None:
                return 0
            page.pending_penalty = 0
        start_cooldown(pool, tab_id, int(seconds or 0), reason)
        return _remaining(pool, tab_id)
    except Exception:
        return 0


def _park_line(label: str, left: int) -> str:
    """One honest line per parked tab (RULE 2)."""
    if left > 0:
        return f"♻️ Tab {label} reset — cooling {format_remaining(left)}"
    return f"♻️ Tab {label} reset — no cooldown, ready now"


def cancel_request(bridge: Any) -> dict:
    """Cancel: schedule the same park for every affected tab (D-4)."""
    _log(bridge, "⛔ Cancel: resetting every affected tab", "warn")
    if _pool(bridge) is None:
        return {"ok": True, "scheduled": False}
    schedule_coro(bridge, cancel_run_reset(bridge))
    return {"ok": True, "scheduled": True}


async def cancel_run_reset(bridge: Any) -> dict:
    """Park every tab the cancelled run left behind; never shortens a timer (D-4)."""
    pool = _pool(bridge)
    if pool is None:
        return {"ok": True, "parked": 0, "seconds": 0}
    seconds = stop_cancel_seconds(bridge)
    _abort_survivors(pool)
    if await _still_live(bridge):
        _log(bridge, "⛔ Cancel: the run is still unwinding — each tab parks when its job ends", "warn")
        return {"ok": True, "parked": 0, "seconds": seconds, "live": True}
    parked = await _park_affected(bridge, pool, seconds)
    _log(bridge, f"⛔ Cancel: {parked} tab(s) parked in cooldown "
                 f"({format_remaining(seconds)} each)", "warn")
    return {"ok": True, "parked": parked, "seconds": seconds}


def _abort_survivors(pool: Any) -> None:
    """Ask every tab that still claims a running job to abandon it."""
    for tab_id, page in _pages(pool):
        if _image_of(page) and _is_busy_like(page):
            request_tab_abort(pool, tab_id)


async def _still_live(bridge: Any) -> bool:
    """Give a cancelled run a bounded moment to unwind before touching its tabs."""
    deadline = time.monotonic() + UNWIND_WAIT_SEC
    while _live_run(bridge) and time.monotonic() < deadline:
        await asyncio.sleep(_POLL_SEC)
    return _live_run(bridge)


async def _park_affected(bridge: Any, pool: Any, seconds: int) -> int:
    """Park every tab the run left busy; a steady tab keeps its own timer."""
    parked = 0
    for tab_id, page in _pages(pool):
        if _needs_reset(page) and await park_tab(bridge, tab_id, CANCEL_REASON, seconds):
            parked += 1
    return parked


def clear_time(bridge: Any, tab_id: str) -> dict:
    """Clear time: the pause goes and the row is ready now — and it says so (D-5)."""
    pool = _pool(bridge)
    if pool is None:
        return _refuse("pool not initialized")
    page = pool.get_page(tab_id)
    if page is None:
        return _refuse("unknown tab")
    label = tab_label_of(pool, tab_id)
    was = _remaining(pool, tab_id)
    if _live_run(bridge) and _image_of(page):
        return _clear_under_job(bridge, tab_id, label, was)
    cleared = _repair(pool, tab_id, page)
    _log(bridge, _clear_line(label, was, cleared), "success")
    _emit(bridge)
    _persist(bridge)
    return {"ok": True, "was": was, "busy": False, "job_cleared": cleared}


def _clear_under_job(bridge: Any, tab_id: str, label: str, was: int) -> dict:
    """A live job keeps its page — only the countdown is zeroed, and we say so."""
    _drop_timer(bridge, tab_id)
    _log(bridge, f"⏳ Clear time: {label} still running — {format_remaining(was)} removed, "
                 f"the job keeps its page", "warn")
    _emit(bridge)
    _persist(bridge)
    return {"ok": True, "was": was, "busy": True, "job_cleared": False}


def _drop_timer(bridge: Any, tab_id: str) -> None:
    """Zero the countdown fields only — the job, its image and its debt stay."""
    pool = _pool(bridge)
    if pool is None:
        return
    try:
        with pool._lock:
            page = pool._pages.get(tab_id)
            if page is not None:
                page.clear_timer()
    except Exception:
        pass


def _repair(pool: Any, tab_id: str, page) -> bool:
    """Free a really idle tab; a stale job goes with it (fixes F-1)."""
    if not _needs_reset(page):
        reset_cooldown(pool, tab_id)
        return False
    _forget_job(pool, tab_id)
    force_reset_page(pool, tab_id)
    return True


def _clear_line(label: str, was: int, cleared: bool) -> str:
    """The one line the operator reads after Clear time (RULE 2)."""
    tail = " (stale job cleared)" if cleared else ""
    if was > 0:
        return f"♻️ Clear time: {label} ready now — {format_remaining(was)} removed{tail}"
    return f"♻️ Clear time: {label} ready now — no timer to remove{tail}"
