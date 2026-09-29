from __future__ import annotations
import asyncio
from typing import Any
from app.browser.new_chat import ResetCtx
from ..context import _try_open_same_context
from ..cookies import _get_cookies_from_move, _reload_after_cookies, _set_cookies_to_move
from ..storage import _get_storage_from_move, _set_storage_to_move
from .patches import _open_tab_sync, _read_chat_page, _wait_new_chat_ready
from .utils import _connect_all, _log

async def _open_and_prove(move) -> tuple[bool, str]:
    old_cookies = await _get_cookies_from_move(move)
    old_storage = await _get_storage_from_move(move)
    move.new, err = await _try_open_same_context(move)
    if move.new is None:
        move.new, err = await asyncio.to_thread(_open_tab_sync, *move.endpoint, move.url)
    if move.new is None:
        return False, f"the new tab did not open ({err})"
    _log(move, f"🗂 New tab {move.new.id[:12]} opened at {move.new.url} — connecting {move.label} ctx={move.old_context or 'default'}", "info")
    if not await _connect_all(move.clients, move.new.ws_url):
        return False, "could not connect to the new tab"
    if old_cookies:
        await _set_cookies_to_move(move, old_cookies)
    if old_storage:
        await _set_storage_to_move(move, old_storage)
    if old_cookies or old_storage:
        await _reload_after_cookies(move)
    return await _prove_new_chat(move)

async def _prove_new_chat(move) -> tuple[bool, str]:
    ctx = move.ctx
    reset_ctx = ResetCtx(ctrl=ctx.ctrl, client=ctx.client, engine=ctx.bridge, timeout_sec=move.timeout_sec, cancel_check=lambda: bool(getattr(ctx.bridge, "_cancel_requested", False)), purpose="in the new tab")
    ready, why = await _wait_new_chat_ready(reset_ctx)
    if not ready:
        return False, f"the new tab never got ready ({why})"
    is_new, why = await _read_chat_page(ctx.client)
    if is_new is not True:
        return False, f"the new tab is not a new chat ({why})"
    from ..owner import _check_owner_preserved
    owner_ok, owner_why = await _check_owner_preserved(move)
    if not owner_ok:
        return False, owner_why
    _log(move, f"🆕 New chat verified in the new tab {move.new.id[:12]} ({why})", "success")
    return True, why
