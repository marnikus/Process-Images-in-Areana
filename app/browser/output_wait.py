"""Output wait loop — polling, fallback, 3s stabilization + strict JOB-ID verification."""

import asyncio
import time
from dataclasses import dataclass
from typing import Callable, Awaitable


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


def _has_unmatched_pool(diag: dict) -> bool:
    """New images exist but none landed in a valid pool."""
    return (diag.get("allNew", 0) > 0
            and diag.get("validBelow", 0) == 0
            and diag.get("validAbove", 0) == 0)


def should_fallback(elapsed: float, diag: dict) -> bool:
    if elapsed < 10:
        return False
    # Never fallback to a mismatched JOB-ID image
    if diag.get("reason") == "job_id_mismatch_no_matching_image":
        return False
    if diag.get("mismatchDetails") and _has_unmatched_pool(diag):
        return False  # only mismatched images — keep waiting
    if _has_unmatched_pool(diag):
        return True
    return (diag.get("allNew", 0) > 0
            and diag.get("spinning") is False
            and not diag.get("mismatchDetails"))


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


async def _recheck_after_stabilize(diag: dict, check_fn: Callable, log_cb: Callable) -> tuple[bool, dict | None]:
    """3s re-check after a ready result. (confirmed, rd): confirmed=False
    means the re-check flipped to a mismatch — drop the ready result."""
    await asyncio.sleep(3.0)
    try:
        from .output_state import flatten_diagnostics
        rd = flatten_diagnostics(await check_fn())
        r_assoc = rd.get("associatedJobId")
        r_exp = rd.get("expectedJobId") or rd.get("jobId")
        if r_exp and r_assoc and r_assoc != r_exp:
            log_cb(f"❌ Re-check after 3s mismatch: associated {r_assoc} != expected {r_exp} — NOT downloading")
            return False, None
        if rd.get("ready"):
            return True, rd
    except Exception:
        pass
    return True, None


async def _process_ready(diag: dict, check_fn: Callable, log_cb: Callable) -> dict | None:
    assoc = diag.get("associatedJobId")
    exp = diag.get("expectedJobId") or diag.get("jobId")
    if exp and assoc and assoc != exp:
        await handle_mismatch(diag, log_cb)
        return None
    await handle_ready_result(diag, log_cb)
    confirmed, rd = await _recheck_after_stabilize(diag, check_fn, log_cb)
    if not confirmed:
        return None
    return rd if rd is not None else diag


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


@dataclass
class WaitSpec:
    """Inputs of the output wait loop (params object, W0.2)."""

    check_fn: Callable
    log_cb: Callable
    timeout: float
    cancel_check: Callable | None = None
    poll_interval: float = 2.0


async def _timeout_exit(last: dict, elapsed: float, timeout: float, log_cb: Callable) -> dict:
    """Terminal result once the timeout budget is spent."""
    fb = await _handle_timeout_fallback(last, timeout, log_cb)
    if fb:
        return fb
    if last.get("reason") == "job_id_mismatch_no_matching_image":
        last["elapsed"] = elapsed
        return last
    return {"ready": False, "reason": "timeout", "last": last, "elapsed": elapsed}


async def _handle_ready_cycle(diag: dict, spec: WaitSpec) -> dict | None:
    """Process a ready result; None = keep waiting (mismatch), else terminal."""
    ready = await _process_ready(diag, spec.check_fn, spec.log_cb)
    if ready:
        return ready
    assoc, exp = diag.get("associatedJobId"), diag.get("expectedJobId")
    if is_mismatch_reason(diag.get("reason", "")) or (assoc and exp and assoc != exp):
        await handle_mismatch(diag, spec.log_cb)
        await asyncio.sleep(spec.poll_interval)
        return None
    return diag


async def _poll_once(diag: dict, spec: WaitSpec, elapsed: float, spin_visible: bool):
    """One non-ready iteration: spinner tracking, wait/mismatch notes, fallback."""
    spin_visible = await _process_spinner(diag, spec.log_cb, spin_visible)
    if diag.get("reason") in ("no_exact_below_found_wait_next", "job_id_mismatch_no_matching_image"):
        await handle_no_exact_below(diag, spec.log_cb)
        if is_mismatch_reason(diag.get("reason", "")):
            await handle_mismatch(diag, spec.log_cb)
    fb = await _process_fallback(diag, elapsed, spec.log_cb)
    return (fb or None), spin_visible


async def _run_wait(spec: WaitSpec) -> dict:
    start = time.monotonic()
    last = {"ready": False, "reason": "not_started"}
    spin_visible = False
    while True:
        if is_cancelled(spec.cancel_check):
            return {"ready": False, "reason": "cancelled", "last": last}
        elapsed = time.monotonic() - start
        if elapsed > spec.timeout:
            return await _timeout_exit(last, elapsed, spec.timeout, spec.log_cb)
        diag, err = await _poll_check(spec.check_fn, spec.poll_interval)
        if diag is None:
            last = err
            continue
        last = diag
        if is_ready_result(diag):
            result = await _handle_ready_cycle(diag, spec)
            if result is not None:
                return result
            continue
        result, spin_visible = await _poll_once(diag, spec, elapsed, spin_visible)
        if result is not None:
            return result
        await asyncio.sleep(spec.poll_interval)


async def wait_for_new_output_loop(spec: WaitSpec) -> dict:
    """Poll for a new output image until ready/timeout/cancel (public seam)."""
    return await _run_wait(spec)
