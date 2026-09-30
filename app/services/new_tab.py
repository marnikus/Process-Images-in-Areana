"""Start new chat as new tab (I-79 v5) — the job tab's own browser profile decides.

Owner request 2026-09-28; profile-truth rewrite 2026-09-29 (owner report #2: with two Chrome
profiles running, the second profile's new tab opened in the first profile and the first profile's
tab was closed instead). The setting itself lives in `new_tab_setting.py`.

With the option on, a finished job's tab (failed or success) is replaced: a new tab opens at the
new-chat URL **inside the job tab's own browser profile**, the new chat is verified, the old tab is
closed and the close is proven against that browser's own target list. Same URL on both sides is no
exception — the old tab still closes.

The profile is established, never guessed: the endpoint is the job tab's own socket (`ws_url`), the
expected context is the browser-level `Target.getTargets` of that endpoint, and the opener is the
only one that can reach it (`new_tab_open`, R1–R3). Another context → tab closed again → in-place.

The worker keeps its identity (cooldown, job count, alias and worker numbers, URL row): the I-79
move; any failure before it puts everything back (clients home, new tab closed). The URL reconciler
is held for the whole handover. Chrome (CDP) tabs only (Firefox macros never open pages). Design:
docs/archive/2026-09-29-new-chat-new-tab-profile-truth/design.md
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional

from app.browser.cdp import browser_targets as bt
from app.browser.cdp.tabs import TabInfo
from app.browser.chat_page import read_chat_page
from app.browser.new_chat import ResetCtx, wait_new_chat_ready
from app.browser.page_pool import retarget_page, tab_label_of
from app.services.live import reconcile
from app.services.live.url_policy import mark_receivers
from app.services.new_tab_open import OpenSpec, open_in_profile

_RECONCILE_WAIT_SEC = 10.0
_OWNER_TRIES = 2
_OWNER_RETRY_SEC = 0.5


@dataclass
class _Move:
    """One handover: the finish context, the job tab's own endpoint and what it came from."""
    ctx: Any
    url: str
    timeout_sec: float
    endpoint: tuple
    old_id: str = ""
    old_ws: str = ""
    old_url: str = ""
    label: str = ""
    owner: str = ""
    pattern: str = "arena.ai"
    context_id: str = ""
    clients: List[Any] = field(default_factory=list)
    new_id: str = ""
    new_ws: str = ""


def _get_pattern(bridge: Any) -> str:
    """URL pattern that decides which tabs suit pool (default arena.ai)."""
    try:
        cfg = getattr(bridge, "config", None)
        if cfg is not None:
            return str(cfg.get_state("url_pattern", "arena.ai") or "arena.ai")
    except Exception:
        pass
    return "arena.ai"


def _unique(clients: list) -> list:
    """Same client object listed twice (job's, pool's, home's) connects once."""
    unique: list = []
    for client in clients:
        if client is not None and all(client is not seen for seen in unique):
            unique.append(client)
    return unique


def _clients_on(ctx: Any, pooled: Any) -> list:
    """Every distinct client object on the old tab: the job's, the pool's, the home one."""
    home = getattr(ctx.bridge, "cdp", None)
    live_home = home if getattr(home, "_current_tab_id", None) == ctx.tab_id else None
    return _unique([ctx.client, pooled, live_home])


def _popup_client(move: _Move) -> Any:
    """The client whose socket sits on the job tab — the page opener must run there (R3b)."""
    for client in move.clients:
        if getattr(client, "_current_tab_id", None) == move.old_id:
            return client
    return None


def _plan(ctx: Any, url: str, timeout_sec: float) -> tuple[Optional[_Move], str]:
    """What moves: the pool page of the job's tab, its own socket's endpoint, every client."""
    pool = getattr(ctx, "pool", None)
    page = pool.get_page(ctx.tab_id) if pool is not None else None
    if page is None:
        return None, "the job's tab is not in the pool"
    endpoint = bt.endpoint_of_ws(getattr(page, "ws_url", ""))
    if endpoint is None:
        return None, f"the job tab {ctx.tab_id[:12]} has no readable socket (ws_url)"
    pooled, _ctrl = pool.get_clients(ctx.tab_id)
    move = _Move(ctx=ctx, url=url, timeout_sec=timeout_sec, endpoint=endpoint,
                 old_id=ctx.tab_id, old_ws=page.ws_url, old_url=page.url,
                 label=tab_label_of(pool, ctx.tab_id), pattern=_get_pattern(ctx.bridge),
                 owner=str(getattr(page, "owner", "") or ""))
    move.clients = _clients_on(ctx, pooled)
    return move, ""


async def handover(ctx: Any, url: str, timeout_sec: float) -> tuple[bool, str]:
    """Move the finished job's worker to a new tab at `url`; (False, why) = nothing changed."""
    move, why = _plan(ctx, url, timeout_sec)
    if move is None:
        return False, why
    if not await _hold_reconciler(ctx.bridge):
        return False, "a URL reconcile pass is still running"
    try:
        return await _with_browser(move)
    finally:
        # through reconcile.release(), NOT a bare `= False`: the handover holds a
        # flag it does not own, and the holder that ends a pass must also drain
        # the Reparse queue it may have stranded (I-68a, audit #4 N1).
        reconcile.release(ctx.bridge)


async def _hold_reconciler(bridge: Any) -> bool:
    """Wait ≤ 10 s for a running reconcile pass, then take its flag (one loop: no race)."""
    deadline = time.monotonic() + _RECONCILE_WAIT_SEC
    while getattr(bridge, "_auto_scan_running", False):
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.05)
    bridge._auto_scan_running = True
    return True


async def _with_browser(move: _Move) -> tuple[bool, str]:
    """One browser-level connection to the job tab's own endpoint, opened and closed here (R2)."""
    browser, err = await bt.dial(*move.endpoint, timeout_sec=min(move.timeout_sec, 5.0))
    if browser is None:
        return False, f"the job's browser is not reachable ({err})"
    try:
        return await _run(move, browser)
    finally:
        await browser.aclose()


async def _run(move: _Move, browser: Any) -> tuple[bool, str]:
    """Read the profile truth → open in it → prove a new chat → move the worker → close old."""
    target_infos, err = await browser.targets()
    if err:
        return False, f"the job's browser did not answer Target.getTargets ({err})"
    context = bt.context_of(target_infos, move.old_id)
    if context is None:
        return False, f"the job tab {move.old_id[:12]} is not in its own browser's target list"
    move.context_id = context
    _log_profile(move, target_infos)
    opened = await open_in_profile(browser, _popup_client(move),
                                   OpenSpec(move.url, context, move.timeout_sec))
    if not opened.tab_id:
        return await _refuse(move, browser, opened.reason)
    move.new_id, move.new_ws = opened.tab_id, _page_ws(move, opened.tab_id)
    if not await _connect_all(move.clients, move.new_ws):
        return await _refuse(move, browser, "could not connect to the new tab")
    ok, why = await _prove_new_chat(move)
    if not ok:
        return await _refuse(move, browser, why)
    _move_worker(move)
    return _done(move, await _close_old(move, browser))


def _done(move: _Move, old_closed: bool) -> tuple[bool, str]:
    """The handover's own answer. The worker moved either way, so this is `True`
    even when the old tab would not close — but then the answer says so (N2):
    `handover`'s "(False, why) = nothing changed" must stay the only way to say
    nothing changed."""
    ready = f"new chat ready in the new tab {move.new_id[:12]}"
    if old_closed:
        return True, ready
    return True, f"{ready}, but the old tab {move.old_id[:12]} is still open — close it by hand"


async def _refuse(move: _Move, browser: Any, why: str) -> tuple[bool, str]:
    """Roll back and report; the caller then runs the ordinary in-place New Chat."""
    if move.new_id:
        await _connect_all(move.clients, move.old_ws)
        await browser.close(move.new_id)
    _log(move, f"⚠ New chat as a new tab failed: {why} — {move.label} stays in its tab "
               f"(in-place New Chat instead)", "warn")
    return False, why


def _page_ws(move: _Move, target_id: str) -> str:
    """The job tab's own page socket for the new target (same host:port it belongs to)."""
    return f"ws://{move.endpoint[0]}:{move.endpoint[1]}/devtools/page/{target_id}"


def _log_profile(move: _Move, target_infos: list) -> None:
    """What the browser proved: endpoint, context, owner and the same-profile counts (R5)."""
    same = len(bt.matching_targets(target_infos, move.pattern, move.context_id))
    total = len(bt.matching_targets(target_infos, move.pattern))
    _log(move, f"🗂 New chat as a new tab: opening {move.url} — {move.label}'s old tab "
               f"{move.old_id[:12]} ({move.old_url}) closes after — profile {move.endpoint[0]}:"
               f"{move.endpoint[1]} ctx={move.context_id or 'default'} "
               f"owner={move.owner or 'unknown'} — tabs matching '{move.pattern}': "
               f"this profile: {same} | all contexts: {total}", "info")


async def _connect_all(clients: list, ws_url: str) -> bool:
    """Re-point every client object (holders follow without being told)."""
    results = [await client.connect(ws_url) for client in clients]
    return all(results)


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
    _log(move, f"🆕 New chat verified in the new tab {move.new_id[:12]} ({why})", "success")
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
    """Secondary guard: the new tab must not be signed in as somebody else (label ≠ profile)."""
    if not move.owner:
        return True, ""
    new_owner = ""
    for _attempt in range(_OWNER_TRIES):
        new_owner = await _read_owner_from_client(move.ctx.client)
        if new_owner:
            break
        await asyncio.sleep(_OWNER_RETRY_SEC)
    if not new_owner:
        _log(move, f"Owner probe empty for the new tab {move.new_id[:12]} — keeping "
                   f"{move.owner} (the browser already proved the profile)", "info")
        return True, ""
    if new_owner == move.owner.lower():
        return True, ""
    return False, f"Owner mismatch: old {move.owner} vs new {new_owner} — wrong profile, rollback"


def _move_worker(move: _Move) -> None:
    """Pool entry, alias number and URL row now name the new tab; persisted + shown."""
    ctx, new_id = move.ctx, move.new_id
    retarget_page(ctx.pool, move.old_id, TabInfo(id=new_id, title="", url=move.url, ws_url=move.new_ws))
    for row in ctx.bridge.state.urls:
        if row.tab_id == move.old_id:
            row.tab_id, row.url = new_id, move.url
    ctx.tab_id = new_id
    mark_receivers(ctx.bridge.state.urls, ctx.pool)
    for step in ("_save_arena", "_persist_cooldowns", "_emit_pool_status"):
        _quietly(getattr(ctx.bridge, step, None))
    _log(move, f"🗂 {move.label} now works in tab {new_id[:12]} (was {move.old_id[:12]}) — "
               f"cooldown, job count and number kept — profile {move.endpoint[0]}:{move.endpoint[1]} "
               f"ctx={move.context_id or 'default'} owner={move.owner or '?'}", "info")


async def _close_old(move: _Move, browser: Any) -> bool:
    """Close the old tab (also on the same URL) and prove it left the list; one retry (R4)."""
    same = " — it showed the same new-chat URL; one tab per worker" if move.old_url == move.url else ""
    for _attempt in (1, 2):
        await browser.close(move.old_id)
        target_infos, err = await browser.targets()
        if err == "" and bt.target_of(target_infos, move.old_id) is None:
            _log(move, f"🗂 Old tab closed and verified gone ({move.old_id[:12]}){same}", "success")
            return True
    _log(move, f"🗂 Old tab {move.old_id[:12]} is still open after two closes — close it by hand, "
               f"or it comes back as a new URL row", "error")
    return False



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
