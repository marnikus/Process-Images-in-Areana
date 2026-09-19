"""Output state helper — diagnostics flattening for output probes/waits.

v4 adds strict JOB-ID verification: associatedJobId must equal expectedJobId.
The v4 order/mismatch decisions live in the probe payload itself
(output_probes.py) and output_wait.py; this module only normalises the
diag dict every consumer reads (RULE 4: empty vs broken distinct keys).
Imports: stdlib only.
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
