"""Output wait loop — polling, fallback, 3s stabilization + strict JOB-ID verification."""

import asyncio
import time
from typing import Callable


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


def should_fallback(elapsed: float, diag: dict) -> bool:
    if elapsed < 10:
        return False
    # Never fallback to mismatched JOB-ID image
    if diag.get("reason") == "job_id_mismatch_no_matching_image":
        return False
    if diag.get("mismatchDetails"):
        if len(diag.get("mismatchDetails", [])) > 0 and diag.get("allNew", 0) > 0:
            # Has only mismatched images, do not fallback
            if diag.get("validBelow", 0) == 0 and diag.get("validAbove", 0) == 0:
                return False
    if diag.get("allNew", 0) > 0 and diag.get("validBelow", 0) == 0 and diag.get("validAbove", 0) == 0:
        return True
    if diag.get("allNew", 0) > 0 and diag.get("spinning") is False:
        # Only fallback if no mismatch
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
        log_cb(f"✅ New output verified: top={diag.get('top')} associated {assoc} == expected {expected} layout={'reverse' if diag.get('layoutReverse') else 'normal'} {diag.get('orderCheck','')}")
        log_cb("⏳ Waiting 3s before finalizing download as requested")
    except Exception:
        log_cb("✅ New output ready, waiting 3s")


async def handle_no_exact_below(diag: dict, log_cb: Callable) -> None:
    try:
        if is_mismatch_reason(diag.get("reason", "")):
            exp = diag.get("expectedJobId") or diag.get("jobId")
            mism = diag.get("mismatchDetails", [])
            found = ",".join([m.get("associated","?") for m in mism[:3]])
            log_cb(f"❌ JOB-ID mismatch: expected {exp} but found images belong to {found} — awaiting correct image, not downloading wrong")
        else:
            log_cb(f"🔍 No exact below jobTop {diag.get('jobTop')} prevTop {diag.get('prevJobTop')} allNew {diag.get('allNew')} below {diag.get('validBelow')} above {diag.get('validAbove')} expected {diag.get('expectedJobId')}, waiting")
    except Exception:
        log_cb("🔍 Waiting for image below prompt block")


async def handle_mismatch(diag: dict, log_cb: Callable) -> None:
    try:
        exp = diag.get("expectedJobId") or diag.get("jobId")
        mism = diag.get("mismatchDetails", [])
        pool = diag.get("poolDetails", [])
        log_cb(f"❌ Strict verification failed: expected JOB-ID {exp} not found. Mismatched images: {mism[:3]} Pool: {pool[:2]} — will NOT download incorrect image, process as error after timeout")
    except Exception:
        log_cb("❌ JOB-ID mismatch — not downloading incorrect image")


async def _handle_timeout_fallback(last_check: dict, timeout: float, log_cb: Callable) -> dict | None:
    if last_check.get("reason") == "job_id_mismatch_no_matching_image":
        return None
    if last_check.get("mismatchDetails"):
        return None
    if last_check.get("allNew", 0) > 0 and last_check.get("src"):
        # Only fallback if associated matches expected or no expected
        assoc = last_check.get("associatedJobId")
        exp = last_check.get("expectedJobId")
        if exp and assoc and assoc != exp:
            log_cb(f"⚠️ Timeout {timeout}s but only mismatched images (assoc {assoc} != expected {exp}) — NOT using fallback, error")
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
    """Let page-error aborts escape the poll wrapper immediately."""
    from ..utils.page_errors import PageErrorAbort
    if isinstance(exc, PageErrorAbort):
        raise exc


async def _process_ready(diag: dict, check_fn: Callable, log_cb: Callable) -> dict | None:
    assoc = diag.get("associatedJobId")
    exp = diag.get("expectedJobId") or diag.get("jobId")
    if exp and assoc and assoc != exp:
        await handle_mismatch(diag, log_cb)
        return None
    await handle_ready_result(diag, log_cb)
    await asyncio.sleep(3.0)
    try:
        recheck = await check_fn()
        from .output_state import flatten_diagnostics
        rd = flatten_diagnostics(recheck)
        r_assoc = rd.get("associatedJobId")
        r_exp = rd.get("expectedJobId") or rd.get("jobId")
        if r_exp and r_assoc and r_assoc != r_exp:
            log_cb(f"❌ Re-check after 3s mismatch: associated {r_assoc} != expected {r_exp} — NOT downloading")
            return None
        if rd.get("ready"):
            return rd
    except Exception:
        pass
    return diag


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


async def _process_fallback(diag: dict, elapsed: float, log_cb: Callable):
    if not should_fallback(elapsed, diag):
        return None
    src = diag.get("src")
    if not src:
        try:
            src = (diag.get("allNewDetails", [{}])[0] or {}).get("src")
        except Exception:
            src = None
    if src:
        assoc = diag.get("associatedJobId")
        exp = diag.get("expectedJobId")
        if exp and assoc and assoc != exp:
            return None
        log_cb(f"⚠️ Fallback after {elapsed:.1f}s {src[:80]}")
        await asyncio.sleep(3.0)
        diag["ready"] = True
        diag["fallback"] = True
        return diag
    return None


async def wait_for_new_output_loop(check_fn, log_cb, cancel_check, timeout, poll_interval=2.0) -> dict:
    start = time.monotonic()
    last = {"ready": False, "reason": "not_started"}
    spin_visible = False
    while True:
        if is_cancelled(cancel_check):
            return {"ready": False, "reason": "cancelled", "last": last}
        elapsed = time.monotonic() - start
        if elapsed > timeout:
            fb = await _handle_timeout_fallback(last, timeout, log_cb)
            if fb:
                return fb
            if last.get("reason") == "job_id_mismatch_no_matching_image":
                last["elapsed"] = elapsed
                return last
            return {"ready": False, "reason": "timeout", "last": last, "elapsed": elapsed}
        diag, err = await _poll_check(check_fn, poll_interval)
        if diag is None:
            last = err
            continue
        last = diag
        if is_ready_result(diag):
            ready = await _process_ready(diag, check_fn, log_cb)
            if ready:
                return ready
            # If ready was rejected due to mismatch, continue waiting
            if is_mismatch_reason(diag.get("reason", "")) or (diag.get("associatedJobId") and diag.get("expectedJobId") and diag.get("associatedJobId") != diag.get("expectedJobId")):
                await handle_mismatch(diag, log_cb)
                await asyncio.sleep(poll_interval)
                continue
            return diag
        spin_visible = await _process_spinner(diag, log_cb, spin_visible)
        if diag.get("reason") in ("no_exact_below_found_wait_next", "job_id_mismatch_no_matching_image"):
            await handle_no_exact_below(diag, log_cb)
            if is_mismatch_reason(diag.get("reason", "")):
                await handle_mismatch(diag, log_cb)
        fb = await _process_fallback(diag, elapsed, log_cb)
        if fb:
            return fb
        await asyncio.sleep(poll_interval)
