# ideal-size: 60 lines reason=storage copy via JS probes, best-effort helpers that always change together
"""Storage copy — localStorage + sessionStorage via JS probes."""

from __future__ import annotations

from typing import Any

from .matching import _pick_client_for_context


async def _get_storage_from_move(move: Any) -> dict:
    """Local+sessionStorage from old tab (best effort)."""
    try:
        client = _pick_client_for_context(move)
        if client is None:
            return {}
        js = """(() => { try { const g=(s)=>{ const o={}; for(let i=0;i<s.length;i++){ const k=s.key(i); o[k]=s.getItem(k); } return o; }; return JSON.stringify({local:g(localStorage), session:g(sessionStorage)}); } catch(e){ return "{}"; } })()"""
        resp = await client.send("Runtime.evaluate",
                                 {"expression": js, "returnByValue": True})
        val = ""
        if isinstance(resp, dict):
            r = resp.get("result", {}).get("result", {}) if "result" in resp else resp
            val = r.get("value", "") if isinstance(r, dict) else ""
        if not val:
            return {}
        import json as _json
        data = _json.loads(val) if isinstance(val, str) else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


async def _set_storage_to_move(move: Any, data: dict) -> None:
    """Set local+sessionStorage into new tab (best effort)."""
    if not data:
        return
    try:
        client = _pick_client_for_context(move)
        if client is None:
            client = getattr(move.ctx, "client", None)
        if client is None:
            return
        import json as _json

        def _limit(d):
            return dict(list(d.items())[:50]) if isinstance(d, dict) else {}

        payload = {"local": _limit(data.get("local", {})),
                   "session": _limit(data.get("session", {}))}
        js_data = _json.dumps(payload)
        js = f"""((d) => {{ try {{ for(const [k,v] of Object.entries(d.local||{{}})){{ localStorage.setItem(k,v); }} for(const [k,v] of Object.entries(d.session||{{}})){{ sessionStorage.setItem(k,v); }} return true; }} catch(e){{ return false; }} }})({js_data})"""
        await client.send("Runtime.evaluate", {"expression": js})
    except Exception:
        pass
