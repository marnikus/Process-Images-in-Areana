"""Captcha detection/solving service package (solver providers: 2Captcha,
CapMonster Cloud).

Layer: services — imports browser (probe builders) and core only; the
browser layer never imports this package. Call sites route through
`service.handle_captcha` (the choke point, RULE 9 fail-open).
"""

from .signals import CaptchaSignal, SolveOutcome
from .key_store import CaptchaKeyStore, CaptchaSettings, ProviderCreds
from .stats import CaptchaStatsStore
from .api_client import SolverApiClient, ApiError
from .providers import DEFAULT_PROVIDER, PROVIDERS, ProviderSpec, provider_for
from .solver import CaptchaSolver
from .service import CaptchaCtx, CaptchaService, handle_captcha
from .recovery import (
    InlineWaitGates, ResumePolicy, arm_resume, arm_wait_gates, clear_resume,
    disarm_wait_gates, maybe_resume, note_settle, wait_with_gates,
)

__all__ = [
    "CaptchaSignal",
    "SolveOutcome",
    "CaptchaKeyStore",
    "CaptchaSettings",
    "ProviderCreds",
    "CaptchaStatsStore",
    "SolverApiClient",
    "ApiError",
    "DEFAULT_PROVIDER",
    "PROVIDERS",
    "ProviderSpec",
    "provider_for",
    "CaptchaSolver",
    "CaptchaCtx",
    "CaptchaService",
    "handle_captcha",
    "ResumePolicy",
    "InlineWaitGates",
    "arm_resume",
    "arm_wait_gates",
    "clear_resume",
    "disarm_wait_gates",
    "maybe_resume",
    "note_settle",
    "wait_with_gates",
]
