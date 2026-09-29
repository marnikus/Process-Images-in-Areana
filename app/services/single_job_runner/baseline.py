from __future__ import annotations
import logging
from typing import Any, Dict
from .context import JobCtx, log
from .emit import _emit_action, _mark_waiting, _mark_busy

async def capture_baseline(ctrl) -> Dict[str, Any]:
    """Capture baseline."""
    try:
        return await ctrl.capture_baseline()
    except Exception as e:
        log.warning(f"baseline {e}")
        return {"output_count": 0, "output_srcs": []}

async def capture_text_baseline(ctrl) -> Dict[str, Any]:
    """Capture text baseline."""
    try:
        return await ctrl.capture_text_baseline()
    except Exception as e:
        log.warning(f"text baseline {e}")
        return {"text_count": 0, "text_outputs": []}

async def _handle_baseline(ctx: JobCtx, block: Any):
    """Handle baseline."""
    ctx.baseline = await capture_baseline(ctx.ctrl)
    try:
        ctx.old_srcs = list(ctx.baseline.get("output_srcs", []) or [])
    except Exception:
        ctx.old_srcs = []
    _emit_action(ctx, block, "success", f"Baseline {ctx.baseline.get('output_count')}")

async def _handle_text_baseline(ctx: JobCtx, block: Any):
    """Handle text baseline capture."""
    ctx.text_baseline = await capture_text_baseline(ctx.ctrl)
    count = ctx.text_baseline.get("text_count", 0)
    _emit_action(ctx, block, "success", f"Text baseline {count}")

