from __future__ import annotations
import asyncio
import time
from typing import Any
from app.browser.page_pool import retarget_page
from app.services.live.url_policy import mark_receivers
from ..matching import _count_profile_tabs, _count_profile_tabs_by_owner
from ..owner import _preserve_owner_after_move
from .patches import _close_tab_sync, _fetch_tabs_sync, _get_const
from .utils import _connect_all, _log, _quietly

_GONE_WAIT_SEC = 5.0
_GONE_POLL_SEC = 0.2

async def _roll_back(move, why: str) -> None:
    if move.new is not None:
        await _connect_all(move.clients, move.old_ws)
        await asyncio.to_thread(_close_tab_sync, *move.endpoint, move.new.id)
    _log(move, f"⚠ New chat as a new tab failed: {why} — {move.label} stays in its tab (in-place New Chat instead)", "warn")

def _move_worker(move) -> None:
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
    new_count_owner = _count_profile_tabs_by_owner(ctx.pool, move.endpoint, move.pattern, move.old_owner)
    _log(move, f"🗂 {move.label} now works in tab {new.id[:12]} (was {move.old_id[:12]}) — cooldown, job count and number kept — profile {move.endpoint[0]}:{move.endpoint[1]} ctx={move.old_context or 'default'} owner={move.old_owner or '?'} tabs matching '{move.pattern}': {move.profile_count} → {new_count} (owner {move.old_owner or '?'}: {move.profile_count_owner} → {new_count_owner})", "info")

async def _close_old(move) -> bool:
    same = " — it showed the same new-chat URL; one tab per worker" if move.old_url == move.url else ""
    for _attempt in (1, 2):
        await asyncio.to_thread(_close_tab_sync, *move.endpoint, move.old_id)
        if await _gone(move):
            _log(move, f"🗂 Old tab closed and verified gone ({move.old_id[:12]}){same}", "success")
            return True
    _log(move, f"🗂 Old tab {move.old_id[:12]} is still open after two closes — close it by hand, or it comes back as a new URL row", "error")
    return False

async def _gone(move) -> bool:
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
