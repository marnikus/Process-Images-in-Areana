from __future__ import annotations
from typing import Any, List
from .context import JobCtx, log
from app.services.run_state import JobAction

def _emit_action(ctx: JobCtx, block: Any, status: str, msg: str):
    """Emit action status."""
    try:
        ctx.bridge._emit_job_action_status(JobAction(ctx.job_id, block, status, msg))
    except Exception:
        pass

def _get_blocks(ctx: JobCtx) -> List[Any]:
    """Get action blocks."""
    try:
        return ctx.bridge._get_action_blocks()
    except Exception:
        return []

def _report_recovery(ctx: JobCtx, msg: str, level: str = "info"):
    """Revival log with the job correlation prefix (RULE 2)."""
    try:
        ctx.bridge._log(f"[{ctx.corr_id}] {msg}", level)
    except Exception:
        pass

def _mark_waiting(ctx: JobCtx, kind: str):
    """Mark waiting (pool attr; the old _ensure_page_pool call never existed)."""
    try:
        pool = getattr(ctx.bridge, "_page_pool", None)
        if pool:
            pool.mark_waiting(ctx.tab_id, kind)
            ctx.bridge._emit_pool_status()
    except Exception:
        pass

def _mark_busy(ctx: JobCtx):
    """Mark busy."""
    try:
        pool = getattr(ctx.bridge, "_page_pool", None)
        if pool:
            pool.mark_busy(ctx.tab_id, ctx.job_id)
            ctx.bridge._emit_pool_status()
    except Exception:
        pass

def _emit_saved_rect(ctx: JobCtx, name: str):
    """Saved-file confirmation rect (best effort, UI only)."""
    try:
        dur = ctx.bridge.config.get_state("highlight_duration", 3)
        payload = {"x": 100, "y": 100, "width": 200, "height": 200,
                   "duration": dur, "label": f"Saved {name}"}
        ctx.bridge.highlight_rect.emit(json.dumps(payload))
    except Exception:
        pass

def _display(block: Any) -> str:
    """Block display name (ActionBlock or bare stub)."""
    name = getattr(block, "display_name", "") or getattr(block, "name", "")
    if callable(name):
        try:
            name = name()
        except Exception:
            name = ""
    return name or getattr(block, "block_id", "block")

