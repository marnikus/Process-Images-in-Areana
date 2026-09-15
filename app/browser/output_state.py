"""Output state helpers — diagnostics flattening and order check text.

Extracted from cdp_arena.py to keep methods under 20 LOC per RULE 16.
"""


def flatten_diagnostics(result: dict) -> dict:
    # ideal-size: 14 lines reason=normalizes result dict with safe defaults
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
    return diag


def build_order_check_text(diag: dict) -> str:
    # ideal-size: 8 lines reason=builds order check log line
    job_top = diag.get("jobTop")
    prev_top = diag.get("prevJobTop")
    next_top = diag.get("nextJobTop")
    order = diag.get("orderCheck", "")
    layout = "reverse" if diag.get("layoutReverse") else "normal"
    return f"jobTop {job_top} prevTop {prev_top} nextTop {next_top} layout {layout} | {order}"


def should_use_below_pool(diag: dict) -> bool:
    # ideal-size: 4 lines reason=prefers below pool per user correction
    return diag.get("validBelow", 0) > 0 or diag.get("belowCount", 0) > 0


def extract_rect(result: dict) -> dict | None:
    # ideal-size: 4 lines reason=extracts rect safely
    rect = result.get("rect")
    if isinstance(rect, dict):
        return rect
    return None


def extract_src(result: dict) -> str | None:
    # ideal-size: 4 lines reason=extracts full src not truncated
    src = result.get("src")
    if isinstance(src, str) and src.startswith("http"):
        return src
    return None
