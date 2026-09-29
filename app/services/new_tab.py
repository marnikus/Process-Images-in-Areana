"""Start new chat as new tab (I-79) — after a job the worker moves to a fresh tab.

Owner request 2026-09-28: with the Settings option on, a finished job's tab (failed
or success) is replaced: a new tab opens at the new-chat URL, the new chat is
verified, the old tab is closed and the close verified, and the next job runs in
the new tab. Same URL on both sides is no exception — the old tab still closes.

The worker keeps its identity (cooldown, captcha debt, job count, worker and
alias numbers): the pool entry, alias entry and URL row move to the new tab id,
and every CDP client on the old tab is re-`connect`-ed to the new one BEFORE the
old tab closes, so nothing chases a closed tab. Any failure before the move puts
everything back (clients home, new tab closed) and the caller runs the ordinary
in-place New Chat. The URL reconciler is held for the whole handover (its own
`_auto_scan_running` flag) so no pass sees a half-moved worker.

Chrome (CDP) tabs only: Firefox tabs are driven by macros that never open pages.
Design: docs/archive/2026-09-28-new-chat-new-tab/design.md
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional
from urllib.parse import urlparse

from app.browser.cdp.tabs import TabInfo, close_tab_sync, fetch_tabs_sync, open_tab_sync
from app.browser.chat_page import read_chat_page
from app.browser.new_chat import ResetCtx, wait_new_chat_ready
from app.browser.page_pool import retarget_page, tab_label_of
from app.services.live.url_policy import mark_receivers

SETTING_KEY = "new_chat_new_tab"
URL_KEY = "new_chat_new_tab_url"
DEFAULT_URL = "https://arena.ai/image/direct?model_a=max"
_RECONCILE_WAIT_SEC = 10.0
_GONE_WAIT_SEC = 5.0
_GONE_POLL_SEC = 0.2


# ── the setting (session keys, saved/loaded with the cooldown config) ──────

def clean_url(raw: Any) -> str:
    """An http(s) URL with a host, else the default new-chat URL."""
    url = str(raw or "").strip()
    parts = urlparse(url)
    return url if parts.scheme in ("http", "https") and parts.netloc else DEFAULT_URL


def read_setting(get_state) -> dict:
    """`{"enabled", "url"}` from the session; unreadable values heal to the defaults."""
    try:
        return {"enabled": bool(get_state(SETTING_KEY, False)),
                "url": clean_url(get_state(URL_KEY, DEFAULT_URL))}
    except Exception:
        return {"enabled": False, "url": DEFAULT_URL}


def save_setting(config: Any, data: dict) -> dict:
    """Store `new_tab` / `new_tab_url` when the payload has them; returns the stored setting."""
    if "new_tab" not in data:
        return read_setting(config.get_state)
    stored = {"enabled": bool(data.get("new_tab", False)), "url": clean_url(data.get("new_tab_url"))}
    config.set_state(**{SETTING_KEY: stored["enabled"], URL_KEY: stored["url"]})
    return stored


def wanted_url(bridge: Any) -> str:
    """The new-chat URL when the option is on, '' when it is off."""
    config = getattr(bridge, "config", None)
    setting = read_setting(config.get_state) if config is not None else {"enabled": False}
    return setting["url"] if setting["enabled"] else ""


# ── the handover ────────────────────────────────────────────────────────────

@dataclass
class _Move:
    """One handover: the finish context, where it goes, and what it came from."""
    ctx: Any
    url: str
    timeout_sec: float
    old_id: str = ""
    old_ws: str = ""
    old_url: str = ""
    label: str = ""
    endpoint: tuple = ("127.0.0.1", 9222)
    clients: List[Any] = field(default_factory=list)
    new: Optional[TabInfo] = None
    old_owner: str = ""
    old_context: str = ""
    pattern: str = "arena.ai"
    profile_count: int = 0


def _get_pattern(bridge: Any) -> str:
    """URL pattern that decides which tabs suit pool (default arena.ai)."""
    try:
        cfg = getattr(bridge, "config", None)
        if cfg is not None:
            return str(cfg.get_state("url_pattern", "arena.ai") or "arena.ai")
    except Exception:
        pass
    return "arena.ai"


def _matches_pattern(url: str, pattern: str) -> bool:
    try:
        return pattern.lower() in (url or "").lower()
    except Exception:
        return False


def _count_profile_tabs(pool: Any, endpoint: tuple, pattern: str) -> int:
    """How many pooled tabs from same endpoint match pattern (profile tab count)."""
    try:
        host, port = endpoint
        cnt = 0
        with pool._lock:
            for tid, page in pool._pages.items():
                try:
                    client, _ = pool.get_clients(tid)
                    ep = _endpoint_from_client(client)
                    if ep is None:
                        continue
                    if ep[0] != host or ep[1] != port:
                        continue
                    if _matches_pattern(getattr(page, "url", ""), pattern):
                        cnt += 1
                except Exception:
                    continue
        return cnt
    except Exception:
        return 0


async def handover(ctx: Any, url: str, timeout_sec: float) -> tuple[bool, str]:
    """Move the finished job's worker to a new tab at `url`; (False, why) = nothing changed."""
    move = _plan(ctx, url, timeout_sec)
    if move is None:
        return False, "the job's tab is not in the pool"
    if not await _hold_reconciler(ctx.bridge):
        return False, "a URL reconcile pass is still running"
    try:
        return await _run(move)
    finally:
        ctx.bridge._auto_scan_running = False


def _endpoint_from_client(client: Any) -> Optional[tuple]:
    """(host, port) from a CDP client, or None when missing."""
    try:
        h = getattr(client, "_host", None)
        p = getattr(client, "_port", None)
        if h and p:
            return str(h), int(p)
    except Exception:
        return None
    return None


def _resolve_endpoint(ctx: Any, pooled: Any) -> tuple:
    """Endpoint of the closed tab's browser: pooled client wins (profile-correct)."""
    for cli in (pooled, getattr(ctx, "client", None)):
        ep = _endpoint_from_client(cli)
        if ep is not None:
            return ep
    try:
        return str(ctx.pool._host), int(ctx.pool._port)
    except Exception:
        return "127.0.0.1", 9222


def _plan(ctx: Any, url: str, timeout_sec: float) -> Optional[_Move]:
    """What moves: the pool page of the job's tab, its endpoint and every client on it."""
    pool = getattr(ctx, "pool", None)
    page = pool.get_page(ctx.tab_id) if pool is not None else None
    if page is None:
        return None
    pooled, _ = pool.get_clients(ctx.tab_id)
    old_owner = str(getattr(page, "owner", "") or "")
    endpoint = _resolve_endpoint(ctx, pooled)
    pattern = _get_pattern(ctx.bridge)
    count = _count_profile_tabs(pool, endpoint, pattern)
    move = _Move(ctx, url, timeout_sec, ctx.tab_id, page.ws_url, page.url, tab_label_of(pool, ctx.tab_id))
    move.old_owner = old_owner
    move.endpoint = endpoint
    move.pattern = pattern
    move.profile_count = count
    move.clients = _clients_on(ctx)
    return move


def _clients_on(ctx: Any) -> list:
    """Every distinct client object on the old tab: the job's, the pool's, the home one."""
    pooled, _ctrl = ctx.pool.get_clients(ctx.tab_id)
    home = getattr(ctx.bridge, "cdp", None)
    found = [ctx.client, pooled, home if getattr(home, "_current_tab_id", None) == ctx.tab_id else None]
    unique: list = []
    for client in found:
        if client is not None and all(client is not seen for seen in unique):
            unique.append(client)
    return unique


async def _hold_reconciler(bridge: Any) -> bool:
    """Wait ≤ 10 s for a running reconcile pass, then take its flag (one loop: no race)."""
    deadline = time.monotonic() + _RECONCILE_WAIT_SEC
    while getattr(bridge, "_auto_scan_running", False):
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.05)
    bridge._auto_scan_running = True
    return True


async def _run(move: _Move) -> tuple[bool, str]:
    """Open + prove → move the worker → close the old tab; a failed proof rolls back."""
    _log(move, f"🗂 New chat as a new tab: opening {move.url} — {move.label}'s old tab "
               f"{move.old_id[:12]} ({move.old_url}) closes after — "
               f"profile {move.endpoint[0]}:{move.endpoint[1]} owner={move.old_owner or 'unknown'} "
               f"tabs matching '{move.pattern}' in profile: {move.profile_count}", "info")
    ok, why = await _open_and_prove(move)
    if not ok:
        await _roll_back(move, why)
        return False, why
    _move_worker(move)
    await _close_old(move)
    return True, f"new chat ready in the new tab {move.new.id[:12]}"


async def _open_and_prove(move: _Move) -> tuple[bool, str]:
    """Open the tab, move every client onto it, prove it is a ready new chat."""
    move.new, err = await _try_open_same_context(move)
    if move.new is None:
        move.new, err = await asyncio.to_thread(open_tab_sync, *move.endpoint, move.url)
    if move.new is None:
        return False, f"the new tab did not open ({err})"
    _log(move, f"🗂 New tab {move.new.id[:12]} opened at {move.new.url} — connecting {move.label}", "info")
    if not await _connect_all(move.clients, move.new.ws_url):
        return False, "could not connect to the new tab"
    return await _prove_new_chat(move)


def _pick_client_for_context(move: _Move) -> Any:
    """First available client for Target.createTarget (profile-correct)."""
    for c in move.clients:
        if c is not None:
            return c
    return getattr(move.ctx, "client", None)


async def _verify_context_same(move: _Move, client: Any, new_tab: TabInfo) -> tuple[bool, str]:
    """Check new tab context matches old (same Chrome profile)."""
    try:
        from app.browser.cdp.tabs import _context_of
        new_ctx = await _context_of(client, new_tab.id)
        if move.old_context and new_ctx is not None and str(new_ctx) != move.old_context:
            return False, f"context mismatch old={move.old_context} new={new_ctx} — wrong profile"
    except Exception:
        pass
    return True, ""


async def _try_open_same_context(move: _Move) -> tuple[Optional[TabInfo], str]:
    """Try CDP Target.createTarget in same browser context (keeps Arena account)."""
    try:
        from app.browser.cdp.tabs import open_tab_in_same_context
        client = _pick_client_for_context(move)
        if client is None:
            return None, "no client for context open"
        try:
            move.old_context = await _get_old_context_id(move)
        except Exception:
            move.old_context = ""
        new_tab, err = await open_tab_in_same_context(client, *move.endpoint, move.url, move.old_id)
        if new_tab is None:
            return None, err
        ok, why = await _verify_context_same(move, client, new_tab)
        if not ok:
            return None, why
        return new_tab, ""
    except Exception as e:
        return None, str(e)


async def _prove_new_chat(move: _Move) -> tuple[bool, str]:
    """The reset's readiness proof, then the new-chat check the next job's gate also runs."""
    ctx = move.ctx
    reset_ctx = ResetCtx(ctrl=ctx.ctrl, client=ctx.client, engine=ctx.bridge, timeout_sec=move.timeout_sec,
                         cancel_check=lambda: bool(getattr(ctx.bridge, "_cancel_requested", False)),
                         purpose="in the new tab")
    ready, why = await wait_new_chat_ready(reset_ctx)
    if not ready:
        return False, f"the new tab never got ready ({why})"
    is_new, why = await read_chat_page(ctx.client)
    if is_new is not True:
        return False, f"the new tab is not a new chat ({why})"
    owner_ok, owner_why = await _check_owner_preserved(move)
    if not owner_ok:
        return False, owner_why
    _log(move, f"🆕 New chat verified in the new tab {move.new.id[:12]} ({why})", "success")
    return True, why


async def _read_owner_from_client(client: Any) -> str:
    """Probe account email from a tab's client ('' when unknown)."""
    try:
        from app.browser.owner_probe import build_owner_probe, interpret_owner
        from app.core.tab_alias import normalize_owner
        raw = await client.evaluate(build_owner_probe())
        return normalize_owner(interpret_owner(raw).get("email"))
    except Exception:
        return ""


async def _check_owner_preserved(move: _Move) -> tuple[bool, str]:
    """Ensure new tab has same Arena account as old tab (profile-correct)."""
    if not move.old_owner:
        return True, ""
    try:
        new_owner = await _read_owner_from_client(move.ctx.client)
    except Exception:
        new_owner = ""
    if not new_owner:
        _log(move, f"Owner probe empty for new tab {move.new.id[:12]} — keeping {move.old_owner}", "info")
        return True, ""
    if new_owner.lower() == move.old_owner.lower():
        return True, ""
    return False, f"Owner mismatch: old {move.old_owner} vs new {new_owner} — wrong profile, rollback"


async def _get_old_context_id(move: _Move) -> str:
    """BrowserContextId of old tab ('' for default)."""
    try:
        from app.browser.cdp.tabs import _context_of
        for cli in move.clients:
            if cli is None:
                continue
            ctx_id = await _context_of(cli, move.old_id)
            if ctx_id is not None:
                return str(ctx_id)
            # Also try without filter: if _context_of returns None, it may still have context
            # Try to get any context from client that matches old_id
            try:
                resp = await cli.send("Target.getTargets")
                infos = resp.get("result", {}).get("targetInfos", []) if isinstance(resp, dict) else []
                for info in infos:
                    if info.get("targetId") == move.old_id:
                        return str(info.get("browserContextId") or "")
            except Exception:
                pass
    except Exception:
        pass
    return ""


async def _get_new_context_id(move: _Move) -> str:
    """BrowserContextId of new tab."""
    try:
        from app.browser.cdp.tabs import _context_of
        for cli in move.clients:
            if cli is None:
                continue
            ctx_id = await _context_of(cli, move.new.id)
            if ctx_id is not None:
                return str(ctx_id)
    except Exception:
        pass
    return ""


async def _connect_all(clients: list, ws_url: str) -> bool:
    """Re-point every client object (holders follow without being told)."""
    results = [await client.connect(ws_url) for client in clients]
    return all(results)


async def _roll_back(move: _Move, why: str) -> None:
    """Nothing changes: every client back on the old tab, the new tab closed again."""
    if move.new is not None:
        await _connect_all(move.clients, move.old_ws)
        await asyncio.to_thread(close_tab_sync, *move.endpoint, move.new.id)
    _log(move, f"⚠ New chat as a new tab failed: {why} — {move.label} stays in its tab "
               f"(in-place New Chat instead)", "warn")


def _move_worker(move: _Move) -> None:
    """Pool entry, alias number and URL row now name the new tab; persisted + shown."""
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
    _log(move, f"🗂 {move.label} now works in tab {new.id[:12]} (was {move.old_id[:12]}) — "
               f"cooldown, job count and number kept — profile {move.endpoint[0]}:{move.endpoint[1]} "
               f"tabs matching '{move.pattern}': {move.profile_count} → {new_count}", "info")


def _preserve_owner_after_move(pool: Any, new_id: str, old_owner: str) -> None:
    """Keep old Arena account on new tab (profile-correct)."""
    if not old_owner:
        return
    try:
        page = pool.get_page(new_id)
        if page is not None:
            page.owner = old_owner
        book = getattr(pool, "_alias", None)
        if book is not None:
            with pool._lock:
                ent = book._entries.get(new_id)
                if ent is not None:
                    ent["email"] = old_owner
    except Exception:
        pass


async def _close_old(move: _Move) -> bool:
    """Close the old tab (also on the same URL) and prove it left the list; one retry."""
    same = " — it showed the same new-chat URL; one tab per worker" if move.old_url == move.url else ""
    for _attempt in (1, 2):
        await asyncio.to_thread(close_tab_sync, *move.endpoint, move.old_id)
        if await _gone(move):
            _log(move, f"🗂 Old tab closed and verified gone ({move.old_id[:12]}){same}", "success")
            return True
    _log(move, f"🗂 Old tab {move.old_id[:12]} is still open after two closes — close it by hand, "
               f"or it comes back as a new URL row", "error")
    return False


async def _gone(move: _Move) -> bool:
    """Poll the endpoint's tab list until the old id is absent (≤ 5 s)."""
    deadline = time.monotonic() + _GONE_WAIT_SEC
    while True:
        tabs, err, _tried = await asyncio.to_thread(fetch_tabs_sync, *move.endpoint)
        if not err and all(tab.id != move.old_id for tab in tabs):
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(_GONE_POLL_SEC)


def _quietly(step: Any) -> None:
    """Run a bridge side effect; a failing one never breaks the finished job."""
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
