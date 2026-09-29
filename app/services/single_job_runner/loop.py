from __future__ import annotations
from typing import Any, Dict, List, Tuple
from .context import JobCtx, log, _OUTPUT_BLOCKS
from .emit import _emit_action, _get_blocks, _report_recovery
from .state import _init_old_srcs, _maybe_delay, _tab_aborted, _is_cancelled, _output_secured
from .handlers import _handler_map

async def _handle_one_block(ctx: JobCtx, block: Any):
    """Dispatch one block (unknown types skip, legacy parity)."""
    hmap = _handler_map()
    btype = getattr(block, "block_id", "")
    handler = hmap.get(btype)
    if handler:
        await handler(ctx, block)
    else:
        _report_recovery(ctx, f"Unknown block type {btype}, skipping", "warn")
        _emit_action(ctx, block, "skipped", f"Unknown type {btype}")

def _block_skip_reason(ctx: JobCtx, block: Any):
    """Cancellation/disabled short-circuit result, or None to run."""
    if _is_cancelled(ctx):
        reason = "Aborted by operator" if _tab_aborted(ctx) else "Cancelled by user"
        return True, reason, True
    if not getattr(block, "enabled", True):
        _emit_action(ctx, block, "skipped", "Skipped (disabled)")
        return False, "", False
    return None

async def _run_one_checked(ctx: JobCtx, block: Any) -> tuple[bool, str, bool]:
    skip = _block_skip_reason(ctx, block)
    if skip is not None:
        return skip
    await _maybe_delay(block)
    try:
        _emit_action(ctx, block, "running", f"[{ctx.tab_id[:6]}] {block.display_name}")
    except Exception:
        pass
    try:
        await _handle_one_block(ctx, block)
        return False, "", False
    except Exception as e:
        err = str(e)
        try:
            _emit_action(ctx, block, "failed", err)
        except Exception:
            pass
        should_break = bool(getattr(block, "required", False))
        return True, err, should_break

def _post_download_warning(ctx: JobCtx, block: Any, err: str, secured: bool) -> bool:
    """B8 policy: once the image is downloaded, a later page-action failure is
    a warning, not a job failure — the stack continues so VALIDATE/SAVE keep
    the bytes (a paid generation is never thrown away). VALIDATE/SAVE and
    cancellation keep their normal failure semantics."""
    if not secured or _is_cancelled(ctx):
        return False
    if getattr(block, "block_id", "") in _OUTPUT_BLOCKS:
        return False
    name = getattr(block, "display_name", None) or getattr(block, "block_id", "block")
    _report_recovery(ctx, f"⚠ {name} failed after the image was downloaded ({err}) "
                          f"— continuing so the image is saved", "warn")
    return True

def _record_failure(block: Any, err: str, brk: bool, acc: Dict[str, Any]) -> bool:
    """Classify one block failure into the run accumulator; True = stop the stack.

    hard: a required break or a VALIDATE/SAVE failure (never forgiven);
    soft: a non-required block that failed while the stack continued."""
    acc["failed"], acc["error"] = True, err
    if brk or getattr(block, "block_id", "") in _OUTPUT_BLOCKS:
        acc["hard"] = True
        return brk
    acc["soft"].append(f"{_display(block)} ({err})")
    return False

def _soft_failures_forgiven(ctx: JobCtx, acc: Dict[str, Any]) -> bool:
    """B9 policy: optional (`required=False`) blocks that failed BEFORE the
    download do not fail a job whose image was then downloaded, validated
    and SAVED — the paid generation is on disk and the block rows already
    show the red status. Required breaks, VALIDATE/SAVE failures and
    cancellation keep their failure semantics (goldens req_fail / cancel)."""
    if not acc["failed"] or acc["hard"] or not acc["saved"] or not acc["soft"]:
        return False
    if _is_cancelled(ctx) or not _output_secured(ctx):
        return False
    _report_recovery(ctx, "⚠ Completed with warnings — the image was saved although "
                          "non-required block(s) failed: " + "; ".join(acc["soft"]), "warn")
    return True

def _absorb_block_result(ctx: JobCtx, block: Any, result: tuple, acc: Dict[str, Any]) -> bool:
    """Fold one block outcome into the run accumulator; True = stop the stack."""
    failed, err, brk = result
    if not failed:
        if getattr(block, "block_id", "") == "SAVE":
            acc["saved"] = True
        return False
    if _post_download_warning(ctx, block, err, acc["secured"]):
        return False
    return _record_failure(block, err, brk, acc)

async def _loop_blocks(ctx: JobCtx, blocks: List[Any]) -> tuple[bool, str]:
    acc: Dict[str, Any] = {"failed": False, "error": "", "hard": False, "soft": [],
                           "saved": False, "secured": False}
    for block in blocks:
        acc["secured"] = _output_secured(ctx)  # before the block runs (B8)
        result = await _run_one_checked(ctx, block)
        if _absorb_block_result(ctx, block, result, acc):
            break
        if _is_cancelled(ctx) and acc["failed"]:
            break
    if _soft_failures_forgiven(ctx, acc):
        return False, ""
    return acc["failed"], acc["error"]

