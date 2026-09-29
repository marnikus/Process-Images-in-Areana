from __future__ import annotations
import logging
import time
from typing import Any, Dict
from ... import page_recovery
from ...text_output_probes import build_check_text_js
from ...output_state import flatten_diagnostics
from ...utils.page_errors import PageErrorAbort, match_page_error

log = logging.getLogger("arena")

async def _run_resume_gate(ctrl, diag):
    gate = getattr(ctrl, "resume_gate", None)
    if gate is None:
        return diag
    try:
        return await gate(diag) or diag
    except Exception:
        return diag

async def _scan_safely(scanner) -> str:
    if scanner is None:
        return ""
    try:
        return await scanner()
    except Exception:
        return ""

async def _poll_text_diag(cdp, ctx, ctrl) -> Dict[str, Any]:
    js = build_check_text_js(ctx.old_texts, ctx.correlation_id, ctx.old_outputs)
    diag = _read_check(cdp, await page_recovery.page_check(cdp, js))
    if diag.get("ready") or diag.get("reason") == "page_unresponsive":
        return diag
    from .state import scan_page_errors
    err = match_page_error(await scan_page_errors(cdp), ctx.err_base)
    if err:
        raise PageErrorAbort(err)
    return diag

def _read_check(cdp, res) -> Dict[str, Any]:
    if res:
        return flatten_diagnostics(res)
    if page_recovery.page_unresponsive(cdp):
        return _frozen_diag(cdp)
    return _no_result_diag(cdp)

def _no_result_diag(cdp) -> Dict[str, Any]:
    return {"ready": False, "reason": "no_result", "detail": page_recovery.evaluate_failure(cdp)[:120]}

def _frozen_diag(cdp) -> Dict[str, Any]:
    return {"ready": False, "reason": "page_unresponsive", "detail": page_recovery.unresponsive_text(cdp)}

async def _security_gate(cdp, ctrl) -> None:
    settler = getattr(ctrl, "security_settler", None)
    if settler is None:
        return
    try:
        from .state import is_security_dialog_visible
        if await is_security_dialog_visible(cdp):
            await _settle_timed(settler, getattr(ctrl, "pause_clock", None))
    except Exception as e:
        log.debug(f"security gate settle failed {e}")

async def _settle_timed(settler, clock) -> None:
    t0 = time.monotonic()
    await settler()
    if clock is not None:
        clock.note(time.monotonic() - t0)
