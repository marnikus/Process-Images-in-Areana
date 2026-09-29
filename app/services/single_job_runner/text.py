from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from .context import JobCtx, log
from .emit import _emit_action, _mark_waiting, _mark_busy
from .state import _is_cancelled

async def _poll_text_generation(ctx: JobCtx, timeout_ms: int):
    """Poll for new text output; (status, data, text)."""
    status, data = await ctx.ctrl.wait_for_new_text_output(
        ctx.text_baseline,
        timeout_ms=timeout_ms,
        correlation_id=ctx.corr_id,
        cancel_check=lambda: _is_cancelled(ctx),
    )
    txt = data.get("new_text") or data.get("full_text") if isinstance(data, dict) else None
    return status, data, txt

async def _show_text_overlay(ctx: JobCtx, timeout_ms: int):
    try:
        gen_to = int(ctx.bridge.config.get_state("watcher_generation_timeout_sec", 600))
        eff = max(gen_to, int(timeout_ms / 1000)) if timeout_ms else 600
        await ctx.ctrl.show_watcher_overlay(
            "wait for text description", kind="generation", timeout_sec=eff
        )
        _mark_waiting(ctx, "text_generation")
    except Exception:
        pass

async def wait_for_text_output(ctx: JobCtx, timeout_ms: int) -> tuple[Optional[str], str]:
    try:
        await _show_text_overlay(ctx, timeout_ms)
        status, data, txt = await _poll_text_generation(ctx, timeout_ms)
        await _hide_overlay(ctx)
        _mark_busy(ctx)
        if status == "completed" and txt:
            return txt, ""
        err = data.get("error", "timeout") if isinstance(data, dict) else "timeout"
        return None, str(err)
    except Exception as e:
        await _hide_overlay(ctx)
        return None, str(e)

async def _handle_wait_text(ctx: JobCtx, block: Any):
    """WAIT_TEXT_OUTPUT: wait for new text description."""
    timeout = getattr(block, "timeout_ms", 0) or ctx.bridge.state.settings.timeouts.get(
        "generation", 180
    ) * 1000
    _emit_action(ctx, block, "running", f"Waiting for text description — timeout {timeout}ms")
    txt, err = await wait_for_text_output(ctx, timeout)
    if not txt:
        raise RuntimeError(f"Wait text failed: {err}")
    ctx.text_output = txt
    preview = txt[:80].replace("\n", " ")
    _emit_action(ctx, block, "success", f"Text output {len(txt)} chars: {preview}")

def _get_overwrite_flag(block: Any) -> bool:
    try:
        if getattr(block, "overwrite", False):
            return True
        extra = getattr(block, "extra", {}) or {}
        return bool(extra.get("overwrite", False))
    except Exception:
        return False

def _build_description_doc(ctx: JobCtx, block: Any) -> dict:
    src_path = Path(ctx.img.absolute_path)
    doc = {
        "description": ctx.text_output or "",
        "source": src_path.name,
        "source_path": str(src_path),
    }
    if getattr(block, "include_prompt", True):
        doc["prompt"] = ctx.final_prompt
    if getattr(block, "include_job_id", True):
        doc["job_id"] = ctx.job_id
        doc["corr_id"] = ctx.corr_id
    return doc

async def _save_description_json_file(ctx: JobCtx, block: Any) -> Optional[Path]:
    """Save text description as JSON beside source."""
    try:
        from app.core.naming import atomic_write_json, get_description_json_path

        src_path = Path(ctx.img.absolute_path)
        out_path = get_description_json_path(src_path, overwrite=_get_overwrite_flag(block))
        doc = _build_description_doc(ctx, block)
        atomic_write_json(src_path.parent, out_path, doc)
        _emit_saved_rect(ctx, out_path.name)
        return out_path
    except Exception as e:
        log.warning(f"save json {e}")
        return None

async def _handle_save_json(ctx: JobCtx, block: Any):
    """Handle SAVE_DESCRIPTION_JSON."""
    if not ctx.text_output:
        raise RuntimeError("No text output to save")
    out = await _save_description_json_file(ctx, block)
    if not out:
        raise RuntimeError("Save JSON failed")
    ctx.img.output_path = str(out)
    _emit_action(ctx, block, "success", f"Saved JSON {out.name} ({len(ctx.text_output)} chars)")

async def _handle_generate_description(ctx: JobCtx, block: Any):
    """Combined: wait text + save json."""
    if not ctx.text_output:
        await _handle_wait_text(ctx, block)
    await _handle_save_json(ctx, block)

