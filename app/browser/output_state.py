"""Output state helpers — diagnostics flattening and order check text.

v4 adds strict JOB-ID verification: associatedJobId must equal expectedJobId.
"""

def flatten_diagnostics(result: dict) -> dict:
    if not isinstance(result, dict):
        return {"ready": False, "reason": "invalid_result"}
    diag = dict(result)
    diag.setdefault("jobFound", False)
    diag.setdefault("jobTop", None)
    diag.setdefault("prevJobTop", None)
    diag.setdefault("nextJobTop", None)
    diag.setdefault("jobIndex", -1)
    diag.setdefault("allJobs", 0)
    diag.setdefault("validAbove", 0)
    diag.setdefault("validBelow", 0)
    diag.setdefault("belowCount", 0)
    diag.setdefault("aboveCount", 0)
    diag.setdefault("allNew", 0)
    diag.setdefault("layoutReverse", False)
    diag.setdefault("orderCheck", "")
    diag.setdefault("associatedJobId", None)
    diag.setdefault("expectedJobId", None)
    diag.setdefault("domPrevJobId", None)
    diag.setdefault("domNextJobId", None)
    diag.setdefault("visualPrevJobId", None)
    diag.setdefault("mismatchDetails", [])
    diag.setdefault("jobId", None)
    return diag


def build_order_check_text(diag: dict) -> str:
    job_top = diag.get("jobTop")
    prev_top = diag.get("prevJobTop")
    next_top = diag.get("nextJobTop")
    order = diag.get("orderCheck", "")
    layout = "reverse" if diag.get("layoutReverse") else "normal"
    assoc = diag.get("associatedJobId")
    expected = diag.get("expectedJobId") or diag.get("jobId")
    return f"jobTop {job_top} prevTop {prev_top} nextTop {next_top} layout {layout} associated {assoc} expected {expected} | {order}"


def should_use_below_pool(diag: dict) -> bool:
    return diag.get("validBelow", 0) > 0 or diag.get("belowCount", 0) > 0


def extract_rect(result: dict) -> dict | None:
    rect = result.get("rect")
    if isinstance(rect, dict):
        return rect
    return None


def extract_src(result: dict) -> str | None:
    src = result.get("src")
    if isinstance(src, str) and src.startswith("http"):
        return src
    return None


def is_job_id_match(diag: dict) -> bool:
    """Strict verification: associatedJobId must equal expectedJobId."""
    expected = diag.get("expectedJobId") or diag.get("jobId")
    associated = diag.get("associatedJobId")
    if not expected:
        return True
    if not associated:
        return True
    return associated == expected


def is_mismatch_error(diag: dict) -> bool:
    reason = diag.get("reason", "")
    return reason in ("job_id_mismatch_no_matching_image", "job_id_mismatch")
