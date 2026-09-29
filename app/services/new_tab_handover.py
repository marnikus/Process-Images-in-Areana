"""Identity-proven, rollback-safe Chrome tab handover for New Chat.

The candidate is created through browser-level CDP in the verified source
context. No worker holder changes until page readiness, New Chat, context and
stable Arena-account proofs all pass.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from app.browser.cdp.tabs import TabInfo, close_tab_sync, fetch_tabs_sync
from app.browser.page_pool import retarget_page, tab_label_of
from app.services.live.url_policy import mark_receivers
from .new_tab_identity import dispose_proof, prove_candidate

RECONCILE_WAIT_SEC = 10.0
GONE_WAIT_SEC = 5.0
GONE_POLL_SEC = 0.2


@dataclass
class Handover:
    """One job's source identity, verified candidate and client transaction."""
    ctx: Any
    url: str
    timeout_sec: float
    old_id: str
    old_ws: str
    old_url: str
    label: str
    endpoint: tuple[int, int]
    old_owner: str
    clients: list[Any] = field(default_factory=list)
    new: TabInfo | None = None


async def handover(ctx: Any, url: str, timeout_sec: float) -> tuple[bool, str]:
    """Prove, then move; any pre-commit failure leaves the old worker untouched."""
    move, why = await _plan(ctx, url, timeout_sec)
    if move is None:
        return False, why
    if not await _hold_reconciler(ctx.bridge):
        return False, "a URL reconcile pass is still running"
    try:
        return await _transact(move)
    finally:
        ctx.bridge._auto_scan_running = False


async def _plan(ctx, url, timeout_sec) -> tuple[Handover | None, str]:
    pool = getattr(ctx, "pool", None)
    page = pool.get_page(ctx.tab_id) if pool is not None else None
    if page is None:
        return None, "the job's tab is not in the pool"
    endpoint, why = _source_endpoint(page.ws_url, ctx.tab_id, pool.get_clients(ctx.tab_id)[0], ctx.client)
    if endpoint is None:
        return None, why
    owner = ""
    pooled, _ = pool.get_clients(ctx.tab_id)
    clients = _worker_clients(ctx, pooled, endpoint)
    move = Handover(ctx, url, timeout_sec, ctx.tab_id, page.ws_url, page.url,
                    tab_label_of(pool, ctx.tab_id), endpoint, owner, clients)
    return move, ""


def _source_endpoint(ws_url: str, tab_id: str, pooled, job_client) -> tuple[tuple | None, str]:
    endpoint, why = _parse_source_endpoint(ws_url, tab_id)
    if endpoint is None:
        return None, why
    for label, client in (("pooled", pooled), ("job", job_client)):
        if _client_endpoint(client) != endpoint:
            return None, f"{label} client endpoint does not match source tab endpoint"
    return endpoint, ""


def _parse_source_endpoint(ws_url: str, tab_id: str) -> tuple[tuple | None, str]:
    try:
        parts = urlsplit(str(ws_url or ""))
        target_id = parts.path.rsplit("/", 1)[-1]
        if parts.scheme not in ("ws", "wss") or not parts.hostname or target_id != tab_id:
            return None, "source tab websocket does not prove its target id and endpoint"
        port = parts.port or (443 if parts.scheme == "wss" else 80)
        return (_local_host(parts.hostname), port), ""
    except Exception:
        return None, "source tab websocket endpoint is invalid"


def _local_host(host: str) -> str:
    return "127.0.0.1" if host.lower() == "localhost" else host.lower()


def _client_endpoint(client) -> tuple | None:
    try:
        host, port = str(client._host), int(client._port)
        return _local_host(host), port
    except Exception:
        return None


def _worker_clients(ctx, pooled, endpoint) -> list:
    home = getattr(ctx.bridge, "cdp", None)
    candidates = [ctx.client, pooled]
    if getattr(home, "_current_tab_id", None) == ctx.tab_id and _client_endpoint(home) == endpoint:
        candidates.append(home)
    unique = []
    for client in candidates:
        if client is not None and all(client is not seen for seen in unique):
            unique.append(client)
    return unique


async def _transact(move: Handover) -> tuple[bool, str]:
    proof, why = await prove_candidate(move)
    if proof is None:
        _log(move, f"handover rejected before commit ({why}); original tab retained; use in-place New Chat", "warn")
        return False, why
    move.new, move.old_owner = proof.target, proof.owner
    close_candidate = True
    try:
        if not await _connect_all(move.clients, move.new.ws_url):
            close_candidate = await _restore_clients(move)
            return False, "worker clients could not attach to the verified candidate"
        if not _commit_worker(move):
            close_candidate = await _restore_clients(move)
            return False, "worker pool changed before the verified candidate could be committed"
        close_candidate = False
        await _close_old(move)
        return True, f"new chat ready in the new tab {move.new.id[:12]}"
    finally:
        await dispose_proof(proof, close_candidate)


async def _connect_all(clients: list, ws_url: str) -> bool:
    result = True
    for client in clients:
        try:
            result = bool(await client.connect(ws_url)) and result
        except Exception:
            result = False
    return result


async def _restore_clients(move: Handover) -> bool:
    restored = await _connect_all(move.clients, move.old_ws)
    if not restored:
        _log(move, "client rollback to original tab was incomplete; candidate left open", "error")
    return restored


def _commit_worker(move: Handover) -> bool:
    ctx, new = move.ctx, move.new
    try:
        moved = retarget_page(ctx.pool, move.old_id, new)
    except Exception as exc:
        moved = ctx.pool.get_page(new.id) is not None
        if moved:
            ctx.tab_id = new.id
            _log(move, f"pool retarget completed with a metadata error: {exc}", "error")
            return True
        return False
    if not moved:
        return False
    ctx.tab_id = new.id
    try:
        _finish_commit(move)
    except Exception as exc:
        _log(move, f"worker moved; post-commit metadata update failed: {exc}", "error")
    return True


def _finish_commit(move: Handover) -> None:
    ctx, new = move.ctx, move.new
    page = ctx.pool.get_page(new.id)
    if page is not None:
        page.owner = move.old_owner
    ctx.pool._alias.remember(new.id, move.old_owner)
    for row in ctx.bridge.state.urls:
        if row.tab_id == move.old_id:
            row.tab_id, row.url = new.id, new.url or move.url
    mark_receivers(ctx.bridge.state.urls, ctx.pool)
    for name in ("_save_arena", "_persist_cooldowns", "_emit_pool_status"):
        try:
            getattr(ctx.bridge, name, lambda: None)()
        except Exception:
            pass
    _log(move, f"worker committed to {new.id[:12]} at {move.endpoint[0]}:{move.endpoint[1]}; "
                f"owner={move.old_owner}", "info")

async def _close_old(move: Handover) -> bool:
    for _ in range(2):
        try:
            await asyncio.to_thread(close_tab_sync, *move.endpoint, move.old_id)
            deadline = time.monotonic() + GONE_WAIT_SEC
            while time.monotonic() < deadline:
                tabs, err, _ = await asyncio.to_thread(fetch_tabs_sync, *move.endpoint)
                if not err and all(tab.id != move.old_id for tab in tabs):
                    _log(move, f"old tab {move.old_id[:12]} closed and verified at "
                                f"{move.endpoint[0]}:{move.endpoint[1]}", "success")
                    return True
                await asyncio.sleep(GONE_POLL_SEC)
        except Exception as exc:
            _log(move, f"old-tab close verification error: {exc}", "error")
    _log(move, f"old tab {move.old_id[:12]} remains open after move; close verification failed", "error")
    return False


async def _hold_reconciler(bridge) -> bool:
    deadline = time.monotonic() + RECONCILE_WAIT_SEC
    while getattr(bridge, "_auto_scan_running", False):
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.05)
    bridge._auto_scan_running = True
    return True


def _log(move: Handover, message: str, level: str) -> None:
    try:
        move.ctx.bridge._log(f"🗂 {move.label}: {message}", level)
    except Exception:
        pass
