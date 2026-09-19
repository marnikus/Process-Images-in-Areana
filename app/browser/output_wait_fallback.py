"""Output wait fallback — C11 split from output_wait.py for RULE18 file 150-300.

Handles timeout fallback, recheck after delay, and mismatch blocking logic.
"""

from __future__ import annotations

import asyncio
from typing import Callable


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


def _has_assoc_mismatch(diag: dict) -> bool:
    assoc = diag.get("associatedJobId")
    exp = diag.get("expectedJobId") or diag.get("jobId")
    return bool(exp and assoc and assoc != exp)


def _extract_fallback_src(diag: dict) -> str | None:
    src = diag.get("src")
    if src:
        return src
    try:
        return (diag.get("allNewDetails", [{}])[0] or {}).get("src")
    except Exception:
        return None


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
