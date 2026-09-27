"""The sequential run's tab — which checked pooled tab takes the next image, right now.

Owns the claim (`resolve_and_claim_tab`: prefer a ready tab owned by a checked
row, move the primary CDP there, or say why it stays) and its re-check
(`still_checked`), both against the checkbox set read live (I-33, I-68).
Split from `batch_orchestrator` (RULE 18.2): the pass body asks, this answers.
Imports only cooldown_service / auto_connect / page_pool — never the orchestrator.
"""

from __future__ import annotations

from app.browser.page_pool import tab_label_of
from app.services import auto_connect as ac
from app.services.cooldown_service import resolve_primary_tab


def pool_of(bridge):
    """The shared page pool (None in the single primary-CDP mode)."""
    return getattr(bridge, "_page_pool", None)


def pool_summary(pool) -> str:
    """One-line pool state for run decisions (the supervisor's wait lines reuse it)."""
    try:
        pages = pool.status_snapshot().get("pages", [])
    except Exception:
        return "pool n/a"
    bits = []
    for page in pages:
        bit = f"{(page.get('tab_id') or '?')[:6]}:{page.get('status')}({'c' if page.get('is_connected') else 'd'})"
        bit += f"·j{page.get('jobs_completed', 0)}"
        if page.get("current_image"):
            bit += f"·▶{page.get('current_image')}"
        bits.append(bit)
    return ", ".join(bits) or "pool empty"


def _log_stay_reason(bridge, tab_id: str) -> None:
    """Warn when staying on an unready primary, with pool state."""
    try:
        pool = pool_of(bridge)
        if not (pool and tab_id):
            return
        page = pool.get_page(tab_id)
        if page is None or page.is_free():
            return
        bridge._log(f"⏳ No ready tab — staying on {tab_label_of(pool, tab_id)} ({page.status}) — pool: {pool_summary(pool)}", "warn")
    except Exception:
        pass


def _pool_ws(pool, want: str) -> str:
    """Websocket URL of a pooled page (missing-safe)."""
    page = pool.get_page(want) if pool else None
    return getattr(page, "ws_url", "") or ""


def _claim_no_cdp(bridge, pool, want: str) -> bool:
    """A Firefox primary is claimed in place — there is no socket to move to (D4)."""
    page = pool.get_page(want) if pool else None
    if page is None or getattr(page, "browser", "") != "firefox":
        return False
    bridge._log(f"🦊 Primary {want[:12]} is Firefox — pool dispatch (no CDP move)", "info")
    return True


async def _move_to_tab(bridge, tab_id: str, want: str) -> str:
    """Reconnect to a readier tab; stay on failure."""
    try:
        pool = pool_of(bridge)
        if _claim_no_cdp(bridge, pool, want):
            return want
        ws = _pool_ws(pool, want)
        if ws and bridge.cdp and await bridge.cdp.connect(ws):
            bridge._log(f"🔀 Run moved to ready tab {want[:12]}", "info")
            return want
        bridge._log(f"⚠ Reconnect to ready tab {want[:12]} failed — staying on {(tab_id or '?')[:12]} — pool: {pool_summary(pool)}", "warn")
    except Exception as e:
        bridge._log(f"⚠ Primary move failed ({e}) — pool: {pool_summary(pool_of(bridge))}", "warn")
    return tab_id


async def resolve_and_claim_tab(bridge, tab_id: str, allowed) -> str:
    """Prefer a ready pooled tab owned by a checked row (I-33)."""
    try:
        want = resolve_primary_tab(pool_of(bridge), tab_id, allowed)
    except Exception:
        return tab_id
    if not want:
        return ""
    if want == tab_id:
        _log_stay_reason(bridge, tab_id)
        return tab_id
    return await _move_to_tab(bridge, tab_id, want)


def still_checked(bridge, tab_id: str) -> bool:
    """The claimed tab's row is still checked — the claim's own rule (no pool = no gate, I-68)."""
    return pool_of(bridge) is None or tab_id in ac.live_allowed(bridge)
