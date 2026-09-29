from __future__ import annotations
from pathlib import Path
from typing import Any, Optional
from .context import JobCtx, log
from .emit import _emit_action, _emit_saved_rect
from app.core.naming import OutputSpec, atomic_write_bytes, get_output_path

async def save_image(ctx: JobCtx, file_bytes: bytes) -> Optional[Path]:
    """Save atomically (validated ext or .png)."""
    try:
        settings = ctx.bridge.state.settings
        suffix = settings.output.get("suffix", "_AI")
        overwrite = settings.output.get("overwrite", False)
        preserve = settings.output.get("preserve_format", True)
        tpl = settings.output.get("unique_suffix_template", "{base}_AI_{n}{ext}")
        ext = getattr(ctx, "ext", None) or ".png"
        src_path = Path(ctx.img.absolute_path)
        spec = OutputSpec(suffix=suffix, preserve_format=preserve, overwrite=overwrite,
                          downloaded_ext=ext, unique_template=tpl)
        out_path = get_output_path(src_path, spec)
        atomic_write_bytes(src_path.parent, out_path, file_bytes)
        _emit_saved_rect(ctx, out_path.name)
        return out_path
    except Exception as e:
        log.warning(f"save {e}")
        return None

async def _handle_save(ctx: JobCtx, block: Any):
    """Handle save."""
    if not ctx.file_bytes:
        raise RuntimeError("No bytes to save")
    out = await save_image(ctx, ctx.file_bytes)
    if not out:
        raise RuntimeError("Save failed")
    ctx.img.output_path = str(out)
    _emit_action(ctx, block, "success", f"Saved {out.name}")

