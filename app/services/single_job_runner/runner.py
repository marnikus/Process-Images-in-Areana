from __future__ import annotations
from typing import Any, Optional, Tuple
from .context import JobCtx
from .emit import _get_blocks
from .loop import _loop_blocks
from .state import _init_old_srcs

def _reset_captcha_reports(ctx: JobCtx):
    """Drop stale encounter stash (a reused ctrl must not leak reports)."""
    try:
        ctx.ctrl._captcha_reports = []
    except Exception:
        pass

def _captcha_job_line(ctx: JobCtx, entry: Dict[str, Any], failed: bool, error: str) -> Dict[str, Any]:
    """One CAPTCHA_JOB join record for a stashed encounter."""
    perr = error if "Page error:" in (error or "") else ""
    return {"v": 1, "eid": entry.get("eid", ""), "corr": ctx.corr_id,
            "tab": entry.get("tab", ctx.tab_id),
            "image": getattr(ctx.img, "relative_path", "") or "",
            "job": "failed" if failed else "completed",
            "error": str(error or "")[:200], "page_error": perr[:200]}

def _emit_captcha_job_lines(ctx: JobCtx, failed: bool, error: str) -> None:
    """Drain the encounter stash (each eid reported exactly once) + note the count for history."""
    try:
        lst = getattr(ctx.ctrl, "_captcha_reports", None)
        if not isinstance(lst, list):
            lst = []
        ctx.ctrl._captcha_reports = []
        note_captcha_count(ctx.bridge, getattr(ctx, "job_id", ""), len(lst))
    except Exception:
        return
    for entry in lst:
        try:
            line = _captcha_job_line(ctx, entry if isinstance(entry, dict) else {}, failed, error)
            ctx.bridge._log(f"[{ctx.corr_id}] 🧾 CAPTCHA_JOB {json.dumps(line, ensure_ascii=False)}", "info")
        except Exception:
            pass

async def run_blocks_for_image(ctx: JobCtx) -> tuple[bool, str, Optional[str], Optional[bytes]]:
    blocks = _get_blocks(ctx)
    _init_old_srcs(ctx)
    _reset_captcha_reports(ctx)
    failed, error = await _loop_blocks(ctx, blocks)
    _emit_captcha_job_lines(ctx, failed, error)
    return failed, error, ctx.new_src, ctx.file_bytes

