from __future__ import annotations
from typing import Any
from .context import JobCtx, log
from .emit import _emit_action, _mark_waiting, _mark_busy
from .state import _tab_aborted

async def _attach_open_dialog(ctx: JobCtx, block: Any):
    """Human-like file-dialog click before attach (best effort)."""
    if not (getattr(block, "click_selector", "") and getattr(block, "click_enabled", False)):
        return
    try:
        req = _click_req(block, block.click_selector, "")
        req = replace(req, label=f"{_display(block)} open dialog")
        await _try_click(ctx, req)
        await asyncio.sleep(0.5)
    except Exception as e:
        _report_recovery(ctx, f"Open dialog click skipped: {e}", "warn")

async def _attach_emit(ctx: JobCtx, block: Any, reason: str):
    """Attach success, with confirmation rect when highlight works."""
    try:
        sel = getattr(block, "selector", "") or get_selector("file_input").presence()
        color = getattr(block, "color", "") or "#FF0000"
        ms = getattr(block, "highlight_ms", 0) or 2000
        rect = await ctx.ctrl.highlight_selector(sel, color=color, duration_ms=ms, caption="Attached ok")
        rd = rect.get("rect", rect) if isinstance(rect, dict) else None
        ctx.bridge._emit_job_action_status(JobAction(ctx.job_id, block, "success", reason, rd))
    except Exception:
        _emit_action(ctx, block, "success", reason)

async def _handle_attach(ctx: JobCtx, block: Any):
    """Handle attach."""
    await _attach_open_dialog(ctx, block)
    ok, reason = await attach_image(ctx)
    if not ok:
        raise RuntimeError(f"Attach failed: {reason}")
    _report_recovery(ctx, f"Attachment verified: {reason}", "success")
    await _attach_emit(ctx, block, reason)

async def attach_image(ctx: JobCtx) -> tuple[bool, str]:
    """Attach image."""
    try:
        return await ctx.ctrl.attach_image(ctx.img.absolute_path)
    except Exception as e:
        return False, str(e)

def _marker_selector(block: Any) -> str:
    """Default selector per HIGHLIGHT_* marker (legacy parity)."""
    if getattr(block, "selector", ""):
        return block.selector
    btype = getattr(block, "block_id", "")
    if "ATTACH" in btype:
        return get_selector("file_input").presence()
    if "PROMPT" in btype:
        return textarea_primary()
    return send_presence_selector()

async def _handle_marker_highlight(ctx: JobCtx, block: Any):
    """Marker highlight: visual only, never fails the job."""
    try:
        sel = _marker_selector(block)
        ms = getattr(block, "highlight_ms", 0) or getattr(block, "highlight_duration_ms", 0) or 2000
        rect = await ctx.ctrl.highlight_selector(sel, color=getattr(block, "color", "") or "#FF0000", duration_ms=ms, caption=_display(block))
        rd = rect.get("rect", rect) if isinstance(rect, dict) else None
        ctx.bridge._emit_job_action_status(JobAction(ctx.job_id, block, "success", f"Highlighted {sel}", rd))
    except Exception as e:
        _emit_action(ctx, block, "success", f"Highlight skipped: {e}")

async def _handle_verify_attachment(ctx: JobCtx, block: Any):
    """Handle attachment-preview check (find probe, legacy parity)."""
    sel = getattr(block, "selector", "") or attachment_preview_selector()
    spec = FindProbeSpec(highlight=getattr(block, "highlight_enabled", True), highlight_ms=getattr(block, "highlight_ms", 0) or 1500, color=getattr(block, "color", "") or "#FF0000")
    try:
        raw = await ctx.client.evaluate(build_find_probe(sel, spec))
        res = json.loads(raw) if raw else {}
    except Exception as e:
        raise RuntimeError(f"Verify attachment failed: {e}")
    if not res.get("found"):
        raise RuntimeError(f"Verify attachment failed: preview not found {sel}")
    ctx.bridge._emit_job_action_status(JobAction(ctx.job_id, block, "success", f"Attachment preview found {sel}", res.get("rect")))

def attachment_preview_selector() -> str:
    """Preview-image probe selector (RULE 21: container from site_adapter)."""
    return get_selector("attachment_preview_container").primary + " img"

