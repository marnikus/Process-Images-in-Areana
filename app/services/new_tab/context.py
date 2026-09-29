# ideal-size: 90 lines reason=context handling owns browserContextId resolution that always changes together
"""Browser context handling — same-profile verification for new tab."""

from __future__ import annotations

from typing import Any, Optional

from app.browser.cdp.tabs import TabInfo

from .matching import _pick_client_for_context


async def _verify_context_same(move: Any, client: Any, new_tab: TabInfo) -> tuple[bool, str]:
    """Check new tab context matches old (same Chrome profile)."""
    try:
        from app.browser.cdp.tabs import _context_of
        new_ctx = await _context_of(client, new_tab.id)
        old = move.old_context or ""
        new_s = str(new_ctx) if new_ctx is not None else ""
        if old and new_s and old != new_s:
            return False, f"context mismatch old={old} new={new_s} — wrong profile"
    except Exception:
        pass
    return True, ""


async def _context_from_targets(client: Any, old_id: str) -> str:
    """BrowserContextId from Target.getTargets for old_id."""
    try:
        resp = await client.send("Target.getTargets")
        infos = resp.get("result", {}).get("targetInfos", []) if isinstance(resp, dict) else []
        for info in infos:
            if info.get("targetId") == old_id:
                return str(info.get("browserContextId") or "")
    except Exception:
        pass
    return ""


async def _get_old_context_id(move: Any) -> str:
    """BrowserContextId of old tab ('' for default)."""
    try:
        from app.browser.cdp.tabs import _context_of
        for cli in move.clients:
            if cli is None:
                continue
            ctx_id = await _context_of(cli, move.old_id)
            if ctx_id is not None:
                return str(ctx_id)
            ctx_id = await _context_from_targets(cli, move.old_id)
            if ctx_id:
                return ctx_id
    except Exception:
        pass
    return ""


async def _get_new_context_id(move: Any) -> str:
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


async def _try_open_same_context(move: Any) -> tuple[Optional[TabInfo], str]:
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
        new_tab, err = await open_tab_in_same_context(client, *move.endpoint,
                                                       move.url, move.old_id)
        if new_tab is None:
            return None, err
        ok, why = await _verify_context_same(move, client, new_tab)
        if not ok:
            return None, why
        return new_tab, ""
    except Exception as e:
        return None, str(e)
