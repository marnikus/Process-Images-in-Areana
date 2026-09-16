"""Unit tests for job_state_machine.py — pure state logic, <1ms (Phase 2).

RULE 18: file 60-200 LOC ideal.
RULE 16: func LOC ≤30.
"""

import pytest

from app.services.job_state_machine import (
    BatchSchedulerState,
    can_job_transition,
    is_terminal_job_status,
    next_job_status_on_failure,
    next_job_status_on_success,
    schedule_batch,
    should_retry,
    should_stop_run,
)


@pytest.mark.unit
def test_can_job_transition_pure():
    assert can_job_transition("created", "baseline_captured") is True
    assert can_job_transition("created", "completed") is False


@pytest.mark.unit
def test_next_job_status_on_success_pure():
    assert next_job_status_on_success("created") == "baseline_captured"
    assert next_job_status_on_success("saving") == "completed"
    assert next_job_status_on_success("completed") is None


@pytest.mark.unit
def test_next_job_status_on_failure_pure():
    assert next_job_status_on_failure("waiting_generation", needs_review=False) == "failed"
    assert next_job_status_on_failure("waiting_generation", needs_review=True) == "needs_review"


@pytest.mark.unit
def test_should_retry_pure():
    assert should_retry("failed", attempt=1, max_attempts=3) is True
    assert should_retry("failed", attempt=3, max_attempts=3) is False
    assert should_retry("completed", attempt=1) is False


@pytest.mark.unit
def test_schedule_batch_pure():
    state = BatchSchedulerState(total=3, steady=2, busy=1, pending_jobs=5)
    res = schedule_batch(state)
    assert res["dispatchable"] == 2
    assert res["free"] == 2
    assert res["pending"] == 5

    state2 = BatchSchedulerState(total=2, steady=0, busy=2, pending_jobs=3)
    res2 = schedule_batch(state2)
    assert res2["dispatchable"] == 0


@pytest.mark.unit
def test_should_stop_run_pure():
    # No request → same state
    assert should_stop_run("running", cancel_requested=False, pause_requested=False) == "running"
    # Cancel requested
    assert should_stop_run("running", cancel_requested=True, pause_requested=False) == "cancelling_current"
    # Pause requested
    assert should_stop_run("running", cancel_requested=False, pause_requested=True) == "paused"


@pytest.mark.unit
def test_is_terminal_job_status_pure():
    assert is_terminal_job_status("completed") is True
    assert is_terminal_job_status("failed") is True
    assert is_terminal_job_status("needs_review") is True
    assert is_terminal_job_status("running") is False
    assert is_terminal_job_status("waiting_generation") is False
