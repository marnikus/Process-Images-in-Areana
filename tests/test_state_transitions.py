import pytest
from app.core.state_machine import validate_image_transition, validate_job_transition, validate_run_transition
from app.core.enums import ImageStatus, JobStatus, RunState

@pytest.mark.unit
def test_image_transitions_valid():
    assert validate_image_transition(ImageStatus.PENDING.value, ImageStatus.SELECTED.value) is True
    assert validate_image_transition(ImageStatus.SELECTED.value, ImageStatus.PROCESSING.value) is True
    assert validate_image_transition(ImageStatus.PROCESSING.value, ImageStatus.COMPLETED.value) is True
    assert validate_image_transition(ImageStatus.FAILED.value, ImageStatus.SELECTED.value) is True
    assert validate_image_transition(ImageStatus.COMPLETED.value, ImageStatus.SELECTED.value) is True

@pytest.mark.unit
def test_image_transitions_invalid():
    assert validate_image_transition(ImageStatus.PENDING.value, ImageStatus.COMPLETED.value) is False
    assert validate_image_transition(ImageStatus.DESELECTED.value, ImageStatus.COMPLETED.value) is False
    assert validate_image_transition(ImageStatus.COMPLETED.value, ImageStatus.PROCESSING.value) is False

@pytest.mark.unit
def test_job_transitions_valid():
    assert validate_job_transition(JobStatus.CREATED.value, JobStatus.BASELINE_CAPTURED.value) is True
    assert validate_job_transition(JobStatus.BASELINE_CAPTURED.value, JobStatus.ATTACHING.value) is True
    assert validate_job_transition(JobStatus.ATTACHING.value, JobStatus.ATTACHMENT_VERIFIED.value) is True
    assert validate_job_transition(JobStatus.SUBMITTED.value, JobStatus.WAITING_GENERATION.value) is True
    assert validate_job_transition(JobStatus.WAITING_GENERATION.value, JobStatus.OUTPUT_DETECTED.value) is True

@pytest.mark.unit
def test_job_transitions_invalid():
    assert validate_job_transition(JobStatus.CREATED.value, JobStatus.COMPLETED.value) is False
    assert validate_job_transition(JobStatus.COMPLETED.value, JobStatus.CREATED.value) is False
    assert validate_job_transition(JobStatus.FAILED.value, JobStatus.COMPLETED.value) is False

@pytest.mark.unit
def test_run_transitions_valid():
    assert validate_run_transition(RunState.IDLE.value, RunState.RUNNING.value) is True
    assert validate_run_transition(RunState.RUNNING.value, RunState.PAUSED.value) is True
    assert validate_run_transition(RunState.PAUSED.value, RunState.RUNNING.value) is True
    assert validate_run_transition(RunState.RUNNING.value, RunState.BATCH_COMPLETE.value) is True

@pytest.mark.unit
def test_run_transitions_invalid():
    assert validate_run_transition(RunState.IDLE.value, RunState.PAUSED.value) is False
    assert validate_run_transition(RunState.BATCH_COMPLETE.value, RunState.PAUSED.value) is False
    assert validate_run_transition(RunState.COMPLETED.value if hasattr(RunState, 'COMPLETED') else "completed", RunState.RUNNING.value) is False
