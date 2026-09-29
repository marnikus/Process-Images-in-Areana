# ideal-size: 110 lines reason=cookie copy owns get/set + reload that always changes together
"""Cookie handling — get cookies from old tab, set into new, reload."""

from __future__ import annotations

import asyncio
from typing import Any, List, Optional


def _cookie_base(ck: dict) -> Optional[dict]:
    """Base CDP cookie params or None."""
    try:
        name = ck.get("name", "")
        if not name:
            return None
        return {"name": name, "value": ck.get("value", ""),
                "domain": ck.get("domain", ""), "path": ck.get("path", "/")}
    except Exception:
        return None


def _cookie_params(ck: dict) -> Optional[dict]:
    """CDP Network.setCookie params from cookie dict, or None when unusable."""
    params = _cookie_base(ck)
    if params is None:
        return None
    try:
        if ck.get("secure"):
            params["secure"] = True
        if ck.get("httpOnly"):
            params["httpOnly"] = True
        ss = ck.get("sameSite")
        if ss in ("Strict", "Lax", "None"):
            params["sameSite"] = ss
        return params
    except Exception:
        return None


async def _set_one_cookie(client: Any, ck: dict) -> None:
    """Set one cookie (quiet on failure)."""
    try:
        params = _cookie_params(ck)
        if params is None:
            return
        await client.send("Network.setCookie", params)
    except Exception:
        pass


async def _get_cookies_from_move(move: Any) -> list:
    """Get cookies from old tab's client (best effort, keeps account)."""
    try:
        from .storage import _pick_client_for_context
        client = _pick_client_for_context(move)
        if client is None:
            return []
        try:
            await client.send("Network.enable")
        except Exception:
            pass
        resp = await client.send("Network.getAllCookies")
        cookies = []
        if isinstance(resp, dict):
            cookies = resp.get("result", {}).get("cookies", []) or resp.get("cookies", []) or []
        return cookies if isinstance(cookies, list) else []
    except Exception:
        return []


async def _set_cookies_to_move(move: Any, cookies: list) -> None:
    """Set cookies into new tab (best effort)."""
    if not cookies:
        return
    from .storage import _pick_client_for_context
    client = _pick_client_for_context(move)
    if client is None:
        client = getattr(move.ctx, "client", None)
    if client is None:
        return
    try:
        await client.send("Network.enable")
    except Exception:
        pass
    for ck in cookies[:50]:
        await _set_one_cookie(client, ck)


async def _reload_after_cookies(move: Any) -> None:
    """Reload new tab after session restore (best effort)."""
    try:
        from .storage import _pick_client_for_context
        client = _pick_client_for_context(move)
        if client is None:
            return
        await client.send("Page.reload")
        await asyncio.sleep(0.8)
    except Exception:
        pass
