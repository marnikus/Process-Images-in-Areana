"""SolvePlan — per-solve data bundle shared by solver and polling.

Pure data, no behaviour (RULE 18: leaves may be small). Bundles the
client, CDP control, signal, and progress fields so every stage method
stays within the RULE 16 params gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from .api_client import Captcha2Client
from .signals import CaptchaSignal


@dataclass
class SolvePlan:
    """Per-solve bundle to keep solver methods ≤4 params (RULE 16)."""

    client: Captcha2Client
    ctrl: Any
    tab_id: str
    signal: CaptchaSignal
    stop: Callable[[], bool]
    start: float
    stats: Any = None
    logger: Optional[Callable[[str, str], None]] = None
    token_at: float = 0.0  # monotonic() when the provider token arrived
    err_base: Optional[str] = None  # error-scan corpus at solve start (None = not taken)
    err_seen: bool = False  # a mid-solve page error was already logged
    polls: int = 0  # provider poll rounds (report retry count)
    token_fp: str = ""  # token fingerprint (shape only)
    dialog_at_token: str = ""  # visible | gone | "" (no token yet)
    inject: str = ""  # "scope=.. fields=.. cb=.." summary
    page_error_at: float = 0.0  # solve-start-relative seconds of a mid-solve error
    page_error: str = ""
    stale_reason: str = ""
    page_identity: str = ""
    challenge_identity: str = ""
