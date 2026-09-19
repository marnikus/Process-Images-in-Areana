"""Watcher-only CAPTCHA integration using the official 2Captcha SDK.

This module is the only production owner of CAPTCHA solving. It has no image
job, submit, download, or generation-recovery imports. The synchronous
``2captcha-python`` SDK runs in a worker thread so the watcher loop remains
responsive; token material never enters logs or returned status.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Optional

from app.browser.captcha_probes import build_inject_js
from app.services.captcha.key_store import CaptchaKeyStore, CaptchaSettings, clamp_timeout
from app.services.captcha.signals import CaptchaSignal, SolveOutcome, host_of
from app.services.captcha.stats import CaptchaStatsStore
from app.services.captcha_recording import RecordingManager

try:
    from twocaptcha import TwoCaptcha
except ImportError:  # optional dependency; manual fallback remains available
    TwoCaptcha = None


@dataclass
class WatcherCaptchaResult:
    """Small result returned to Watcher handlers; token is deliberately absent."""

    status: str
    reason: str = ""
    method: str = "watcher"


@dataclass
class _SolveRequest:
    """Inputs shared by one per-tab SDK task."""

    cdp: Any
    tab_id: str
    signal: CaptchaSignal
    stop: Callable[[], bool]


def _token_from_sdk(value: Any) -> str:
    """Normalize SDK string/extended-response results without logging tokens."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("code", "gRecaptchaResponse", "token"):
            token = value.get(key)
            if token:
                return str(token).strip()
    return ""


def _sdk_solver(settings: CaptchaSettings):
    """Build the official SDK client, or return None when it is unavailable."""
    if TwoCaptcha is None or not settings.api_key:
        return None
    options = {
        "defaultTimeout": settings.solve_timeout_sec,
        "pollingInterval": 5,
        "extendedResponse": True,
    }
    try:
        return TwoCaptcha(settings.api_key, **options)
    except TypeError:
        return TwoCaptcha(settings.api_key)


def _sdk_call(client: Any, signal: CaptchaSignal) -> Any:
    """Submit one visible page signal through the SDK's recaptcha helper."""
    kwargs = {"sitekey": signal.sitekey, "url": signal.page_url}
    if signal.kind == "recaptcha_enterprise":
        kwargs["enterprise"] = 1
    return client.recaptcha(**kwargs)


class WatcherCaptchaSolver:
    """Per-page solver used exclusively by the enabled Watcher."""

    def __init__(self, config_dir: str, log: Callable[[str, str], None]):
        self.keys = CaptchaKeyStore(config_dir)
        self.stats = CaptchaStatsStore(config_dir)
        self._log = log
        self._inflight: dict[str, asyncio.Task] = {}

    def enabled(self) -> bool:
        """Return true only when the user enabled the provider and stored a key."""
        settings = self.keys.load()
        return bool(settings.enabled and settings.api_key and TwoCaptcha is not None)

    async def solve(self, request: _SolveRequest) -> WatcherCaptchaResult:
        """Deduplicate concurrent solves for one page/tab."""
        current = self._inflight.get(request.tab_id)
        if current is not None and not current.done():
            return await current
        task = asyncio.create_task(self._solve_once(request))
        self._inflight[request.tab_id] = task
        try:
            return await task
        finally:
            self._inflight.pop(request.tab_id, None)

    async def _solve_once(self, request: _SolveRequest) -> WatcherCaptchaResult:
        """Validate the signal, call the official SDK, and inject its result."""
        if request.stop():
            return WatcherCaptchaResult("stopped", "stop requested")
        settings = self.keys.load()
        client = _sdk_solver(settings)
        if client is None:
            return WatcherCaptchaResult("manual", "2Captcha SDK or key unavailable")
        self.stats.record("detected", host_of(request.signal.page_url))
        try:
            response = await asyncio.to_thread(_sdk_call, client, request.signal)
            token = _token_from_sdk(response)
            if not token:
                raise RuntimeError("SDK returned no token")
            if request.stop():
                return WatcherCaptchaResult("stopped", "stop requested after provider result")
            return await self._inject(request, token)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.stats.record("auto_failed", host_of(request.signal.page_url))
            self.stats.set_last_error(type(exc).__name__)
            self._log(f"Watcher 2Captcha solve failed: {type(exc).__name__}", "warn")
            return WatcherCaptchaResult("manual", "provider or injection failure")

    async def _inject(self, request: _SolveRequest, token: str) -> WatcherCaptchaResult:
        """Inject only through the Watcher CDP controller; token is not retained."""
        try:
            raw = await request.cdp.cdp.evaluate(
                build_inject_js(token, request.signal.sitekey))
            if not _injection_ok(raw):
                raise RuntimeError("page rejected token")
            self.stats.record("auto_solved", host_of(request.signal.page_url))
            self._log(f"Watcher solved CAPTCHA on page {request.tab_id[:12]}", "success")
            return WatcherCaptchaResult("solved")
        except Exception:
            self.stats.record("auto_failed", host_of(request.signal.page_url))
            return WatcherCaptchaResult("manual", "page did not accept token")


def _injection_ok(value: Any) -> bool:
    """Accept the JSON/string result shapes produced by the page probe."""
    if isinstance(value, str):
        try:
            import json
            value = json.loads(value)
        except Exception:
            return False
    return isinstance(value, dict) and bool(value.get("ok"))


class WatcherCaptchaService:
    """Settings, stats, recordings, and the Watcher-only solver facade."""

    def __init__(self, config_dir: str, log: Optional[Callable[[str, str], None]] = None):
        self._log = log or (lambda _msg, _level="info": None)
        self.keys = CaptchaKeyStore(config_dir)
        self.solver = WatcherCaptchaSolver(config_dir, self._log)
        self.stats = self.solver.stats
        self.recordings = RecordingManager(config_dir, self._log)

    def apply_settings(self, api_key: str, enabled: bool, timeout: int) -> dict:
        """Persist only Watcher provider settings and return masked status."""
        key = str(api_key or "").strip()
        settings = CaptchaSettings(enabled=bool(enabled and key), api_key=key,
                                   solve_timeout_sec=clamp_timeout(timeout))
        self.keys.save(settings)
        return {"ok": True, "enabled": settings.enabled, "has_key": bool(key),
                "masked_key": CaptchaKeyStore.mask(key),
                "solve_timeout_sec": settings.solve_timeout_sec}

    def status_payload(self) -> dict:
        """WebChannel-safe settings/status payload; never returns the raw key."""
        settings = self.keys.load()
        return {"enabled": settings.enabled, "has_key": bool(settings.api_key),
                "masked_key": CaptchaKeyStore.mask(settings.api_key),
                "solve_timeout_sec": settings.solve_timeout_sec,
                "balance": self.stats.last_balance, "balance_at": self.stats.balance_at,
                "last_error": self.stats.last_error, "provider": "2captcha-python"}

    def stats_payload(self) -> dict:
        """Return local counters used by the Watcher status surface."""
        return self.stats.to_dict()

    async def refresh_balance(self) -> Optional[float]:
        """Fetch balance through the official SDK without blocking Qt/asyncio."""
        settings = self.keys.load()
        client = _sdk_solver(settings)
        if client is None or not hasattr(client, "balance"):
            return None
        try:
            value = await asyncio.to_thread(client.balance)
            balance = float(value.get("balance", value) if isinstance(value, dict) else value)
            self.stats.set_balance(balance)
            return balance
        except Exception as exc:
            self.stats.set_last_error(type(exc).__name__)
            self._log(f"Watcher 2Captcha balance failed: {type(exc).__name__}", "warn")
            return None


def build_request(cdp: Any, tab_id: str, signal: CaptchaSignal,
                  stop: Optional[Callable[[], bool]] = None) -> _SolveRequest:
    """Create a bounded solver request for one Watcher page."""
    return _SolveRequest(cdp=cdp, tab_id=str(tab_id or "page"), signal=signal,
                         stop=stop or (lambda: False))


__all__ = [
    "WatcherCaptchaResult", "WatcherCaptchaService", "WatcherCaptchaSolver",
    "build_request",
]
