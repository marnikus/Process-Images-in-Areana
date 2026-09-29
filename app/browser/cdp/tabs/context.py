from __future__ import annotations

from typing import Any, Optional, Tuple

from .fetch import fetch_tabs_sync
from .models import TabInfo


async def _context_of(client: Any, old_id: str) -> Optional[str]:
    """BrowserContextId of old tab, or None for default context."""
    try:
        resp = await client.send("Target.getTargets")
        infos = resp.get("result", {}).get("targetInfos", []) if isinstance(resp, dict) else []
        if not infos:
            infos = resp.get("targetInfos", []) if isinstance(resp, dict) else []
        for info in infos:
            if info.get("targetId") == old_id:
                return info.get("browserContextId")
    except Exception:
        return None
    return None


async def open_tab_in_same_context(client: Any, endpoint: tuple[str, int], url: str, old_id: str) -> Tuple[Optional[TabInfo], str]:
    """Open new tab in same browser context as old_id (profile-correct, keeps Arena account)."""
    host, port = endpoint if isinstance(endpoint, (tuple, list)) else (getattr(endpoint, "host", "127.0.0.1"), getattr(endpoint, "port", 9222))
    ctx_id = await _context_of(client, old_id)
    params = {"url": url}
    if ctx_id:
        params["browserContextId"] = ctx_id
    try:
        resp = await client.send("Target.createTarget", params)
        result = resp.get("result", resp) if isinstance(resp, dict) else {}
        new_id = result.get("targetId", "")
        if not new_id:
            return None, f"createTarget no id {str(resp)[:120]}"
        import asyncio as _asyncio
        tabs, err, _ = await _asyncio.to_thread(fetch_tabs_sync, host, port)
        if err:
            return TabInfo(id=new_id, title="", url=url, ws_url=f"ws://{host}:{port}/devtools/page/{new_id}"), ""
        for tab in tabs:
            if tab.id == new_id:
                return tab, ""
        return TabInfo(id=new_id, title="", url=url, ws_url=f"ws://{host}:{port}/devtools/page/{new_id}"), ""
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
