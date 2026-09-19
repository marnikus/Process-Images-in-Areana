"""Captcha Watcher — the ONLY captcha-solving mechanic in the app.

Isolation contract (docs/archive/2026-10-02-captcha-watcher-isolation/design.md):

* Solving lives here and nowhere else. The job pipeline (single_job_runner,
  batch orchestrator, dispatchers) never solves a captcha — it only detects
  the dialog, pauses and waits for it to clear (RULE 20 manual default).
* Watcher ON  → this loop scans the app-owned pages every TICK_SEC and solves
  visible reCAPTCHA challenges through the official 2Captcha SDK
  (pip `2captcha-python`, imported lazily — the app runs without it).
* Watcher OFF → the app processes images only; any captcha is the user's
  own business (or a manual solve in Chrome).

Public surface (used by app/ui/panels/watcher_solver.py):
    CaptchaWatcher, WatcherDeps, SdkSolver, CaptchaSignal, SolveResult,
    WatcherStatus
"""

from .sdk_solver import SdkSolver
from .signals import CaptchaSignal, SolveResult, WatcherStatus
from .watcher import EVAL_TIMEOUT_SEC, MAX_SOLVE_ATTEMPTS, TICK_SEC, CaptchaWatcher, WatcherDeps

__all__ = [
    "CaptchaSignal",
    "CaptchaWatcher",
    "EVAL_TIMEOUT_SEC",
    "MAX_SOLVE_ATTEMPTS",
    "SdkSolver",
    "SolveResult",
    "TICK_SEC",
    "WatcherDeps",
    "WatcherStatus",
]
