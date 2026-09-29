from __future__ import annotations
from typing import Any
from ..move import _Move, _plan
from .reconcile import _hold_reconciler
from .open_prove import _open_and_prove
from .move_close import _roll_back, _move_worker, _close_old
from .utils import _log

async def handover(ctx: Any, url: str, timeout_sec: float) -> tuple[bool, str]:
    move = _plan(ctx, url, timeout_sec)
    if move is None:
        return False, "the job's tab is not in the pool"
    if not await _hold_reconciler(ctx.bridge):
        return False, "a URL reconcile pass is still running"
    try:
        return await _run(move)
    finally:
        ctx.bridge._auto_scan_running = False

async def _run(move: _Move) -> tuple[bool, str]:
    _log(move, f"🗂 New chat as a new tab: opening {move.url} — {move.label}'s old tab {move.old_id[:12]} ({move.old_url}) closes after — profile {move.endpoint[0]}:{move.endpoint[1]} owner={move.old_owner or 'unknown'} ctx={move.old_context or 'default'} tabs matching '{move.pattern}' in profile: {move.profile_count} (owner {move.old_owner or '?'}: {move.profile_count_owner})", "info")
    ok, why = await _open_and_prove(move)
    if not ok:
        await _roll_back(move, why)
        return False, why
    _move_worker(move)
    await _close_old(move)
    return True, f"new chat ready in the new tab {move.new.id[:12]}"
