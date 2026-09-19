"""Output wait loop — C6 refactor with WaitSpec and small helpers."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Callable


@dataclass
class WaitSpec:
    timeout: float
    poll_interval: float = 2.0


@dataclass
class LoopState:
    last: dict
    spin_visible: bool = False
    start: float = 0.0


def should_continue_after_spinner(reason: str) -> bool:
    return reason in ("generating_spinner_visible", "generating_no_new_yet", "job_id_mismatch_no_matching_image")


def is_ready_result(diag: dict) -> bool:
    return bool(diag.get("ready"))


def is_cancelled(cancel_check: Callable | None) -> bool:
    if cancel_check is None:
        return False
    try:
        return bool(cancel_check())
    except Exception:
        return False


def _is_mismatch_block(diag: dict) -> bool:
    if diag.get("reason") == "job_id_mismatch_no_matching_image":
        return True
    mism = diag.get("mismatchDetails")
    if mism and len(mism) > 0 and diag.get("allNew", 0) > 0:
        if diag.get("validBelow", 0) == 0 and diag.get("validAbove", 0) == 0:
            return True
    return False


def should_fallback(elapsed: float, diag: dict) -> bool:
    if elapsed < 10:
        return False
    if _is_mismatch_block(diag):
        return False
    if diag.get("allNew", 0) > 0 and diag.get("validBelow", 0) == 0 and diag.get("validAbove", 0) == 0:
        return True
    if diag.get("allNew", 0) > 0 and diag.get("spinning") is False:
        if not diag.get("mismatchDetails"):
            return True
    return False


def is_mismatch_reason(reason: str) -> bool:
    return reason in ("job_id_mismatch_no_matching_image", "job_id_mismatch")


async def handle_spinner_visible(diag: dict, log_cb: Callable) -> None:
    try:
        d = diag.get("spinDetails", [])
        label = d[0].get("label") if d else "generating"
        log_cb(f"⏳ Generating {label} spinner visible")
    except Exception:
        log_cb("⏳ Spinner visible")


async def handle_spinner_gone(log_cb: Callable) -> None:
    log_cb("✅ Spinner gone, scanning for new image below prompt")


async def handle_ready_result(diag: dict, log_cb: Callable) -> None:
    try:
        assoc = diag.get("associatedJobId")
        expected = diag.get("expectedJobId") or diag.get("jobId")
        if assoc and expected and assoc != expected:
            log_cb(f"❌ JOB-ID mismatch before download: associated {assoc} != expected {expected} — will NOT download, error")
            return
        log_cb(f"✅ New output verified: top={diag.get('top')} associated {assoc} == expected {expected} "
               f"layout={'reverse' if diag.get('layoutReverse') else 'normal'} {diag.get('orderCheck','')}")
        log_cb("⏳ Waiting 3s before finalizing download as requested")
    except Exception:
        log_cb("✅ New output ready, waiting 3s")


async def handle_no_exact_below(diag: dict, log_cb: Callable) -> None:
    try:
        if is_mismatch_reason(diag.get("reason", "")):
            exp = diag.get("expectedJobId") or diag.get("jobId")
            mism = diag.get("mismatchDetails", [])
            found = ",".join([m.get("associated", "?") for m in mism[:3]])
            log_cb(f"❌ JOB-ID mismatch: expected {exp} but found images belong to {found} — awaiting correct image")
        else:
            log_cb(f"🔍 No exact below jobTop {diag.get('jobTop')} prevTop {diag.get('prevJobTop')} "
                   f"allNew {diag.get('allNew')} below {diag.get('validBelow')} above {diag.get('validAbove')} "
                   f"expected {diag.get('expectedJobId')}, waiting")
    except Exception:
        log_cb("🔍 Waiting for image below prompt block")


async def handle_mismatch(diag: dict, log_cb: Callable) -> None:
    try:
        exp = diag.get("expectedJobId") or diag.get("jobId")
        mism = diag.get("mismatchDetails", [])
        pool = diag.get("poolDetails", [])
        log_cb(f"❌ Strict verification failed: expected JOB-ID {exp} not found. "
               f"Mismatched images: {mism[:3]} Pool: {pool[:2]} — will NOT download incorrect image")
    except Exception:
        log_cb("❌ JOB-ID mismatch — not downloading incorrect image")


async def _handle_timeout_fallback(last_check: dict, timeout: float, log_cb: Callable) -> dict | None:
    if last_check.get("reason") == "job_id_mismatch_no_matching_image":
        return None
    if last_check.get("mismatchDetails"):
        return None
    if last_check.get("allNew", 0) > 0 and last_check.get("src"):
        assoc = last_check.get("associatedJobId")
        exp = last_check.get("expectedJobId")
        if exp and assoc and assoc != exp:
            log_cb(f"⚠️ Timeout {timeout}s but only mismatched images (assoc {assoc} != expected {exp}) — NOT using fallback")
            return None
        log_cb(f"⚠️ Timeout {timeout}s fallback stable image")
        last_check["ready"] = True
        last_check["fallback"] = True
        await asyncio.sleep(3.0)
        return last_check
    return None


async def _poll_check(check_fn: Callable, poll_interval: float):
    try:
        result = await check_fn()
        from .output_state import flatten_diagnostics
        return flatten_diagnostics(result), None
    except Exception as e:
        _reraise_abort(e)
        await asyncio.sleep(poll_interval)
        return None, {"ready": False, "reason": str(e)}


def _reraise_abort(exc: Exception) -> None:
    from ..utils.page_errors import PageErrorAbort
    if isinstance(exc, PageErrorAbort):
        raise exc


def _has_assoc_mismatch(diag: dict) -> bool:
    assoc = diag.get("associatedJobId")
    exp = diag.get("expectedJobId") or diag.get("jobId")
    return bool(exp and assoc and assoc != exp)


async def _recheck_after_delay(check_fn: Callable, log_cb: Callable) -> dict | None:
    await asyncio.sleep(3.0)
    try:
        recheck = await check_fn()
        from .output_state import flatten_diagnostics
        rd = flatten_diagnostics(recheck)
        if _has_assoc_mismatch(rd):
            r_assoc = rd.get("associatedJobId")
            r_exp = rd.get("expectedJobId") or rd.get("jobId")
            log_cb(f"❌ Re-check after 3s mismatch: associated {r_assoc} != expected {r_exp} — NOT downloading")
            return None
        if rd.get("ready"):
            return rd
    except Exception:
        pass
    return None


async def _process_ready(diag: dict, check_fn: Callable, log_cb: Callable) -> dict | None:
    if _has_assoc_mismatch(diag):
        await handle_mismatch(diag, log_cb)
        return None
    await handle_ready_result(diag, log_cb)
    rechecked = await _recheck_after_delay(check_fn, log_cb)
    return rechecked if rechecked is not None else diag


async def _process_spinner(diag: dict, log_cb: Callable, was_visible: bool) -> bool:
    reason = diag.get("reason", "")
    spinning = diag.get("spinning", False)
    if spinning and should_continue_after_spinner(reason):
        if not was_visible:
            await handle_spinner_visible(diag, log_cb)
        return True
    if was_visible and not spinning:
        await handle_spinner_gone(log_cb)
        return False
    return was_visible


def _extract_fallback_src(diag: dict) -> str | None:
    src = diag.get("src")
    if src:
        return src
    try:
        return (diag.get("allNewDetails", [{}])[0] or {}).get("src")
    except Exception:
        return None


async def _process_fallback(diag: dict, elapsed: float, log_cb: Callable):
    if not should_fallback(elapsed, diag):
        return None
    src = _extract_fallback_src(diag)
    if not src:
        return None
    assoc = diag.get("associatedJobId")
    exp = diag.get("expectedJobId")
    if exp and assoc and assoc != exp:
        return None
    log_cb(f"⚠️ Fallback after {elapsed:.1f}s {src[:80]}")
    await asyncio.sleep(3.0)
    diag["ready"] = True
    diag["fallback"] = True
    return diag


async def _check_cancelled(cancel_check, state: LoopState) -> dict | None:
    if is_cancelled(cancel_check):
        return {"ready": False, "reason": "cancelled", "last": state.last}
    return None


async def _check_timeout(state: LoopState, spec: WaitSpec, log_cb: Callable) -> dict | None:
    elapsed = time.monotonic() - state.start
    if elapsed <= spec.timeout:
        return None
    fb = await _handle_timeout_fallback(state.last, spec.timeout, log_cb)
    if fb:
        return fb
    if state.last.get("reason") == "job_id_mismatch_no_matching_image":
        state.last["elapsed"] = elapsed
        return state.last
    return {"ready": False, "reason": "timeout", "last": state.last, "elapsed": elapsed}


async def _handle_ready_branch(diag: dict, check_fn: Callable, log_cb: Callable, spec: WaitSpec):
    ready = await _process_ready(diag, check_fn, log_cb)
    if ready:
        return ready, True
    if is_mismatch_reason(diag.get("reason", "")) or (
        diag.get("associatedJobId") and diag.get("expectedJobId") and diag.get("associatedJobId") != diag.get("expectedJobId")
    ):
        await handle_mismatch(diag, log_cb)
        await asyncio.sleep(spec.poll_interval)
        return None, False
    return diag, True


async def _handle_non_ready_branch(diag: dict, log_cb: Callable, state: LoopState, spec: WaitSpec):
    state.spin_visible = await _process_spinner(diag, log_cb, state.spin_visible)
    if diag.get("reason") in ("no_exact_below_found_wait_next", "job_id_mismatch_no_matching_image"):
        await handle_no_exact_below(diag, log_cb)
        if is_mismatch_reason(diag.get("reason", "")):
            await handle_mismatch(diag, log_cb)
    fb = await _process_fallback(diag, time.monotonic() - state.start, log_cb)
    if fb:
        return fb
    return None


async def wait_for_new_output_loop(check_fn, log_cb, cancel_check, timeout, poll_interval=2.0) -> dict:
    spec = WaitSpec(timeout=timeout, poll_interval=poll_interval)
    return await wait_for_new_output_with_spec(check_fn, log_cb, cancel_check, spec)


async def wait_for_new_output_with_spec(check_fn, log_cb, cancel_check, spec: WaitSpec) -> dict:
    state = LoopState(last={"ready": False, "reason": "not_started"}, start=time.monotonic())
    while True:
        cancelled = await _check_cancelled(cancel_check, state)
        if cancelled:
            return cancelled
        timed_out = await _check_timeout(state, spec, log_cb)
        if timed_out:
            return timed_out

        diag, err = await _poll_check(check_fn, spec.poll_interval)
        if diag is None:
            state.last = err
            continue
        state.last = diag

        if is_ready_result(diag):
            result, done = await _handle_ready_branch(diag, check_fn, log_cb, spec)
            if done:
                return result
            continue

        fb_result = await _handle_non_ready_branch(diag, log_cb, state, spec)
        if fb_result:
            return fb_result
        await asyncio.sleep(spec.poll_interval)


def wait_for_new_output_loop_legacy(check_fn, log_cb, cancel_check, timeout, poll_interval=2.0):
    import asyncio as _asyncio
    return _asyncio.get_event_loop().run_until_complete(
        wait_for_new_output_loop(check_fn, log_cb, cancel_check, timeout, poll_interval)
    )
