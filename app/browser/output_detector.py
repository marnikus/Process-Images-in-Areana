"""Output Detector — pure decision logic extracted from output_wait/state (Phase 2).

Goals:
- No I/O, no asyncio.sleep, no CDP — pure dict → decision.
- Testable <1ms, no browser needed.
- RULE 18: file 150-300 LOC ideal, current ~180 LOC.
- RULE 16: func LOC ≤30, CC ≤10, nesting ≤4, params ≤4.

Extracted logic:
- is_job_id_match (pure)
- should_download (pure)
- should_fallback (pure, re-exported)
- detect_new_output (pure, given baseline + current list)
- decide_ready (pure, given diag)

Transport/polling stays in output_wait.py.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional, Tuple


def is_job_id_match(associated: Optional[str], expected: Optional[str]) -> bool:
    """Check if associated JOB-ID matches expected — pure."""
    if not expected:
        return True  # no expectation → allow
    if not associated:
        return False
    return associated == expected


def _has_job_mismatch(diag: Dict[str, Any]) -> bool:
    assoc = diag.get("associatedJobId")
    exp = diag.get("expectedJobId") or diag.get("jobId")
    return bool(exp and assoc and assoc != exp)


def _has_no_matching_image(diag: Dict[str, Any]) -> bool:
    return diag.get("reason") == "job_id_mismatch_no_matching_image"


def _has_src(diag: Dict[str, Any]) -> bool:
    if diag.get("src"):
        return True
    try:
        src = (diag.get("allNewDetails", [{}])[0] or {}).get("src")
        return bool(src)
    except Exception:
        return False


def should_download(diag: Dict[str, Any]) -> Tuple[bool, str]:
    """Decide if we should download — pure, never mismatch."""
    if _has_job_mismatch(diag):
        assoc = diag.get("associatedJobId")
        exp = diag.get("expectedJobId") or diag.get("jobId")
        return False, f"mismatch assoc {assoc} != expected {exp}"
    if _has_no_matching_image(diag):
        return False, "mismatch no matching image"
    if not diag.get("ready"):
        return False, f"not ready reason={diag.get('reason')}"
    if not _has_src(diag):
        return False, "no src"
    return True, "ready and matched"


def _is_only_mismatched(diag: Dict[str, Any]) -> bool:
    if not diag.get("mismatchDetails"):
        return False
    return diag.get("validBelow", 0) == 0 and diag.get("validAbove", 0) == 0


def should_fallback_pure(elapsed: float, diag: Dict[str, Any]) -> bool:
    """Pure fallback decision — extracted from output_wait."""
    if elapsed < 10:
        return False
    if _has_no_matching_image(diag):
        return False
    if _is_only_mismatched(diag):
        return False
    if diag.get("allNew", 0) > 0 and diag.get("validBelow", 0) == 0 and diag.get("validAbove", 0) == 0:
        return True
    if diag.get("allNew", 0) > 0 and diag.get("spinning") is False:
        return not bool(diag.get("mismatchDetails"))
    return False


def is_ready_result(diag: Dict[str, Any]) -> bool:
    """Pure check if diag is ready."""
    return bool(diag.get("ready"))


def is_mismatch_reason(reason: str) -> bool:
    """Pure check if reason is mismatch."""
    return reason in ("job_id_mismatch_no_matching_image", "job_id_mismatch")


def detect_new_output(baseline_srcs: List[str], current_srcs: List[str]) -> List[str]:
    """Detect new srcs not in baseline — pure list diff."""
    base_set = set(baseline_srcs or [])
    return [s for s in (current_srcs or []) if s not in base_set]


def _is_spinner_wait(diag: Dict[str, Any]) -> bool:
    if not diag.get("spinning"):
        return False
    return diag.get("reason") in (
        "generating_spinner_visible",
        "generating_no_new_yet",
        "job_id_mismatch_no_matching_image",
    )


def _decide_if_ready(diag: Dict[str, Any]) -> Dict[str, Any]:
    ok, reason = should_download(diag)
    if ok:
        return {"action": "download", "src": diag.get("src"), "diag": diag}
    return {"action": "error", "reason": reason, "diag": diag}


def decide_ready(diag: Dict[str, Any], elapsed: float) -> Dict[str, Any]:
    """Decide final action from diag — pure state machine."""
    if diag.get("reason") == "cancelled":
        return {"action": "cancelled", "diag": diag}
    if _has_job_mismatch(diag):
        assoc = diag.get("associatedJobId")
        exp = diag.get("expectedJobId") or diag.get("jobId")
        return {"action": "error", "reason": f"mismatch {assoc}!={exp}", "diag": diag}
    if is_ready_result(diag):
        return _decide_if_ready(diag)
    if _is_spinner_wait(diag):
        return {"action": "wait", "reason": "spinner", "diag": diag}
    if should_fallback_pure(elapsed, diag):
        ok, _ = should_download(diag)
        if ok:
            return {"action": "fallback", "src": diag.get("src"), "diag": diag}
    return {"action": "wait", "reason": diag.get("reason", "unknown"), "diag": diag}


def flatten_diagnostics_pure(result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Pure flatten — safe version of output_state.flatten_diagnostics."""
    if not result:
        return {"ready": False, "reason": "no_result"}
    if not isinstance(result, dict):
        return {"ready": False, "reason": f"not dict {type(result)}"}
    # If already flattened with ready key, return as is
    if "ready" in result:
        return result
    # Try to extract from nested
    try:
        # output_probes returns dict with ready, src, etc.
        return dict(result)
    except Exception:
        return {"ready": False, "reason": "flatten failed"}
