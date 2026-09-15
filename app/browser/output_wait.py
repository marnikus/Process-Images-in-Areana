"""Output wait loop — polling, fallback, 3s stabilization."""

import asyncio
import time
from typing import Callable, Awaitable


def should_continue_after_spinner(reason: str) -> bool:
    return reason in ("generating_spinner_visible", "generating_no_new_yet")


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
    if diag.get("allNew", 0) > 0 and diag.get("validBelow", 0) == 0 and diag.get("validAbove", 0) == 0:
        return True
    if diag.get("allNew", 0) > 0 and diag.get("spinning") is False:
        return True
    return False


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
        log_cb(f"✅ New output below prompt ready top={diag.get('top')} large={diag.get('isLarge')} below={diag.get('validBelow')} above={diag.get('validAbove')} layout={'reverse' if diag.get('layoutReverse') else 'normal'} {diag.get('orderCheck','')}")
        log_cb("⏳ Waiting 3s before finalizing download as requested")
    except Exception:
        log_cb("✅ New output ready, waiting 3s")


async def handle_no_exact_below(diag: dict, log_cb: Callable) -> None:
    try:
        log_cb(f"🔍 No exact below jobTop {diag.get('jobTop')} prevTop {diag.get('prevJobTop')} allNew {diag.get('allNew')} below {diag.get('validBelow')} above {diag.get('validAbove')}, waiting")
    except Exception:
        log_cb("🔍 Waiting for image below prompt block")


async def _handle_timeout_fallback(last_check: dict, timeout: float, log_cb: Callable) -> dict | None:
    if last_check.get("allNew", 0) > 0 and last_check.get("src"):
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
        await asyncio.sleep(poll_interval)
        return None, {"ready": False, "reason": str(e)}


async def _process_ready(diag: dict, check_fn: Callable, log_cb: Callable) -> dict:
    await handle_ready_result(diag, log_cb)
    await asyncio.sleep(3.0)
    try:
        recheck = await check_fn()
        from .output_state import flatten_diagnostics
        rd = flatten_diagnostics(recheck)
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
            return fb or {"ready": False, "reason": "timeout", "last": last, "elapsed": elapsed}
        diag, err = await _poll_check(check_fn, poll_interval)
        if diag is None:
            last = err
            continue
        last = diag
        if is_ready_result(diag):
            return await _process_ready(diag, check_fn, log_cb)
        spin_visible = await _process_spinner(diag, log_cb, spin_visible)
        if diag.get("reason") == "no_exact_below_found_wait_next":
            await handle_no_exact_below(diag, log_cb)
        fb = await _process_fallback(diag, elapsed, log_cb)
        if fb:
            return fb
        await asyncio.sleep(poll_interval)
