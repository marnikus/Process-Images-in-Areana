"""Chrome job output — VALIDATE and SAVE (split from single_job_runner, 2026-09-26).

* VALIDATE: the extension from the decoded bytes (PIL), else the src suffix;
  under 100 bytes is never an image.
* SAVE: `image_output.save_beside` — the same `_AI` naming and atomic write as
  the Firefox lane, retrying a transient sharing violation — then
  `confirm.confirm_saved` proves every byte is on disk. A failure keeps its
  reason: logged (`❌ Save failed: …`) and carried in the job error
  (it used to be swallowed into a bare "Save failed").

docs/archive/2026-09-26-chrome-job-save-and-confirmations/design.md D-5.
"""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Any, Optional

from app.services.job_flow.image_output import output_spec, save_beside
from app.services.job_flow.confirm import confirm_saved
from app.services.job_flow.ctx import JobCtx, emit_action, report

log = logging.getLogger("arena")


async def save_image(ctx: JobCtx, file_bytes: bytes) -> Optional[Path]:
    """Save atomically (validated ext or .png); None + `ctx.save_error` on failure."""
    ctx.save_error = ""
    try:
        spec = output_spec(ctx.bridge.state.settings, getattr(ctx, "ext", None) or ".png")
        out_path = save_beside(Path(ctx.img.absolute_path), file_bytes, spec)
    except Exception as e:
        ctx.save_error = str(e)
        log.warning(f"save {e}")
        report(ctx, f"❌ Save failed: {e}", "error")
        return None
    _emit_saved_rect(ctx, out_path.name)
    return out_path


def _emit_saved_rect(ctx: JobCtx, name: str):
    """Saved-file confirmation rect (best effort, UI only)."""
    try:
        dur = ctx.bridge.config.get_state("highlight_duration", 3)
        payload = {"x": 100, "y": 100, "width": 200, "height": 200,
                   "duration": dur, "label": f"Saved {name}"}
        ctx.bridge.highlight_rect.emit(json.dumps(payload))
    except Exception:
        pass


def _pil_format(data: bytes) -> Optional[str]:
    """Lowercase PIL format when bytes decode to a sized image."""
    try:
        from PIL import Image
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
    emit_action(ctx, block, "success", f"Valid {ctx.ext} {len(ctx.file_bytes)} bytes")


async def _handle_save(ctx: JobCtx, block: Any):
    """Handle save: write, prove it on disk, record the path."""
    if not ctx.file_bytes:
        raise RuntimeError("No bytes to save")
    out = await save_image(ctx, ctx.file_bytes)
    if not out:
        raise RuntimeError("Save failed" + (f": {ctx.save_error}" if ctx.save_error else ""))
    confirm_saved(ctx, out, len(ctx.file_bytes))
    ctx.img.output_path = str(out)
    emit_action(ctx, block, "success", f"Saved {out.name}")
