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
from .recovery import ResumePolicy, arm_resume, clear_resume, maybe_resume, note_settle

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
    "arm_resume",
    "clear_resume",
    "maybe_resume",
    "note_settle",
]
