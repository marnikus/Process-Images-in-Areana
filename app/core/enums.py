from enum import Enum

class UrlStatus(str, Enum):
    UNCHECKED = "unchecked"
    CHECKING = "checking"
    READY = "ready"
    UNAVAILABLE = "unavailable"
    AUTH_REQUIRED = "authentication required"
    CAPTCHA_REQUIRED = "CAPTCHA/user action required"
    UNSUPPORTED = "unsupported page"
    ERROR = "error"

class ImageStatus(str, Enum):
    PENDING = "pending"
    SELECTED = "selected"
    DESELECTED = "deselected"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    NEEDS_REVIEW = "needs_review"

class JobStatus(str, Enum):
    CREATED = "created"
    BASELINE_CAPTURED = "baseline_captured"
    ATTACHING = "attaching"
    ATTACHMENT_VERIFIED = "attachment_verified"
    PROMPT_INSERTED = "prompt_inserted"
    PROMPT_VERIFIED = "prompt_verified"
    SUBMITTED = "submitted"
    WAITING_GENERATION = "waiting_generation"
    OUTPUT_DETECTED = "output_detected"
    DOWNLOADING = "downloading"
    VALIDATING = "validating"
    SAVING = "saving"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    PAUSED_USER_ACTION = "paused_user_action_required"
    INTERRUPTED = "interrupted"

class RunState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING_AFTER_CURRENT = "stopping_after_current"
    CANCELLING_CURRENT = "cancelling_current"
    BATCH_COMPLETE = "batch_complete"
    ERROR = "error"
