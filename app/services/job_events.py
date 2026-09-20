"""Job lifecycle wire shapes shared by the sequential and parallel run paths.

`job_started(job_id, image_path)` / `job_finished(job_id, payload_json)` are
the per-job UI signals. B10 (I-39/I-40): the finished payload carries the
image identity + row fields so the Image Queue can patch the exact row the
moment a job ends — independent of the debounced full-state push, which
stays the source of truth and lands right after.
"""

from __future__ import annotations

from typing import Any, Dict


def job_finished_payload(img: Any, status: str, message: str) -> Dict[str, Any]:
    """{status, message, output_path, image_id, image_path, attempts, error}."""
    error = (getattr(img, "error", "") or "") if status == "failed" else ""
    return {
        "status": status,
        "message": message,
        "output_path": getattr(img, "output_path", "") or "",
        "image_id": getattr(img, "id", "") or "",
        "image_path": getattr(img, "absolute_path", "") or "",
        "attempts": int(getattr(img, "attempt_count", 0) or 0),
        "error": error,
    }
