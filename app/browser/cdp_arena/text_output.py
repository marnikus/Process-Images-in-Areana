"""Arena text output — wait_for_new_text_output loop (C3).

Mirrors output.py but for text descriptions.
RULE 18: file 150-300, func ≤20, CC≤10, params≤4.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .. import page_recovery
from ..text_output_probes import build_check_text_js
from ..output_probes import build_baseline_js as _image_baseline
from ..text_output_probes import build_baseline_text_js
from ..output_state import flatten_diagnostics
from ..output_wait import WaitSpec as PollSpec, wait_for_new_output_with_spec
from ...utils.page_errors import PageErrorAbort, match_page_error
from .state import capture_baseline as _capture_image_baseline, scan_page_errors

log = logging.getLogger("arena")


@dataclass
class PollContextText:
    old_texts: List[str] = field(default_factory=list)
    correlation_id: Optional[str] = None
    old_outputs: List[Any] = field(default_factory=list)
    err_base: str = ""


@dataclass
class WaitSpecText:
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
    if scanner is None:
        return ""
    try:
        return await scanner()
    except Exception:
        return ""


async def _poll_text_diag(cdp, ctx: PollContextText, ctrl) -> Dict[str, Any]:
    js = build_check_text_js(ctx.old_texts, ctx.correlation_id, ctx.old_outputs)
    diag = _read_check(cdp, await page_recovery.page_check(cdp, js))
    if diag.get("ready") or diag.get("reason") == "page_unresponsive":
        return diag
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
    return {
        "ready": False,
        "reason": "no_result",
        "detail": page_recovery.evaluate_failure(cdp)[:120],
    }


def _frozen_diag(cdp) -> Dict[str, Any]:
    return {
        "ready": False,
        "reason": "page_unresponsive",
        "detail": page_recovery.unresponsive_text(cdp),
    }


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


async def _map_wait_result(cdp, result, baseline, timeout_ms):
    if result.get("ready"):
        rect = result.get("rect")
        return "completed", {
            "new_text": result.get("text") or result.get("full_text"),
            "full_text": result.get("full_text") or result.get("text"),
            "check": result,
            "baseline": baseline,
            "rect": rect,
        }
    if result.get("reason") == "cancelled":
        return "failed", {"error": "Cancelled", "cancelled": True}
    final_baseline = {} if page_recovery.page_unresponsive(cdp) else await capture_text_baseline(cdp)
    return "failed", {
        "error": _timeout_text(result, timeout_ms),
        "last_baseline": final_baseline,
        "last_check": result,
    }


def _timeout_text(result, timeout_ms) -> str:
    note = result.get("pause_note") or ""
    return f"Timeout after {timeout_ms}ms{_last_check(result)}" + (f" ({note})" if note else "")


def _last_check(result) -> str:
    last = result.get("last") or result
    reason = last.get("reason", "")
    if reason in ("", "timeout"):
        return ""
    detail = f" ({last['detail']})" if last.get("detail") else ""
    return f" — last check: {reason}{detail}{_spinner_note(last)}"


def _spinner_note(diag) -> str:
    labels = ", ".join(str(d.get("label", "")) for d in diag.get("spinDetails") or [])
    return f" (spinner: {labels})" if labels else ""


async def _build_poll_context(baseline: Dict[str, Any], correlation_id, err_base) -> PollContextText:
    old_texts = []
    try:
        outs = baseline.get("text_outputs", []) or []
        for o in outs:
            t = o.get("text", "") if isinstance(o, dict) else str(o)
            if t:
                old_texts.append(t[:200])
    except Exception:
        old_texts = []
    return PollContextText(
        old_texts=old_texts,
        old_outputs=baseline.get("text_outputs", []) or [],
        correlation_id=correlation_id,
        err_base=err_base,
    )


async def _prepare_wait(cdp, spec: WaitSpecText) -> PollContextText:
    err_base = await scan_page_errors(cdp)
    ctx = await _build_poll_context(spec.baseline, spec.correlation_id, err_base)
    if spec.ctrl is not None:
        spec.ctrl._err_base = err_base
        spec.ctrl._dead_gen_revived = False
    return ctx


async def _run_wait(cdp, spec: WaitSpecText, ctx: PollContextText) -> Tuple[str, Dict[str, Any]]:
    async def check_fn():
        if await page_recovery.still_frozen(cdp):
            return _frozen_diag(cdp)
        await _security_gate(cdp, spec.ctrl)
        diag = await _poll_text_diag_or_revive(spec.ctrl, ctx, cdp)
        return await _run_resume_gate(spec.ctrl, diag)

    def _log(msg: str):
        if spec.log_cb:
            spec.log_cb(msg)

    poll = PollSpec(
        timeout=spec.timeout_ms / 1000.0,
        poll_interval=2.0,
        pause=getattr(spec.ctrl, "pause_clock", None),
    )
    result = await wait_for_new_output_with_spec(check_fn, _log, spec.cancel_check, poll)
    return await _map_wait_result(cdp, result, spec.baseline, spec.timeout_ms)


async def _poll_text_diag_or_revive(ctrl, ctx: PollContextText, cdp=None) -> Dict[str, Any]:
    try:
        poll = getattr(ctrl, "_poll_text_diag", None)
        if poll is not None:
            return await poll(ctx.old_texts, ctx.correlation_id, ctx.old_outputs)
        return await _poll_text_diag(cdp, ctx, ctrl)
    except PageErrorAbort as exc:
        raise


async def capture_text_baseline(cdp) -> Dict[str, Any]:
    try:
        raw = await page_recovery.page_check(cdp, build_baseline_text_js())
        if isinstance(raw, dict):
            return raw
        return {"text_count": 0, "text_outputs": []}
    except Exception:
        return {"text_count": 0, "text_outputs": []}


async def wait_for_new_text_output(cdp, spec: WaitSpecText) -> Tuple[str, Dict[str, Any]]:
    ctx = await _prepare_wait(cdp, spec)
    try:
        first_err = match_page_error(ctx.err_base)
        if first_err:
            return "failed", {"error": first_err}
        return await _run_wait(cdp, spec, ctx)
    except Exception as e:
        return "failed", {"error": str(e)}
