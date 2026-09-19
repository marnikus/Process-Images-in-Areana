# ideal-size: ~170 lines reason=single adapter around the official SDK; the
# payload builders and the error map always change together (RULE 18.2)
"""2Captcha solving via the **official Python SDK** (`2captcha-python`).

Replaces the hand-rolled HTTP layer (`api_client.py` + the transport half of
`solver.py`, ~1 100 LOC) with the vendor SDK:

    pip install 2captcha-python      # https://github.com/2captcha/2captcha-python
    from twocaptcha import TwoCaptcha

Layer rules
-----------
* services layer: imports SDK + `.signals` only — never Qt, never `browser`.
* This module *never* decides **whether** to solve. That is
  `watcher_gate.solve_if_watcher_on()`. Here we only know **how**.
* Network egress is limited to the SDK (api.2captcha.com) — RULE 20.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .signals import CaptchaSignal, SolveOutcome

log = logging.getLogger("captcha.sdk")

# Import is lazy-safe: the app must still boot (and the Watcher must still
# report "solver unavailable") when the optional dependency is absent.
try:  # pragma: no cover - import shape only
    from twocaptcha import TwoCaptcha
    from twocaptcha.solver import (
        ApiException,
        NetworkException,
        TimeoutException,
        ValidationException,
    )
    SDK_AVAILABLE = True
except ImportError:  # pragma: no cover
    TwoCaptcha = None  # type: ignore[assignment]
    ApiException = NetworkException = TimeoutException = ValidationException = Exception
    SDK_AVAILABLE = False

SDK_HINT = "pip install 2captcha-python"


@dataclass(frozen=True)
class SdkConfig:
    """Everything the SDK constructor needs, read from the key store."""

    api_key: str
    timeout_sec: int = 180
    polling_interval_sec: int = 5
    soft_id: int = 0

    def as_kwargs(self) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "apiKey": self.api_key,
            "defaultTimeout": self.timeout_sec,
            "pollingInterval": self.polling_interval_sec,
        }
        if self.soft_id:
            kwargs["softId"] = self.soft_id
        return kwargs


def _recaptcha_kwargs(sig: CaptchaSignal) -> Dict[str, Any]:
    """`solver.recaptcha(...)` arguments for v2 / v2-enterprise / v3."""
    kwargs: Dict[str, Any] = {"sitekey": sig.sitekey, "url": sig.page_url}
    if sig.enterprise:
        kwargs["enterprise"] = 1
    if sig.invisible:
        kwargs["invisible"] = 1
    if sig.action:
        kwargs["action"] = sig.action
    if sig.kind == "recaptcha_v3":
        kwargs["version"] = "v3"
        kwargs["min_score"] = sig.min_score or 0.7
    if sig.data_s:
        kwargs["datas"] = sig.data_s
    return kwargs


# One row per supported captcha family: kind -> (SDK method, kwargs builder).
_DISPATCH = {
    "recaptcha_v2": ("recaptcha", _recaptcha_kwargs),
    "recaptcha_v3": ("recaptcha", _recaptcha_kwargs),
    "recaptcha_enterprise": ("recaptcha", _recaptcha_kwargs),
    "hcaptcha": ("hcaptcha", lambda s: {"sitekey": s.sitekey, "url": s.page_url}),
    "turnstile": ("turnstile", lambda s: {"sitekey": s.sitekey, "url": s.page_url}),
}

# SDK exception -> (short reason, retryable?) — keeps call sites branch-free.
_ERRORS = (
    (ValidationException, "bad_request", False),
    (NetworkException, "network", True),
    (TimeoutException, "timeout", True),
    (ApiException, "api_error", True),
)


def _classify(exc: Exception) -> tuple[str, bool]:
    for exc_type, reason, retryable in _ERRORS:
        if isinstance(exc, exc_type):
            return reason, retryable
    return "unexpected", False


class SdkSolver:
    """Thin, synchronous adapter. Run it off the UI thread (Watcher loop)."""

    def __init__(self, config: SdkConfig, logger=None):
        self.config = config
        self._log = logger or (lambda msg, level="info": log.info(msg))
        self._solver = None

    # ---- lifecycle -----------------------------------------------------
    def available(self) -> tuple[bool, str]:
        """(usable, reason) — checked before every solve, never raises."""
        if not SDK_AVAILABLE:
            return False, f"2captcha SDK missing — {SDK_HINT}"
        if not (self.config.api_key or "").strip():
            return False, "no 2captcha API key configured"
        return True, ""

    def _client(self):
        if self._solver is None:
            self._solver = TwoCaptcha(**self.config.as_kwargs())
        return self._solver

    def balance(self) -> Optional[float]:
        ok, _ = self.available()
        if not ok:
            return None
        try:
            return float(self._client().balance())
        except Exception as exc:  # noqa: BLE001 - reporting only
            self._log(f"2captcha balance failed: {exc}", "warn")
            return None

    # ---- solving -------------------------------------------------------
    def solve(self, sig: CaptchaSignal) -> SolveOutcome:
        """Blocking solve of one signal. Always returns, never raises."""
        ok, reason = self.available()
        if not ok:
            return SolveOutcome(ok=False, reason=reason, retryable=False)
        entry = _DISPATCH.get(sig.kind)
        if entry is None:
            return SolveOutcome(ok=False, reason=f"unsupported kind {sig.kind}",
                                retryable=False)
        method_name, build = entry
        try:
            result = getattr(self._client(), method_name)(**build(sig))
        except Exception as exc:  # noqa: BLE001 - mapped below
            short, retryable = _classify(exc)
            self._log(f"2captcha {sig.kind} failed ({short}): {exc}", "error")
            return SolveOutcome(ok=False, reason=short, retryable=retryable)
        token = (result or {}).get("code", "")
        if not token:
            return SolveOutcome(ok=False, reason="empty token", retryable=True)
        return SolveOutcome(ok=True, token=token, task_id=str((result or {}).get("captchaId", "")))

    def report(self, task_id: str, good: bool) -> None:
        """Feedback loop — improves worker quality and refunds bad solves."""
        if not task_id:
            return
        try:
            self._client().report(task_id, good)
        except Exception as exc:  # noqa: BLE001 - best effort
            self._log(f"2captcha report skipped: {exc}", "warn")
