"""2Captcha API v2 client — https://2captcha.com/api-docs

JSON API: clientKey travels in the POST body (never in a URL, never in a
log line). Only api.2captcha.com is ever contacted (RULE 20).
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import aiohttp

API_BASE = "https://api.2captcha.com"
POLL_INTERVAL_SEC = 5.0  # docs-recommended getTaskResult cadence

# 2captcha errorId → short reason (https://2captcha.com/api-docs/create-task)
_ERROR_REASONS = {
    1: "unavailable",        # CAPTCHA_UNAVAILABLE
    2: "bad_key",            # KEY_DOESNT_EXIST
    3: "no_credit",          # NOT_ENOUGH_CREDIT
    16: "not_found",         # TASK_NOT_FOUND
}


class ApiError(Exception):
    """Classified 2Captcha failure; .reason is a stable short token."""

    def __init__(self, reason: str, error_id: Optional[int] = None, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason  # unavailable|bad_key|no_credit|not_found|task_error|network
        self.error_id = error_id


def error_reason(error_id: Any) -> str:
    """Map a 2Captcha errorId to a stable reason token."""
    try:
        return _ERROR_REASONS.get(int(error_id), "task_error")
    except (TypeError, ValueError):
        return "task_error"


class Captcha2Client:
    """Thin async client; one shared session, closed via aclose()."""

    def __init__(self, key: str, timeout_sec: float = 30.0):
        self._key = key
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
        url = f"{API_BASE}/{method}"
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
            raise ApiError(error_reason(err), error_id=int(err),
                           message=str(data.get("errorCode", "")))
        return data

    async def create_task(self, task: Dict[str, Any]) -> str:
        """Submit a solve task; returns the taskId string."""
        data = await self._post("createTask", {"task": task})
        task_id = data.get("taskId")
        if not task_id:
            raise ApiError("task_error", message="createTask returned no taskId")
        return str(task_id)

    async def get_result(self, task_id: str) -> Dict[str, Any]:
        """One getTaskResult poll: status processing|ready|failed + solution."""
        return await self._post("getTaskResult", {"taskId": task_id})

    async def get_balance(self) -> float:
        data = await self._post("getBalance", {})
        try:
            return float(data.get("balance", 0.0))
        except (TypeError, ValueError):
            return 0.0

    async def delete_task(self, task_id: str) -> bool:
        """Free credit on an abandoned task; True when it is gone."""
        try:
            await self._post("deleteTask", {"taskId": task_id})
            return True
        except ApiError as e:
            return e.reason == "not_found"
