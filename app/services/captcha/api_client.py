"""Solver API client — one shared JSON protocol, two providers.

Wire contract per provider docs (2captcha.com/api-docs, docs.capmonster.cloud):
`clientKey` travels in the POST body (never in a URL, never in a log line);
only the selected provider's official api host is ever contacted (RULE 20).
Every per-provider difference (base URL, error classification, refund support)
comes from the ProviderSpec — this file stays protocol-shaped.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import aiohttp

from .providers import DEFAULT_PROVIDER, ProviderSpec, provider_for

DEFAULT_POLL_INTERVAL_SEC = 5.0  # report default before the provider is known


class ApiError(Exception):
    """Classified provider failure; .reason is a stable short token.

    Reasons: unavailable|bad_key|no_credit|not_found|task_error|network and
    capmonster's `pending` (still solving — converted by get_result).
    """

    def __init__(self, reason: str, error_id: Optional[int] = None, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason
        self.error_id = error_id


class SolverApiClient:
    """Thin async client for one provider spec; one shared session, closed via aclose()."""

    def __init__(self, key: str, spec: Optional[ProviderSpec] = None,
                 timeout_sec: float = 30.0):
        self._key = key
        self.spec = spec or provider_for(DEFAULT_PROVIDER)
        self._timeout = aiohttp.ClientTimeout(total=timeout_sec)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def aclose(self) -> None:
        try:
            if self._session is not None and not self._session.closed:
                await self._session.close()
        finally:
            self._session = None

    async def _post(self, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        session = await self._ensure_session()
        url = f"{self.spec.api_base}/{method}"
        body = {"clientKey": self._key, **payload}
        try:
            async with session.post(url, json=body) as resp:
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, json.JSONDecodeError, ValueError) as e:
            raise ApiError("network", message=str(e))
        if not isinstance(data, dict):
            raise ApiError("network", message="non-JSON response")
        err = data.get("errorId", 0)
        if err != 0:
            code = data.get("errorCode")
            raise ApiError(self.spec.error_reason(err, code),
                           error_id=err if isinstance(err, int) else None,
                           message=str(code or data.get("errorDescription") or ""))
        return data

    async def create_task(self, task: Dict[str, Any]) -> Any:
        """Submit a solve task; returns the provider's raw taskId (str or int)."""
        data = await self._post("createTask", {"task": task})
        task_id = data.get("taskId")
        if task_id is None or task_id == "":
            raise ApiError("task_error", message="createTask returned no taskId")
        return task_id  # echoed back untouched — CapMonster ids are integers

    async def get_result(self, task_id: Any) -> Dict[str, Any]:
        """One getTaskResult poll; a provider `pending` error reads as processing."""
        try:
            return await self._post("getTaskResult", {"taskId": task_id})
        except ApiError as e:
            if e.reason == "pending":
                return {"status": "processing"}
            raise

    async def get_balance(self) -> float:
        data = await self._post("getBalance", {})
        try:
            return float(data.get("balance", 0.0))
        except (TypeError, ValueError):
            return 0.0

    async def delete_task(self, task_id: Any) -> bool:
        """Refund an abandoned task; providers without deleteTask are no-ops."""
        if not self.spec.can_delete:
            return False
        try:
            await self._post("deleteTask", {"taskId": task_id})
            return True
        except ApiError as e:
            return e.reason == "not_found"
