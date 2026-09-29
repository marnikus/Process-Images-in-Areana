from __future__ import annotations
import asyncio
from typing import Any, Dict, Optional, Tuple
from .context import JobCtx, log
from .emit import _emit_action, _mark_waiting, _mark_busy, _report_recovery
from .state import _is_cancelled, _tab_aborted
from app.services.await_processing import handle_await_processing
from app.core.pause_clock import PauseClock

async def _poll_generation(ctx: JobCtx, timeout_ms: int):
    """Poll for new output; (status, data, src) with abort marking."""
    status, data = await ctx.ctrl.wait_for_new_output(
        ctx.baseline, timeout_ms=timeout_ms, correlation_id=ctx.corr_id,
        cancel_check=lambda: _is_cancelled(ctx),
    )
    if isinstance(data, dict) and data.get("cancelled") and _tab_aborted(ctx):
        data["error"] = "Aborted by operator"
    src = data.get("new_src") if isinstance(data, dict) else None
    return status, data, src

async def wait_for_output(ctx: JobCtx, timeout_ms: int) -> tuple[Optional[str], Optional[bytes], str]:
    """Wait output."""
    try:
        await _show_gen_overlay(ctx, timeout_ms)
        _arm_revival(ctx)  # bounded resubmit if the blocked generation died
        if captcha_in_scope(ctx.bridge):
            ctx.ctrl.security_settler = lambda: _settle_and_note(ctx)  # captcha inside the wait
            ctx.ctrl.pause_clock = PauseClock(pause_cap_seconds(ctx.bridge))  # S3: capped pause
        status, data, src = await _poll_generation(ctx, timeout_ms)
        if status == "completed" and src:
            return await _verify_download(ctx, src)
        return await _hide_and_result(ctx, src, data)
    except Exception as e:
        await _hide_overlay(ctx)
        return None, None, str(e)
    finally:
        _drop_wait_hooks(ctx)
        _clear_revival(ctx)

def _drop_wait_hooks(ctx: JobCtx) -> None:
    """One wait, one settler, one clock: both leave with the wait."""
    for name in ("security_settler", "pause_clock"):
        try:
            delattr(ctx.ctrl, name)
        except Exception:
            pass

async def _settle_and_note(ctx: JobCtx):
    """Settle a mid-wait dialog, then stamp it for generation revival."""
    from app.services.captcha.recovery import note_settle
    settled = await check_security(ctx)
    if settled:
        note_settle(ctx.ctrl)
    return settled

def _arm_revival(ctx: JobCtx):
    """Arm post-captcha revival for this generation wait (services-owned)."""
    from app.services.captcha.recovery import arm_resume
    try:
        policy = arm_resume(ctx.ctrl, ctx.final_prompt, cancelled=lambda: _is_cancelled(ctx),
                            report=lambda m, l="info": _report_recovery(ctx, m, l))
        img = getattr(ctx, "img", None)
        path = getattr(img, "absolute_path", None) if img is not None else None
        if path:
            policy.image_path = str(path)
    except Exception:
        pass

def _clear_revival(ctx: JobCtx):
    """Disarm revival at wait end; never raises."""
    from app.services.captcha.recovery import clear_resume
    try:
        clear_resume(ctx.ctrl)
    except Exception:
        pass

async def _show_gen_overlay(ctx: JobCtx, timeout_ms: int):
    """Show generation overlay."""
    try:
        gen_to = int(ctx.bridge.config.get_state("watcher_generation_timeout_sec", 600))
        eff = max(gen_to, int(timeout_ms / 1000)) if timeout_ms else 600
        await ctx.ctrl.show_watcher_overlay("wait for finish generation", kind="generation", timeout_sec=eff)
        _mark_waiting(ctx, "generation")
    except Exception:
        pass

async def _handle_wait(ctx: JobCtx, block: Any):
    """WAIT_OUTPUT: announce, then wait for the NEW output image (legacy loop).

    B12: AWAIT_PROCESSING_IMAGE no longer shares this handler — the new-output
    wait can only end by timeout on an idle page (services/await_processing)."""
    timeout = getattr(block, "timeout_ms", 0) or ctx.bridge.state.settings.timeouts.get("generation", 180) * 1000
    _emit_action(ctx, block, "running", f"Waiting for generation — timeout {timeout}ms")
    src, fbytes, err = await wait_for_output(ctx, timeout)
    if src:
        ctx.new_src = src
    if fbytes:
        ctx.file_bytes = fbytes
        ctx.ctype = "image"
    if not ctx.new_src:
        raise RuntimeError(f"Wait failed: {err}")
    _emit_action(ctx, block, "success", f"Output {ctx.new_src[:60]}")

