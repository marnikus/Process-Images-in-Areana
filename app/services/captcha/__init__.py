"""Captcha detection/solving service package (2Captcha integration).

Layer: services — imports browser (probe builders) and core only; the
browser layer never imports this package. Call sites route through
`service.handle_captcha` (the choke point, RULE 9 fail-open).
"""

from .signals import CaptchaSignal, SolveOutcome
from .key_store import CaptchaKeyStore, CaptchaSettings
from .stats import CaptchaStatsStore
from .api_client import Captcha2Client, ApiError
from .solver import CaptchaSolver
from .service import CaptchaCtx, CaptchaService, handle_captcha
from .recovery import ResumePolicy, arm_resume, clear_resume, maybe_resume, note_settle
from .sdk_client import SdkConfig, SdkSolver
from .watcher_gate import CaptchaGate, current_gate, install_gate, is_solving_enabled

__all__ = [
    "CaptchaSignal",
    "SolveOutcome",
    "CaptchaKeyStore",
    "CaptchaSettings",
    "CaptchaStatsStore",
    "Captcha2Client",
    "ApiError",
    "CaptchaSolver",
    "CaptchaCtx",
    "CaptchaService",
    "handle_captcha",
    "ResumePolicy",
    "arm_resume",
    "clear_resume",
    "maybe_resume",
    "note_settle",
    # REFACTOR 02 — the watcher-only captcha path (gate + SDK adapter)
    "SdkConfig",
    "SdkSolver",
    "CaptchaGate",
    "current_gate",
    "install_gate",
    "is_solving_enabled",
]
