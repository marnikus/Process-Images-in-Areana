from __future__ import annotations
from typing import Any, List, Optional
from .context import JobCtx, log
from .emit import _emit_action, _mark_waiting, _mark_busy, _display
from app.browser.visual_click import ClickRequest

def _click_req(block: Any, sel: str, text: str) -> ClickRequest:
    """Visual-runner request from block fields (RULE 1)."""
    return ClickRequest(
        selector=sel,
        label_selector=getattr(block, "label_selector", "") or "",
        match_text=text,
        match_mode=getattr(block, "match_mode", "") or "contains",
        click_enabled=getattr(block, "click_enabled", True),
        click_selector=getattr(block, "click_selector", "") or "",
        highlight_enabled=getattr(block, "highlight_enabled", True),
        confirm_pause_ms=getattr(block, "confirm_pause_ms", 0) or 700,
        highlight_ms=getattr(block, "highlight_ms", 0) or 2000,
        label=_display(block),
    )

def _fallback_list(block: Any) -> List[str]:
    """Comma-separated fallback selectors, blanks dropped."""
    raw = getattr(block, "fallback_selector", "") or ""
    return [s.strip() for s in raw.split(",") if s.strip()]

async def _try_click(ctx: JobCtx, req: ClickRequest) -> str:
    """One visual attempt; never raises (returns 'fail' instead)."""
    try:
        return await find_and_click(ctx.client, req, engine=ctx.bridge)
    except Exception:
        return "fail"

async def _submit_visual(ctx: JobCtx, block: Any) -> str:
    """Primary submit click through the visual runner."""
    sel = getattr(block, "selector", "") or send_click_primary()
    return await _try_click(ctx, _click_req(block, sel, getattr(block, "match_text", "") or ""))

async def _submit_fallbacks(ctx: JobCtx, block: Any) -> Optional[str]:
    """Fallback selectors in order; first 'ok' wins."""
    for fb_sel in _fallback_list(block):
        _report_recovery(ctx, f"↩ Submit fallback trying {fb_sel[:40]}", "warn")
        req = _click_req(block, fb_sel, getattr(block, "fallback_text", "") or "")
        req = replace(req, label=f"Submit fallback {fb_sel[:40]}")
        if await _try_click(ctx, req) == "ok":
            return fb_sel
    return None

async def submit_job(ctx: JobCtx, block: Any) -> tuple[bool, str]:
    """Submit: visual first, fallbacks, controller last resort."""
    if await _submit_visual(ctx, block) == "ok":
        sel = getattr(block, "selector", "") or "submit"
        return True, f"Clicked {sel}"
    won = await _submit_fallbacks(ctx, block)
    if won:
        return True, f"Submit via fallback {won}"
    try:
        ok, reason = await ctx.ctrl.submit()
        if ok:
            return True, f"Submit via controller {reason}"
        return False, f"Submit failed: {reason}"
    except Exception as e:
        return False, f"Submit failed: {e}"

async def _handle_submit(ctx: JobCtx, block: Any):
    """Handle submit (settle React, then visual-first submit)."""
    await asyncio.sleep(0.8)  # let React enable the button after prompt insert
    ok, reason = await submit_job(ctx, block)
    if not ok:
        raise RuntimeError(reason)
    _emit_action(ctx, block, "success", reason)
    await check_security(ctx)  # F4: captcha often pops at submit time

