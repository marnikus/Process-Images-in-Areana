# ideal-size: 200 lines reason=handover orchestrates open+prove→move→close that always changes together per RULE 18.2
"""Handover orchestration — open new tab, prove ready, move worker, close old."""

from __future__ import annotations

import asyncio
import sys
import time
from typing import Any

from app.browser.cdp.tabs import TabInfo
from app.browser.cdp.tabs import close_tab_sync as _real_close
from app.browser.cdp.tabs import fetch_tabs_sync as _real_fetch
from app.browser.cdp.tabs import open_tab_sync as _real_open
from app.browser.chat_page import read_chat_page as _real_read
from app.browser.new_chat import ResetCtx, wait_new_chat_ready as _real_wait
from app.browser.page_pool import retarget_page
from app.services.live.url_policy import mark_receivers

from .context import _try_open_same_context
from .cookies import _get_cookies_from_move, _reload_after_cookies, _set_cookies_to_move
from .matching import _count_profile_tabs, _count_profile_tabs_by_owner
from .move import _Move, _plan
from .owner import _check_owner_preserved, _preserve_owner_after_move
from .storage import _get_storage_from_move, _set_storage_to_move

_RECONCILE_WAIT_SEC = 10.0
_GONE_WAIT_SEC = 5.0
_GONE_POLL_SEC = 0.2


def _patched(name: str, default):
    """Return patched version from parent package if monkeypatched, else default."""
    try:
        mod = sys.modules.get("app.services.new_tab")
        if mod is not None and hasattr(mod, name):
            val = getattr(mod, name)
            # If it's the same as default, still return it (patched may be same)
            # We return whatever is on parent if it exists and is not the module itself
            if val is not default or name in mod.__dict__:
                return val
    except Exception:
        pass
    return default


def _open_tab_sync(*args, **kwargs):
    fn = _patched("open_tab_sync", _real_open)
    return fn(*args, **kwargs)


def _close_tab_sync(*args, **kwargs):
    fn = _patched("close_tab_sync", _real_close)
    return fn(*args, **kwargs)


def _fetch_tabs_sync(*args, **kwargs):
    fn = _patched("fetch_tabs_sync", _real_fetch)
    return fn(*args, **kwargs)


async def _wait_new_chat_ready(*args, **kwargs):
    fn = _patched("wait_new_chat_ready", _real_wait)
    return await fn(*args, **kwargs)


async def _read_chat_page(*args, **kwargs):
    fn = _patched("read_chat_page", _real_read)
    return await fn(*args, **kwargs)


def _get_const(name: str, default: float) -> float:
    try:
        mod = sys.modules.get("app.services.new_tab")
        if mod is not None and hasattr(mod, name):
            return float(getattr(mod, name))
    except Exception:
        pass
    return default


async def handover(ctx: Any, url: str, timeout_sec: float) -> tuple[bool, str]:
    """Move finished job's worker to a new tab at `url`; (False, why) = nothing changed."""
    move = _plan(ctx, url, timeout_sec)
    if move is None:
        return False, "the job's tab is not in the pool"
    if not await _hold_reconciler(ctx.bridge):
        return False, "a URL reconcile pass is still running"
    try:
        return await _run(move)
    finally:
        ctx.bridge._auto_scan_running = False


async def _hold_reconciler(bridge: Any) -> bool:
    wait_sec = _get_const("_RECONCILE_WAIT_SEC", _RECONCILE_WAIT_SEC)
    deadline = time.monotonic() + wait_sec
    while getattr(bridge, "_auto_scan_running", False):
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.05)
    bridge._auto_scan_running = True
    return True


async def _run(move: _Move) -> tuple[bool, str]:
    """Open + prove → move worker → close old tab; failed proof rolls back."""
    _log(move, f"🗂 New chat as a new tab: opening {move.url} — {move.label}'s old tab "
               f"{move.old_id[:12]} ({move.old_url}) closes after — "
               f"profile {move.endpoint[0]}:{move.endpoint[1]} owner={move.old_owner or 'unknown'} "
               f"ctx={move.old_context or 'default'} "
               f"tabs matching '{move.pattern}' in profile: {move.profile_count} "
               f"(owner {move.old_owner or '?'}: {move.profile_count_owner})", "info")
    ok, why = await _open_and_prove(move)
    if not ok:
        await _roll_back(move, why)
        return False, why
    _move_worker(move)
    await _close_old(move)
    return True, f"new chat ready in the new tab {move.new.id[:12]}"


async def _open_and_prove(move: _Move) -> tuple[bool, str]:
    """Open tab, move clients onto it, prove ready new chat."""
    old_cookies = await _get_cookies_from_move(move)
    old_storage = await _get_storage_from_move(move)
    move.new, err = await _try_open_same_context(move)
    if move.new is None:
        move.new, err = await asyncio.to_thread(_open_tab_sync, *move.endpoint, move.url)
    if move.new is None:
        return False, f"the new tab did not open ({err})"
    _log(move, f"🗂 New tab {move.new.id[:12]} opened at {move.new.url} — "
               f"connecting {move.label} ctx={move.old_context or 'default'}", "info")
    if not await _connect_all(move.clients, move.new.ws_url):
        return False, "could not connect to the new tab"
    if old_cookies:
        await _set_cookies_to_move(move, old_cookies)
    if old_storage:
        await _set_storage_to_move(move, old_storage)
    if old_cookies or old_storage:
        await _reload_after_cookies(move)
    return await _prove_new_chat(move)


async def _prove_new_chat(move: _Move) -> tuple[bool, str]:
    """Reset readiness proof + new-chat check + owner check."""
    ctx = move.ctx
    reset_ctx = ResetCtx(ctrl=ctx.ctrl, client=ctx.client, engine=ctx.bridge,
                         timeout_sec=move.timeout_sec,
                         cancel_check=lambda: bool(getattr(ctx.bridge, "_cancel_requested", False)),
                         purpose="in the new tab")
    ready, why = await _wait_new_chat_ready(reset_ctx)
    if not ready:
        return False, f"the new tab never got ready ({why})"
    is_new, why = await _read_chat_page(ctx.client)
    if is_new is not True:
        return False, f"the new tab is not a new chat ({why})"
    owner_ok, owner_why = await _check_owner_preserved(move)
    if not owner_ok:
        return False, owner_why
    _log(move, f"🆕 New chat verified in the new tab {move.new.id[:12]} ({why})", "success")
    return True, why


async def _connect_all(clients: list, ws_url: str) -> bool:
    """Re-point every client object (holders follow without being told)."""
    results = [await client.connect(ws_url) for client in clients]
    return all(results)


async def _roll_back(move: _Move, why: str) -> None:
    """Nothing changes: every client back on old tab, new tab closed."""
    if move.new is not None:
        await _connect_all(move.clients, move.old_ws)
        await asyncio.to_thread(_close_tab_sync, *move.endpoint, move.new.id)
    _log(move, f"⚠ New chat as a new tab failed: {why} — {move.label} stays in its tab "
               f"(in-place New Chat instead)", "warn")


def _move_worker(move: _Move) -> None:
    """Pool entry, alias number and URL row now name new tab; persisted + shown."""
    ctx, new = move.ctx, move.new
    retarget_page(ctx.pool, move.old_id, new)
    _preserve_owner_after_move(ctx.pool, new.id, move.old_owner)
    for row in ctx.bridge.state.urls:
        if row.tab_id == move.old_id:
            row.tab_id, row.url = new.id, new.url or move.url
    ctx.tab_id = new.id
    mark_receivers(ctx.bridge.state.urls, ctx.pool)
    for step in ("_save_arena", "_persist_cooldowns", "_emit_pool_status"):
        _quietly(getattr(ctx.bridge, step, None))
    new_count = _count_profile_tabs(ctx.pool, move.endpoint, move.pattern)
    new_count_owner = _count_profile_tabs_by_owner(ctx.pool, move.endpoint,
                                                   move.pattern, move.old_owner)
    _log(move, f"🗂 {move.label} now works in tab {new.id[:12]} (was {move.old_id[:12]}) — "
               f"cooldown, job count and number kept — profile {move.endpoint[0]}:{move.endpoint[1]} "
               f"ctx={move.old_context or 'default'} owner={move.old_owner or '?'} "
               f"tabs matching '{move.pattern}': {move.profile_count} → {new_count} "
               f"(owner {move.old_owner or '?'}: {move.profile_count_owner} → {new_count_owner})",
         "info")


async def _close_old(move: _Move) -> bool:
    """Close old tab and prove it left list; one retry."""
    same = " — it showed the same new-chat URL; one tab per worker" if move.old_url == move.url else ""
    for _attempt in (1, 2):
        await asyncio.to_thread(_close_tab_sync, *move.endpoint, move.old_id)
        if await _gone(move):
            _log(move, f"🗂 Old tab closed and verified gone ({move.old_id[:12]}){same}", "success")
            return True
    _log(move, f"🗂 Old tab {move.old_id[:12]} is still open after two closes — close it by hand, "
               f"or it comes back as a new URL row", "error")
    return False


async def _gone(move: _Move) -> bool:
    """Poll endpoint's tab list until old id absent."""
    gone_wait = _get_const("_GONE_WAIT_SEC", _GONE_WAIT_SEC)
    poll_sec = _get_const("_GONE_POLL_SEC", _GONE_POLL_SEC)
    deadline = time.monotonic() + gone_wait
    while True:
        tabs, err, _tried = await asyncio.to_thread(_fetch_tabs_sync, *move.endpoint)
        if not err and all(tab.id != move.old_id for tab in tabs):
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(poll_sec)


def _quietly(step: Any) -> None:
    """Run bridge side effect; failing one never breaks finished job."""
    try:
        if step is not None:
            step()
    except Exception:
        pass


def _log(move: _Move, message: str, level: str) -> None:
    try:
        move.ctx.bridge._log(message, level)
    except Exception:
        pass
