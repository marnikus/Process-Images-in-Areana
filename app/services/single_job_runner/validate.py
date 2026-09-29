from __future__ import annotations
from typing import Any, Optional
from .context import JobCtx
from .emit import _emit_action

def _pil_format(data: bytes) -> Optional[str]:
    """Lowercase PIL format when bytes decode to a sized image."""
    try:
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(data))
        if im.width and im.height:
            return (im.format or "PNG").lower()
    except Exception:
        return None
    return None

def _src_suffix(src: str) -> str:
    """Extension hint from the source URL (last resort: .png)."""
    for suffix in (".png", ".jpg", ".jpeg", ".webp"):
        if suffix in (src or ""):
            return ".jpg" if suffix == ".jpeg" else suffix
    return ".png"

def _infer_ext(ctx: JobCtx) -> str:
    """Image ext from bytes (PIL) or src suffix; raises when too small."""
    fmt = _pil_format(ctx.file_bytes or b"")
    if fmt:
        return f".{fmt}"
    if len(ctx.file_bytes or b"") < 100:
        raise RuntimeError("Validation failed: unreadable image")
    return _src_suffix(ctx.new_src or "")

async def _handle_validate(ctx: JobCtx, block: Any):
    """Handle validate (sets ctx.ext for SAVE)."""
    if not ctx.file_bytes:
        raise RuntimeError("No bytes")
    ctx.ext = _infer_ext(ctx)
    _emit_action(ctx, block, "success", f"Valid {ctx.ext} {len(ctx.file_bytes)} bytes")

