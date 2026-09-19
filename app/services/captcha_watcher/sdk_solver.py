"""SdkSolver — thin wrapper over the official 2Captcha SDK (`2captcha-python`).

This is the ONLY place in the app that talks to a captcha-solving service.
No hand-rolled HTTP client, no polling loop of our own: `AsyncTwoCaptcha`
submits the task, polls and returns the token.

* Lazy import: the SDK is optional (requirements.txt lists it, but the app
  boots and processes images without it — the Watcher then reports
  `sdk_available=False` and never attempts a solve).
* Fail-open (RULE 9): every failure becomes a `SolveResult(ok=False, error=…)`;
  nothing raises into the watcher loop.
* RULE 20: the API key never appears in logs or results; tokens are only
  ever counted, never printed.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Optional

from .signals import CaptchaSignal, SolveResult

DEFAULT_SOLVE_TIMEOUT_SEC = 180
POLL_INTERVAL_SEC = 5
SDK_MISSING_ERROR = "2captcha-python not installed (pip install 2captcha-python)"


def _import_sdk() -> Optional[Any]:
    """The `twocaptcha` module or None when the SDK is not installed."""
    try:
        import twocaptcha  # noqa: WPS433 — optional dependency, imported lazily
        return twocaptcha
    except Exception:
        return None


def sdk_available() -> bool:
    return _import_sdk() is not None


def _default_factory(api_key: str, timeout_sec: int) -> Any:
    """Real SDK client; raises ImportError-like when the package is missing."""
    sdk = _import_sdk()
    if sdk is None:
        raise RuntimeError(SDK_MISSING_ERROR)
    return sdk.AsyncTwoCaptcha(api_key, defaultTimeout=timeout_sec,
                               recaptchaTimeout=timeout_sec, pollingInterval=POLL_INTERVAL_SEC)


def _error_text(exc: BaseException) -> str:
    """Short, key-free error label (SDK exceptions carry no secrets, but keep it terse)."""
    text = f"{type(exc).__name__}: {exc}".strip()
    return text[:200]


def _token_of(result: Any) -> str:
    """SDK returns {'captchaId': id, 'code': token} (dict) — tolerate a bare string."""
    if isinstance(result, dict):
        return str(result.get("code") or "")
    return str(result or "")


def _task_id_of(result: Any) -> str:
    if isinstance(result, dict):
        return str(result.get("captchaId") or "")
    return ""


class SdkSolver:
    """One solver per API key; stateless between calls (safe to share)."""

    def __init__(self, api_key: str, timeout_sec: int = DEFAULT_SOLVE_TIMEOUT_SEC,
                 client_factory: Optional[Callable[[str, int], Any]] = None):
        self._api_key = (api_key or "").strip()
        self._timeout = max(30, int(timeout_sec or DEFAULT_SOLVE_TIMEOUT_SEC))
        self._factory = client_factory or _default_factory

    @property
    def has_key(self) -> bool:
        return bool(self._api_key)

    def _client(self) -> Any:
        return self._factory(self._api_key, self._timeout)

    async def solve(self, signal: CaptchaSignal) -> SolveResult:
        """Submit one recaptcha task; never raises."""
        started = time.monotonic()
        if not self.has_key:
            return SolveResult(ok=False, error="no api key")
        if not signal.solvable:
            return SolveResult(ok=False, error=f"unsolvable signal kind={signal.kind or '?'}")
        try:
            client = self._client()
            result = await asyncio.wait_for(
                client.recaptcha(sitekey=signal.sitekey, url=signal.page_url, version="v2",
                                 enterprise=1 if signal.kind == "recaptcha_enterprise" else 0,
                                 invisible=1 if signal.invisible else 0),
                timeout=self._timeout + 30)
        except Exception as exc:  # ApiException / NetworkException / TimeoutException / RuntimeError
            return SolveResult(ok=False, error=_error_text(exc),
                               elapsed_s=time.monotonic() - started)
        token = _token_of(result)
        if not token:
            return SolveResult(ok=False, error="empty token from SDK", task_id=_task_id_of(result),
                               elapsed_s=time.monotonic() - started)
        return SolveResult(ok=True, token=token, task_id=_task_id_of(result),
                           elapsed_s=time.monotonic() - started)

    async def balance(self) -> Optional[float]:
        """Account balance in USD, or None on any failure (never raises)."""
        if not self.has_key:
            return None
        try:
            return float(await self._client().balance())
        except Exception:
            return None
