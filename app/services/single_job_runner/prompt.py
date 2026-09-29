from __future__ import annotations
from typing import Any
from .context import JobCtx, log
from .emit import _emit_action, _mark_waiting, _mark_busy
from .preset import _resolve_prompt_from_preset, _build_final_from_template

async def insert_prompt(ctx: JobCtx) -> tuple[bool, str]:
    """Insert prompt."""
    try:
        return await ctx.ctrl.insert_prompt(ctx.final_prompt)
    except Exception as e:
        return False, str(e)

async def _handle_prompt(ctx: JobCtx, block: Any):
    """Handle prompt with optional preset loading."""
    preset_tmpl = _resolve_prompt_from_preset(ctx, block)
    if preset_tmpl:
        final = _build_final_from_template(ctx.corr_id, preset_tmpl)
        try:
            ok, reason = await ctx.ctrl.insert_prompt(final)
            if not ok:
                raise RuntimeError(f"Prompt failed: {reason}")
            _emit_action(ctx, block, "success", f"Preset {getattr(block, 'preset_name', '')} {reason}")
            return
        except Exception as e:
            raise RuntimeError(f"Preset prompt failed: {e}")
    ok, reason = await insert_prompt(ctx)
    if not ok:
        raise RuntimeError(f"Prompt failed: {reason}")
    _emit_action(ctx, block, "success", reason)

async def _handle_verify_prompt(ctx: JobCtx, block: Any):
    """Handle prompt check (one retry, legacy parity)."""
    verified, reason = await ctx.ctrl.verify_prompt(ctx.final_prompt)
    if not verified:
        _report_recovery(ctx, f"Prompt mismatch {reason}, retrying", "warn")
        await ctx.ctrl.insert_prompt(ctx.final_prompt)
        verified, reason = await ctx.ctrl.verify_prompt(ctx.final_prompt)
        if not verified:
            raise RuntimeError(f"Prompt verification failed: {reason}")
    _emit_action(ctx, block, "success", f"Verified {reason}")

async def _type_highlight(ctx: JobCtx, block: Any) -> None:
    """Best-effort highlight before typed prompt (never fails)."""
    if not getattr(block, "highlight_enabled", False):
        return
    try:
        sel = getattr(block, "selector", "") or textarea_primary()
        await ctx.ctrl.highlight_selector(sel, color=getattr(block, "color", "") or "#FF0000", duration_ms=getattr(block, "highlight_ms", 0) or 2000, caption=_display(block))
    except Exception:
        pass

async def _handle_type_prompt(ctx: JobCtx, block: Any):
    """Handle typed prompt (highlight, then insert full prompt)."""
    extra = getattr(block, "extra", {}) or {}
    speed = extra.get("typing_speed_ms", 10)
    _report_recovery(ctx, f"⌨ Typing prompt speed {speed}ms", "info")
    await _type_highlight(ctx, block)
    ok, reason = await insert_prompt(ctx)
    if not ok:
        raise RuntimeError(f"Type prompt failed: {reason}")
    _emit_action(ctx, block, "success", reason)

