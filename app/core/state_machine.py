from typing import Dict, Set
from .enums import ImageStatus, JobStatus, RunState

# Valid transitions for Image
IMAGE_TRANSITIONS: Dict[str, Set[str]] = {
    ImageStatus.PENDING.value: {ImageStatus.SELECTED.value, ImageStatus.DESELECTED.value, ImageStatus.SKIPPED.value, ImageStatus.PROCESSING.value},
    ImageStatus.SELECTED.value: {ImageStatus.PENDING.value, ImageStatus.DESELECTED.value, ImageStatus.PROCESSING.value, ImageStatus.SKIPPED.value},
    ImageStatus.DESELECTED.value: {ImageStatus.SELECTED.value, ImageStatus.PENDING.value},
    ImageStatus.PROCESSING.value: {ImageStatus.COMPLETED.value, ImageStatus.FAILED.value, ImageStatus.NEEDS_REVIEW.value, ImageStatus.SKIPPED.value},
    ImageStatus.COMPLETED.value: {ImageStatus.SELECTED.value, ImageStatus.PENDING.value, ImageStatus.DESELECTED.value},
    ImageStatus.FAILED.value: {ImageStatus.SELECTED.value, ImageStatus.PENDING.value, ImageStatus.DESELECTED.value, ImageStatus.SKIPPED.value},
    ImageStatus.SKIPPED.value: {ImageStatus.SELECTED.value, ImageStatus.PENDING.value, ImageStatus.DESELECTED.value},
    ImageStatus.NEEDS_REVIEW.value: {ImageStatus.SELECTED.value, ImageStatus.PENDING.value, ImageStatus.COMPLETED.value, ImageStatus.FAILED.value, ImageStatus.DESELECTED.value},
}

# Valid transitions for Job
JOB_TRANSITIONS: Dict[str, Set[str]] = {
    JobStatus.CREATED.value: {JobStatus.BASELINE_CAPTURED.value, JobStatus.FAILED.value, JobStatus.INTERRUPTED.value},
    JobStatus.BASELINE_CAPTURED.value: {JobStatus.ATTACHING.value, JobStatus.FAILED.value, JobStatus.PAUSED_USER_ACTION.value},
    JobStatus.ATTACHING.value: {JobStatus.ATTACHMENT_VERIFIED.value, JobStatus.FAILED.value, JobStatus.PAUSED_USER_ACTION.value},
    JobStatus.ATTACHMENT_VERIFIED.value: {JobStatus.PROMPT_INSERTED.value, JobStatus.FAILED.value},
    JobStatus.PROMPT_INSERTED.value: {JobStatus.PROMPT_VERIFIED.value, JobStatus.FAILED.value},
    JobStatus.PROMPT_VERIFIED.value: {JobStatus.SUBMITTED.value, JobStatus.FAILED.value},
    JobStatus.SUBMITTED.value: {JobStatus.WAITING_GENERATION.value, JobStatus.FAILED.value, JobStatus.PAUSED_USER_ACTION.value},
    JobStatus.WAITING_GENERATION.value: {JobStatus.OUTPUT_DETECTED.value, JobStatus.FAILED.value, JobStatus.NEEDS_REVIEW.value, JobStatus.PAUSED_USER_ACTION.value},
    JobStatus.OUTPUT_DETECTED.value: {JobStatus.DOWNLOADING.value, JobStatus.FAILED.value, JobStatus.NEEDS_REVIEW.value},
    JobStatus.DOWNLOADING.value: {JobStatus.VALIDATING.value, JobStatus.FAILED.value},
    JobStatus.VALIDATING.value: {JobStatus.SAVING.value, JobStatus.FAILED.value, JobStatus.NEEDS_REVIEW.value},
    JobStatus.SAVING.value: {JobStatus.COMPLETED.value, JobStatus.FAILED.value},
    JobStatus.COMPLETED.value: set(),
    JobStatus.FAILED.value: {JobStatus.CREATED.value},  # retry creates new attempt but could transition to created
    JobStatus.NEEDS_REVIEW.value: {JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.CREATED.value},
    JobStatus.PAUSED_USER_ACTION.value: {JobStatus.BASELINE_CAPTURED.value, JobStatus.ATTACHING.value, JobStatus.SUBMITTED.value, JobStatus.WAITING_GENERATION.value, JobStatus.FAILED.value},
    JobStatus.INTERRUPTED.value: {JobStatus.CREATED.value, JobStatus.FAILED.value},
}

# Valid transitions for RunState
RUN_TRANSITIONS: Dict[str, Set[str]] = {
    RunState.IDLE.value: {RunState.RUNNING.value, RunState.ERROR.value},
    RunState.RUNNING.value: {RunState.PAUSED.value, RunState.STOPPING_AFTER_CURRENT.value, RunState.CANCELLING_CURRENT.value, RunState.BATCH_COMPLETE.value, RunState.ERROR.value, RunState.IDLE.value},
    RunState.PAUSED.value: {RunState.RUNNING.value, RunState.IDLE.value, RunState.STOPPING_AFTER_CURRENT.value, RunState.ERROR.value},
    RunState.STOPPING_AFTER_CURRENT.value: {RunState.IDLE.value, RunState.BATCH_COMPLETE.value, RunState.ERROR.value},
    RunState.CANCELLING_CURRENT.value: {RunState.IDLE.value, RunState.RUNNING.value, RunState.ERROR.value},
    RunState.BATCH_COMPLETE.value: {RunState.IDLE.value, RunState.RUNNING.value},
    RunState.ERROR.value: {RunState.IDLE.value},
}

def can_transition(current: str, next_state: str, transitions: Dict[str, Set[str]]) -> bool:
    allowed = transitions.get(current, set())
    return next_state in allowed

def validate_image_transition(current: str, next_state: str) -> bool:
    return can_transition(current, next_state, IMAGE_TRANSITIONS)

def validate_job_transition(current: str, next_state: str) -> bool:
    return can_transition(current, next_state, JOB_TRANSITIONS)

def validate_run_transition(current: str, next_state: str) -> bool:
    return can_transition(current, next_state, RUN_TRANSITIONS)
