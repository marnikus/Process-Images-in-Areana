"""Job State Machine — pure logic extracted from job_runner.py (Phase 2).

Goals:
- No I/O, no browser, no FS — pure state transitions.
- Testable <1ms, no async needed for core logic.
- RULE 18: file 150-300 LOC ideal, current ~140 LOC.
- RULE 16: func LOC ≤30, CC ≤10, nesting ≤4, params ≤4.

Extracted from job_runner.py run_single_job state flow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..core.state_machine import validate_job_transition, validate_run_transition


@dataclass
class JobState:
    job_id: str
    status: str
    attempt: int = 1
    error: Optional[str] = None
    logs: List[Dict] = field(default_factory=list)


def can_job_transition(current: str, next_status: str) -> bool:
    """Pure check if job can transition — delegates to state_machine."""
    return validate_job_transition(current, next_status)


def next_job_status_on_success(current: str) -> Optional[str]:
    """Pure next status on success — maps current to next expected.

    Based on job_runner.py steps 09-20.
    """
    mapping = {
        "created": "baseline_captured",
        "baseline_captured": "attaching",
        "attaching": "attachment_verified",
        "attachment_verified": "prompt_inserted",
        "prompt_inserted": "prompt_verified",
        "prompt_verified": "submitted",
        "submitted": "waiting_generation",
        "waiting_generation": "output_detected",
        "output_detected": "downloading",
        "downloading": "validating",
        "validating": "saving",
        "saving": "completed",
    }
    return mapping.get(current)


def next_job_status_on_failure(current: str, needs_review: bool = False) -> str:
    """Pure next status on failure."""
    if needs_review:
        return "needs_review"
    return "failed"


def should_retry(status: str, attempt: int, max_attempts: int = 3) -> bool:
    """Pure retry decision."""
    if status != "failed":
        return False
    return attempt < max_attempts


@dataclass
class BatchSchedulerState:
    total: int
    steady: int
    busy: int
    pending_jobs: int


def schedule_batch(state: BatchSchedulerState) -> Dict[str, int]:
    """Pure batch scheduling decision — how many jobs can be dispatched now.

    Given pool counts and pending jobs, returns dispatchable count.
    No I/O, no async.
    """
    free = state.steady
    pending = state.pending_jobs
    dispatchable = min(free, pending)
    return {
        "dispatchable": dispatchable,
        "free": free,
        "pending": pending,
        "total_pages": state.total,
        "busy_pages": state.busy,
    }


def should_stop_run(run_state: str, cancel_requested: bool, pause_requested: bool) -> str:
    """Pure run control decision — returns next run state or current."""
    if cancel_requested:
        if validate_run_transition(run_state, "cancelling_current"):
            return "cancelling_current"
    if pause_requested:
        if validate_run_transition(run_state, "paused"):
            return "paused"
    return run_state


def is_terminal_job_status(status: str) -> bool:
    """Check if job status is terminal — pure."""
    return status in ("completed", "failed", "needs_review", "interrupted")
