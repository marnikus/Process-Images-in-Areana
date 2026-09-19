"""Arena output — wait_for_new_output loop (C3).

RULE18: file 150-300, func ≤20, CC≤10, params≤4 (C6 WaitSpec).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Tuple, Callable, List

from ..output_probes import build_check_js
from ..output_state import flatten_diagnostics
from ..output_wait import WaitSpec as PollSpec, wait_for_new_output_with_spec
from ...utils.page_errors import PageErrorAbort, match_dead_generation, match_page_error
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


async def _scan_safely(scanner) -> str:
    """Fail-open scan: a broken/absent scanner reads as an empty corpus."""
    if scanner is None:
        return ""
    try:
        return await scanner()
    except Exception:
        return ""


async def _rebaseline_errors(ctrl, ctx) -> str:
    """Fresh page-error corpus after a converted toast (the banner must not re-fire)."""
    scanner = getattr(ctrl, "_scan_page_errors", None) or getattr(ctrl, "scan_page_errors", None)
    fresh = await _scan_safely(scanner)
    ctrl._err_base = fresh
    if ctx is not None:
        ctx.err_base = fresh
    return fresh


async def _convert_dead_generation(ctrl, err: str, ctx=None) -> Optional[Dict[str, Any]]:
    """Dead-generation toast -> one revival poll instead of an instant failure.

    Design `2026-09-18-dead-generation-toast-revival` §4.2. Converts only when
    the error is the site's dead-request toast, a `resume_gate` is armed, and
    this wait has not converted yet (one shot per wait, reset at wait start).
    Every other error re-raises unchanged (RULE 4: honest broken).
    """
    if match_dead_generation(err) == "":
        return None
    if getattr(ctrl, "resume_gate", None) is None or getattr(ctrl, "_dead_gen_revived", False):
        return None
    ctrl._dead_gen_revived = True
    await _rebaseline_errors(ctrl, ctx)
    return {"ready": False, "reason": "dead_generation", "dead_generation_error": err}


async def _poll_diag_or_revive(ctrl, ctx: PollContext, cdp=None) -> Dict[str, Any]:
    """One poll; a dead-generation abort becomes a revival diag, others re-raise.

    Always delegates the poll itself: `ctrl._poll_output_diag` when the
    controller has it (CDPArenaController mixin), else this module's scanner.
    """
    try:
        poll = getattr(ctrl, "_poll_output_diag", None)
        if poll is not None:
            return await poll(ctx.old_srcs, ctx.correlation_id, ctx.old_outputs)
        return await _poll_output_diag(cdp, ctx, ctrl)
    except PageErrorAbort as exc:
        diag = await _convert_dead_generation(ctrl, str(exc), ctx)
        if diag is None:
            raise
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


async def _prepare_wait(cdp, spec: WaitSpec) -> PollContext:
    """Scan the error corpus once per wait and prime the one-shot revival."""
    err_base = await scan_page_errors(cdp)
    ctx = await _build_poll_context(spec.baseline, spec.correlation_id, err_base)
    if spec.ctrl is not None:
        spec.ctrl._err_base = err_base          # conversion re-baselines through here
        spec.ctrl._dead_gen_revived = False     # one revival per wait
    return ctx


async def _run_wait(cdp, spec: WaitSpec, ctx: PollContext) -> Tuple[str, Dict[str, Any]]:
    """Poll until the wait's own gates settle (done/abort mapping included)."""
    async def check_fn():
        await _security_gate(cdp, spec.ctrl)
        diag = await _poll_diag_or_revive(spec.ctrl, ctx, cdp)
        return await _run_resume_gate(spec.ctrl, diag)

    def _log(msg: str):
        if spec.log_cb:
            spec.log_cb(msg)

    poll = PollSpec(timeout=spec.timeout_ms / 1000.0, poll_interval=2.0)
    result = await wait_for_new_output_with_spec(check_fn, _log, spec.cancel_check, poll)
    return await _map_wait_result(cdp, result, spec.baseline, spec.timeout_ms)


async def wait_for_new_output(cdp, spec: WaitSpec) -> Tuple[str, Dict[str, Any]]:
    ctx = await _prepare_wait(cdp, spec)
    try:
        first_err = match_page_error(ctx.err_base)
        if first_err:
            return "failed", {"error": first_err}
        return await _run_wait(cdp, spec, ctx)
    except Exception as e:  # RULE 4: a broken poll is an honest failed wait
        return "failed", {"error": str(e)}
