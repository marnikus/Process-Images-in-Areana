"""Arena output — wait_for_new_output loop (C3).

RULE18: file 150-300, func ≤20, CC≤10, params≤4 (C6 WaitSpec).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Tuple, Callable, List

from ..output_probes import build_check_js
from ..output_state import flatten_diagnostics
from ..output_wait import wait_for_new_output_loop
from ...utils.page_errors import PageErrorAbort, match_page_error
from .state import capture_baseline, scan_page_errors

log = logging.getLogger("arena")


@dataclass
class PollContext:
    old_srcs: List[str] = field(default_factory=list)
    correlation_id: Optional[str] = None
    old_outputs: List[Any] = field(default_factory=list)
    err_base: str = ""


@dataclass
class WaitSpec:
    baseline: Dict[str, Any] = field(default_factory=dict)
    timeout_ms: int = 180000
    correlation_id: Optional[str] = None
    cancel_check: Optional[Callable] = None
    log_cb: Optional[Callable] = None
    ctrl: Any = None


async def _run_resume_gate(ctrl, diag):
    gate = getattr(ctrl, "resume_gate", None)
    if gate is None:
        return diag
    try:
        return await gate(diag) or diag
    except Exception:
        return diag


async def _poll_output_diag(cdp, ctx: PollContext, ctrl) -> Dict[str, Any]:
    js = build_check_js(ctx.old_srcs, ctx.correlation_id, ctx.old_outputs)
    res = await cdp.evaluate(js)
    diag = flatten_diagnostics(res) if res else {"ready": False, "reason": "no_result"}
    if diag.get("ready"):
        return diag
    err = match_page_error(await scan_page_errors(cdp), ctx.err_base)
    if err:
        raise PageErrorAbort(err)
    return diag


async def _security_gate(cdp, ctrl) -> None:
    settler = getattr(ctrl, "security_settler", None)
    if settler is None:
        return
    try:
        from .state import is_security_dialog_visible
        if await is_security_dialog_visible(cdp):
            await settler()
    except Exception as e:
        log.debug(f"security gate settle failed {e}")


async def _map_wait_result(cdp, result, baseline, timeout_ms):
    if result.get("ready"):
        rect = result.get("rect")
        return "completed", {"new_src": result.get("src"), "check": result,
                             "baseline": baseline, "rect": rect}
    if result.get("reason") == "cancelled":
        return "failed", {"error": "Cancelled", "cancelled": True}
    final_baseline = await capture_baseline(cdp)
    return "failed", {"error": f"Timeout after {timeout_ms}ms",
                      "last_baseline": final_baseline, "last_check": result}


async def _build_poll_context(baseline: Dict[str, Any], correlation_id, err_base) -> PollContext:
    return PollContext(
        old_srcs=baseline.get("output_srcs", []) or [],
        old_outputs=baseline.get("outputs", []) or [],
        correlation_id=correlation_id,
        err_base=err_base,
    )


async def wait_for_new_output(cdp, spec: WaitSpec) -> Tuple[str, Dict[str, Any]]:
    baseline = spec.baseline
    err_base = await scan_page_errors(cdp)
    ctx = await _build_poll_context(baseline, spec.correlation_id, err_base)

    async def check_fn():
        await _security_gate(cdp, spec.ctrl)
        diag = await _poll_output_diag(cdp, ctx, spec.ctrl)
        return await _run_resume_gate(spec.ctrl, diag)

    def _log(msg: str):
        if spec.log_cb:
            spec.log_cb(msg)

    try:
        first_err = match_page_error(err_base)
        if first_err:
            return "failed", {"error": first_err}
        result = await wait_for_new_output_loop(
            check_fn=check_fn,
            log_cb=_log,
            cancel_check=spec.cancel_check,
            timeout=spec.timeout_ms / 1000.0,
            poll_interval=2.0,
        )
        return await _map_wait_result(cdp, result, baseline, spec.timeout_ms)
    except Exception as e:
        return "failed", {"error": str(e)}


async def wait_for_new_output_legacy(cdp, baseline: Dict[str, Any], timeout_ms: int = 180000,
                                     correlation_id: Optional[str] = None,
                                     cancel_check=None, log_cb=None, ctrl=None):
    spec = WaitSpec(baseline=baseline, timeout_ms=timeout_ms,
                    correlation_id=correlation_id, cancel_check=cancel_check,
                    log_cb=log_cb, ctrl=ctrl)
    return await wait_for_new_output(cdp, spec)
