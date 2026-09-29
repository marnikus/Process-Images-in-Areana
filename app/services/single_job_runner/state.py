from __future__ import annotations
from typing import Any, Dict, List
from .context import JobCtx, _OUTPUT_BLOCKS

def _init_old_srcs(ctx: JobCtx):
    try:
        ctx.old_srcs = list(ctx.baseline.get("output_srcs", []) or [])
    except Exception:
        ctx.old_srcs = []

async def _maybe_delay(block: Any):
    d = getattr(block, "pre_delay_ms", 0)
    if d:
        await asyncio.sleep(d / 1000.0)

def _tab_aborted(ctx: JobCtx) -> bool:
    """Operator stop requested for this tab's job."""
    try:
        from .cooldown_service import is_tab_aborted
        return is_tab_aborted(getattr(ctx.bridge, "_page_pool", None), ctx.tab_id)
    except Exception:
        return False

def _is_cancelled(ctx: JobCtx) -> bool:
    return bool(getattr(ctx.bridge, "_cancel_requested", False)) or _tab_aborted(ctx)

def _output_secured(ctx: JobCtx) -> bool:
    """The generated image is already in memory (DOWNLOAD/WAIT delivered bytes)."""
    return bool(ctx.file_bytes and len(ctx.file_bytes) > 100)

