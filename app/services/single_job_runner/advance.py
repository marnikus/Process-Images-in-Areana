from __future__ import annotations
from typing import Any
from .context import JobCtx
from app.core.enums import ImageStatus

async def _handle_advance(ctx: JobCtx, block: Any):
    """Handle advance."""
    ctx.img.status = ImageStatus.COMPLETED.value
    _emit_action(ctx, block, "success", "Completed")

