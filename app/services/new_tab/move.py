# ideal-size: 100 lines reason=move planning owns _Move dataclass and endpoint resolution that always changes together
"""Move planning — _Move dataclass, endpoint resolution, client collection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from app.browser.cdp.tabs import TabInfo
from app.browser.page_pool import tab_label_of

from .matching import (
    _count_profile_tabs,
    _count_profile_tabs_by_owner,
    _endpoint_from_client,
    _get_pattern,
)


@dataclass
class _Move:
    """One handover: finish context, where it goes, and what it came from."""
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
    profile_count_owner: int = 0


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


def _clients_on(ctx: Any) -> list:
    """Every distinct client object on the old tab: job's, pool's, home one."""
    pooled, _ctrl = ctx.pool.get_clients(ctx.tab_id)
    home = getattr(ctx.bridge, "cdp", None)
    found = [ctx.client, pooled,
             home if getattr(home, "_current_tab_id", None) == ctx.tab_id else None]
    unique: list = []
    for client in found:
        if client is not None and all(client is not seen for seen in unique):
            unique.append(client)
    return unique


def _plan(ctx: Any, url: str, timeout_sec: float) -> Optional[_Move]:
    """What moves: pool page of job's tab, endpoint and every client on it."""
    pool = getattr(ctx, "pool", None)
    page = pool.get_page(ctx.tab_id) if pool is not None else None
    if page is None:
        return None
    pooled, _ = pool.get_clients(ctx.tab_id)
    old_owner = str(getattr(page, "owner", "") or "")
    endpoint = _resolve_endpoint(ctx, pooled)
    pattern = _get_pattern(ctx.bridge)
    count = _count_profile_tabs(pool, endpoint, pattern)
    count_owner = _count_profile_tabs_by_owner(pool, endpoint, pattern, old_owner)
    move = _Move(ctx, url, timeout_sec, ctx.tab_id, page.ws_url, page.url,
                 tab_label_of(pool, ctx.tab_id))
    move.old_owner = old_owner
    move.endpoint = endpoint
    move.pattern = pattern
    move.profile_count = count
    move.profile_count_owner = count_owner
    move.clients = _clients_on(ctx)
    return move
