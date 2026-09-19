"""Captcha OBSERVATION package for the job pipeline (detect → wait → penalty).

Layer: services — imports browser (probe builders) and core only; the
browser layer never imports this package. Pipeline call sites route through
`service.handle_captcha` (the choke point, RULE 9 fail-open).

This package does NOT solve captchas. Since the 2026-10-02 isolation the
2Captcha HTTP client + solver that used to live here are gone; the app's
only solver is `app.services.captcha_watcher` (official SDK, Watcher ON).
"""

from .signals import CaptchaSignal, SolveOutcome
from .key_store import CaptchaKeyStore, CaptchaSettings
from .stats import CaptchaStatsStore
from .service import CaptchaCtx, CaptchaService, handle_captcha
from .recovery import ResumePolicy, arm_resume, clear_resume, maybe_resume, note_settle

__all__ = [
    "CaptchaSignal",
    "SolveOutcome",
    "CaptchaKeyStore",
    "CaptchaSettings",
    "CaptchaStatsStore",
    "CaptchaCtx",
    "CaptchaService",
    "handle_captcha",
    "ResumePolicy",
    "arm_resume",
    "clear_resume",
    "maybe_resume",
    "note_settle",
]
