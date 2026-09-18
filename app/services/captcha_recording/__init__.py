"""Local, redacted captcha session recording (one canonical system).

`RecordingManager` owns the per-tab lifecycle; `manager.catalog` is the UI-facing
read/label/delete surface; `milestones` is the closed edge vocabulary both the
automatic and the manual path speak.
"""

from .manager import RecordingManager
from .models import RecordingLimits, VALID_ACTOR_LABELS, VALID_RESULT_LABELS
from .store import RecordingStore

__all__ = ["RecordingManager", "RecordingLimits", "RecordingStore",
           "VALID_ACTOR_LABELS", "VALID_RESULT_LABELS"]
