from __future__ import annotations
from typing import Any, List, Optional
from .context import JobCtx, log
from .emit import _emit_action, _mark_waiting, _mark_busy, _display
from app.browser.probe_requests import HighlightSpec
from app.browser.visual_click import ClickRequest
from app.browser.dom_highlight import build_find_probe, build_highlight_probe
from app.browser.probe_selectors import send_click_primary
from app.browser.site_adapter import get_selector

async def _custom_ok_emit(ctx: JobCtx, block: Any, sel: str):
    """Custom-find success, with confirmation rect when highlight works."""
    try:
        ms = getattr(block, "highlight_ms", 0) or 2000
        rect = await ctx.ctrl.highlight_selector(sel, color=getattr(block, "color", "") or "#FF0000", duration_ms=ms, caption=_display(block))
        rd = rect.get("rect", rect) if isinstance(rect, dict) else None
        ctx.bridge._emit_job_action_status(JobAction(ctx.job_id, block, "success", f"FIND+CLICK ok {sel}", rd))
    except Exception:
        _emit_action(ctx, block, "success", f"FIND+CLICK ok {sel}")

async def _custom_fallbacks(ctx: JobCtx, block: Any) -> Optional[str]:
    """Fallback selectors in order; first 'ok' wins."""
    for fb_sel in _fallback_list(block):
        _report_recovery(ctx, f"↩ Trying fallback {fb_sel[:40]}", "warn")
        req = _click_req(block, fb_sel, getattr(block, "fallback_text", "") or "")
        req = replace(req, click_enabled=True,
                      label=f"{_display(block)} fallback {fb_sel[:30]}")
        if await _try_click(ctx, req) == "ok":
            return fb_sel
    return None

async def _handle_custom(ctx: JobCtx, block: Any):
    """Handle custom find (primary + fallbacks, legacy parity)."""
    sel = getattr(block, "selector", "") or "button"
    req = _click_req(block, sel, getattr(block, "match_text", "") or "")
    if await _try_click(ctx, req) == "ok":
        await _custom_ok_emit(ctx, block, sel)
        return
    won = await _custom_fallbacks(ctx, block)
    if won:
        _emit_action(ctx, block, "success", f"Fallback ok {won}")
        return
    tried = _fallback_list(block)
    if tried:
        raise RuntimeError(f"Find & Click failed for {sel} and fallbacks {tried}")
    raise RuntimeError(f"Find & Click failed for {sel}")

def _str(block: Any, name: str, default: str) -> str:
    """Block text field with default for missing-or-empty."""
    val = getattr(block, name, "")
    return val if val else default

def _highlight_spec(block: Any, sel: str) -> HighlightSpec:
    """Probe spec from block fields (pure visual, no click)."""
    return HighlightSpec(
        label_selector=getattr(block, "label_selector", "") or None,
        match_text=getattr(block, "match_text", "") or None,
        match_mode=_str(block, "match_mode", "contains"),
        color=_str(block, "color", "#00c853"),
        caption=_display(block) or sel[:30],
        highlight_ms=getattr(block, "highlight_ms", 0) or 2000,
        clear_first=True,
    )

async def _handle_highlight(ctx: JobCtx, block: Any):
    """Pure visual confirmation (no click, legacy parity)."""
    sel = _str(block, "selector", "div")
    try:
        raw = await ctx.client.evaluate(build_highlight_probe(sel, _highlight_spec(block, sel)))
        res = json.loads(raw) if raw else {}
    except Exception as e:
        raise RuntimeError(f"Highlight failed: {e}")
    if not res.get("found"):
        raise RuntimeError(f"Highlight not found: {sel}")
    _report_recovery(ctx, f"Highlighted {sel}", "success")
    ctx.bridge._emit_job_action_status(JobAction(ctx.job_id, block, "success", f"Highlighted {sel}", res.get("rect")))

async def _handle_pause(ctx: JobCtx, block: Any):
    """Handle pause (duration from extra/timeout, legacy parity)."""
    extra = getattr(block, "extra", {}) or {}
    dur = extra.get("duration_ms") or getattr(block, "timeout_ms", 0) or 1000
    _report_recovery(ctx, f"⏸ Pausing {dur}ms", "info")
    await asyncio.sleep(dur / 1000.0)
    _emit_action(ctx, block, "success", f"Paused {dur}ms")

