"""Pre-emptive 2Captcha task creation (warm-up) for CaptchaSolver.

Starts createTask the moment a challenge is detected so the provider's
solve latency overlaps the app's own setup (recording, report, probes).
The task is consumed by the next solve on the same tab, or deleted
(credit hygiene) when abandoned. TTL + sitekey checks discard warm tasks
that no longer match the live challenge.

No Qt, no browser imports (services layer; direction: solver → warm → api_client).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

from .api_client import Captcha2Client
from .signals import CaptchaSignal, host_of

WARM_TTL_SEC = 30.0  # a warm task older than this is stale (page may have moved on)

_TASK_TYPES = {
    "recaptcha_enterprise": "RecaptchaV2EnterpriseTaskProxyless",
    "recaptcha_v2": "RecaptchaV2TaskProxyless",
}


def task_type_for(kind: str) -> str:
    return _TASK_TYPES.get(kind, _TASK_TYPES["recaptcha_v2"])


def task_payload(task_type: str, signal: CaptchaSignal) -> Dict[str, Any]:
    """Docs-exact createTask payload (2captcha.com/api-docs/recaptcha-v2-enterprise)."""
    payload = {"type": task_type,
               "websiteURL": signal.page_url,
               "websiteKey": signal.sitekey}
    if task_type.startswith("RecaptchaV2Enterprise"):
        payload["isInvisible"] = signal.is_invisible  # true = no visible checkbox
    return payload


@dataclass
class WarmTask:
    """One in-flight provider task: createTask may still be running."""
    client: Captcha2Client
    creating: asyncio.Task  # resolves to the provider task_id
    sitekey: str
    created_at: float


class WarmTaskPool:
    """One pre-started 2Captcha task per tab; consumed or deleted, never leaked."""

    def __init__(self, keys: Any, stats: Any, log: Callable[[str, str], None],
                 client_factory: Any = Captcha2Client):
        self._keys = keys
        self._stats = stats
        self._log = log
        self._client_factory = client_factory  # injectable for RULE 8 fakes
        self._warm: Dict[str, WarmTask] = {}

    def start(self, tab_id: str, signal: CaptchaSignal) -> bool:
        """Fire createTask in the background; False when skipped (no key / already warm)."""
        if tab_id in self._warm or not signal.sitekey:
            return False
        settings = self._keys.load()
        if not settings.api_key:
            return False
        payload = task_payload(task_type_for(signal.kind), signal)
        client = self._client_factory(settings.api_key)
        creating = asyncio.create_task(client.create_task(payload))
        self._warm[tab_id] = WarmTask(client=client, creating=creating,
                                      sitekey=signal.sitekey, created_at=time.monotonic())
        self._stats.record("task_created", host_of(signal.page_url))
        self._log(f"🤖 2Captcha task pre-started (warm, tab {str(tab_id)[:12]})", "info")
        return True

    async def take(self, tab_id: str,
                   signal: CaptchaSignal) -> Optional[Tuple[Captcha2Client, str]]:
        """Consume the warm task; None when absent, stale, or creation failed."""
        warm = self._warm.pop(tab_id, None)
        if warm is None:
            return None
        try:
            task_id = await warm.creating
        except Exception as exc:
            await self._close(warm.client)
            self._log(f"🤖 warm createTask failed: {exc}", "warn")
            return None
        if self._stale(warm, signal):
            await self._abandon(warm.client, task_id)
            return None
        self._log(f"🤖 warm task #{task_id} consumed (saved the createTask roundtrip)", "info")
        return warm.client, task_id

    async def discard(self, tab_id: str) -> None:
        """Delete an unconsumed warm task so it can never bill (credit hygiene)."""
        warm = self._warm.pop(tab_id, None)
        if warm is None:
            return
        try:
            task_id = await warm.creating
        except Exception:
            await self._close(warm.client)
            return
        await self._abandon(warm.client, task_id)

    def _stale(self, warm: WarmTask, signal: CaptchaSignal) -> bool:
        """Older than the TTL or the challenge's sitekey changed meanwhile."""
        aged = time.monotonic() - warm.created_at > WARM_TTL_SEC
        return aged or warm.sitekey != signal.sitekey

    async def _abandon(self, client: Captcha2Client, task_id: str) -> None:
        try:
            await client.delete_task(task_id)
        except Exception:
            pass  # deletion is credit hygiene, never fatal
        await self._close(client)

    async def _close(self, client: Captcha2Client) -> None:
        try:
            await client.aclose()
        except Exception:
            pass
