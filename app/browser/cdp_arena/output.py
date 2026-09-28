"""Arena output — wait_for_new_output loop (C3).

RULE18: file 150-300, func ≤20, CC≤10, params≤4 (C6 WaitSpec).
"""
from __future__ import annotations

import asyncio
import logging
from functools import partial
import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Tuple, Callable, List

from .. import page_recovery
from ..output_probes import build_check_js
from ..output_state import flatten_diagnostics
from ..output_wait import WaitSpec as PollSpec, wait_for_new_output_with_spec
from ...utils.page_errors import PageErrorAbort, match_dead_generation, match_page_error
from .state import capture_baseline, scan_page_errors

log = logging.getLogger("arena")

# I-78: a timeout on a page that stopped answering is not the end — the page is given
# this window to come back, then one look, before the wait fails (owner log 2026-09-28).
RESCUE_WINDOW_S = 20.0
RESCUE_LOOKS = 3
RESCUE_LOOK_S = 1.0


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
    diag = _read_check(cdp, await page_recovery.page_check(cdp, js))
    if diag.get("ready") or diag.get("reason") == "page_unresponsive":
        return diag   # I-71: no banner scan (another 30 s) on a page that is not answering
    err = match_page_error(await scan_page_errors(cdp), ctx.err_base)
    if err:
        raise PageErrorAbort(err)
    return diag


def _read_check(cdp, res) -> Dict[str, Any]:
    """The check's answer as a diag; no answer keeps the transport's reason (I-71)."""
    if res:
        return flatten_diagnostics(res)
    if page_recovery.page_unresponsive(cdp):
        return _frozen_diag(cdp)
    return _no_result_diag(cdp)


def _no_result_diag(cdp) -> Dict[str, Any]:
    """The check answered nothing: keep the transport's reason (I-71 — a bare `no_result` hid it)."""
    return {"ready": False, "reason": "no_result", "detail": page_recovery.evaluate_failure(cdp)[:120]}


def _frozen_diag(cdp) -> Dict[str, Any]:
    """'page_unresponsive' + the transport's words — what the wait tells and times out with."""
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
    """Run the settle and charge its duration to the wait's pause clock (S3)."""
    t0 = time.monotonic()
    await settler()
    if clock is not None:
        clock.note(time.monotonic() - t0)


async def _map_wait_result(cdp, result, baseline, timeout_ms):
    if result.get("ready"):
        rect = result.get("rect")
        return "completed", {"new_src": result.get("src"), "check": result,
                             "baseline": baseline, "rect": rect}
    if result.get("reason") == "cancelled":
        return "failed", {"error": "Cancelled", "cancelled": True}
    final_baseline = {} if page_recovery.page_unresponsive(cdp) else await _baseline_or_empty(cdp)
    return "failed", {"error": _timeout_text(result, timeout_ms),
                      "last_baseline": final_baseline, "last_check": result}


async def _baseline_or_empty(cdp) -> Dict[str, Any]:
    """The report's last baseline; a raising capture must not hide the timeout (RULE 4)."""
    try:
        return await capture_baseline(cdp)
    except Exception:
        return {}


def _timeout_text(result, timeout_ms) -> str:
    """'Timeout after Nms — last check: <reason>' plus the captcha pause evidence (I-69, RULE 4)."""
    note = result.get("pause_note") or ""
    return f"Timeout after {timeout_ms}ms{_last_check(result)}" + (f" ({note})" if note else "")


def _last_check(result) -> str:
    """What the probe answered last — the report's only clue why nothing was taken."""
    last = result.get("last") or result   # a mismatch timeout IS its own last answer
    reason = last.get("reason", "")
    if reason in ("", "timeout"):
        return ""
    detail = f" ({last['detail']})" if last.get("detail") else ""
    return f" — last check: {reason}{detail}{_spinner_note(last)}"


def _spinner_note(diag) -> str:
    """' (spinner: Max, Response B)' — which response rows were still spinning."""
    labels = ", ".join(str(d.get("label", "")) for d in diag.get("spinDetails") or [])
    return f" (spinner: {labels})" if labels else ""


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


def _log_line(spec: WaitSpec, message: str) -> None:
    """One wait line (RULE 2); a log without a sink stays quiet."""
    try:
        if spec.log_cb:
            spec.log_cb(message)
    except Exception:
        pass


async def _rescue_look(spec: WaitSpec, ctx: PollContext, cdp,
                       left: int = RESCUE_LOOKS) -> Optional[Dict[str, Any]]:
    """Up to `left` polls at the page that just answered; the ready diag or None (I-78)."""
    diag = await _rescue_read(spec, ctx, cdp)
    if diag.get("ready"):
        _log_line(spec, "🛟 the page answered again — the image that was on it is taken")
        diag["rescued"] = True
        return diag
    if left <= 1:
        return None
    await asyncio.sleep(RESCUE_LOOK_S)
    return await _rescue_look(spec, ctx, cdp, left - 1)


async def _rescue_read(spec: WaitSpec, ctx: PollContext, cdp) -> Dict[str, Any]:
    """One diag read for the rescue; a broken read is "no result" (RULE 4)."""
    try:
        return await _poll_diag_or_revive(spec.ctrl, ctx, cdp)
    except Exception:
        return {"ready": False, "reason": "no_result"}


async def _rescue_after_timeout(cdp, spec: WaitSpec, ctx: PollContext,
                                result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """I-78: a wait that timed out on a silent page gets a bounded look when it answers.

    The image may be sitting on the page (I-73) — the rescue takes it instead of reporting
    a timeout and navigating away. It never submits, never settles a captcha and never runs
    for a page that was answering all along (a plain slow generation keeps its timeout).
    """
    if result.get("ready") or not page_recovery.page_unresponsive(cdp):
        return None
    if not await page_recovery.await_page_answer(cdp, RESCUE_WINDOW_S):
        return None
    return await _rescue_look(spec, ctx, cdp)


async def _run_wait(cdp, spec: WaitSpec, ctx: PollContext) -> Tuple[str, Dict[str, Any]]:
    """Poll until the wait's own gates settle (done/abort mapping included)."""
    async def check_fn():
        if await page_recovery.still_frozen(cdp):   # I-71: a 3 s ping, not three 30 s probes
            return _frozen_diag(cdp)
        await _security_gate(cdp, spec.ctrl)
        diag = await _poll_diag_or_revive(spec.ctrl, ctx, cdp)
        return await _run_resume_gate(spec.ctrl, diag)

    poll = PollSpec(timeout=spec.timeout_ms / 1000.0, poll_interval=2.0, pause=getattr(spec.ctrl, "pause_clock", None))
    log = partial(_log_line, spec)                  # RULE 2: the wait's own sink
    result = await wait_for_new_output_with_spec(check_fn, log, spec.cancel_check, poll)
    return await _map_wait_rescue(cdp, spec, ctx, result)


async def _map_wait_rescue(cdp, spec: WaitSpec, ctx: PollContext,
                           result: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """I-78 rescue look, then the wait's own result mapping (one place, one rule)."""
    rescued = await _rescue_after_timeout(cdp, spec, ctx, result)
    return await _map_wait_result(cdp, rescued or result, spec.baseline, spec.timeout_ms)


async def wait_for_new_output(cdp, spec: WaitSpec) -> Tuple[str, Dict[str, Any]]:
    ctx = await _prepare_wait(cdp, spec)
    try:
        first_err = match_page_error(ctx.err_base)
        if first_err:
            return "failed", {"error": first_err}
        return await _run_wait(cdp, spec, ctx)
    except Exception as e:  # RULE 4: a broken poll is an honest failed wait
        return "failed", {"error": str(e)}
