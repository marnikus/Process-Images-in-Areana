from __future__ import annotations
from typing import Any, Optional, Tuple
from .context import JobCtx, log
from .emit import _emit_action, _mark_waiting, _mark_busy
from .state import _is_cancelled

async def _verify_download(ctx: JobCtx, src: str):
    """Verify downloadable."""
    await asyncio.sleep(3)
    try:
        s, f, c = await ctx.ctrl.download_image(src)
        if s and f and len(f) > 100:
            await _hide_overlay(ctx)
            _mark_busy(ctx)
            return src, f, c
    except Exception:
        pass
    await _hide_overlay(ctx)
    _mark_busy(ctx)
    return src, None, "not downloadable"

async def _hide_and_result(ctx: JobCtx, src, data):
    """Hide overlay and return result."""
    await _hide_overlay(ctx)
    _mark_busy(ctx)
    if src:
        return src, None, "not downloadable"
    err = data.get("error", "timeout") if isinstance(data, dict) else "timeout"
    return None, None, str(err)

async def _hide_overlay(ctx: JobCtx):
    """Hide overlay."""
    try:
        await ctx.ctrl.hide_watcher_overlay()
    except Exception:
        pass

async def download_image(ctx: JobCtx, src: str) -> tuple[bool, bytes, str]:
    """Download."""
    try:
        return await ctx.ctrl.download_image(src)
    except Exception as e:
        return False, b"", str(e)

async def _handle_download(ctx: JobCtx, block: Any):
    """Handle download."""
    await check_security(ctx)  # F4: catch a captcha before pulling bytes
    if ctx.file_bytes and len(ctx.file_bytes) > 100:
        _emit_action(ctx, block, "success", f"Already {len(ctx.file_bytes)}")
        return
    if not ctx.new_src:
        raise RuntimeError("No new_src")
    await asyncio.sleep(3)
    s, f, c = await download_image(ctx, ctx.new_src)
    if not s or len(f) < 100:
        raise RuntimeError(f"Download failed: {c}")
    ctx.file_bytes = f
    ctx.ctype = c
    _emit_action(ctx, block, "success", f"Downloaded {len(f)}")

