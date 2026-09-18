"""Captcha session recording — diff-logging around captcha events.

Layer: services (no Qt, no browser imports except probe builders via the
recorder's ctrl parameter). Storage lives in git-ignored logs/recordings/.
RULE 20 privacy: recaptcha token material is redacted in-probe and again
here (defense in depth); recordings never change site behaviour.
"""

from .recorder import RecordingService
from .store import RecordingStore

__all__ = ["RecordingService", "RecordingStore"]
