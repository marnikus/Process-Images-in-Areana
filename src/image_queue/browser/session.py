"""Adapt retained CdpService discovery/connect separation, exact target policy and lease.

Readiness deliberately remains unsupported until the image-page adapter is reviewed.
No persistent target IDs, auto navigation, browser closing, or reconnect/replay.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

from image_queue.browser.discovery import fetch_tabs
from image_queue.browser.lease import CdpLease
from image_queue.browser.transport import CDPClient
from image_queue.domain.connections import PageTarget, match_open_tabs
from image_queue.domain.settings import ConnectionPreset
from image_queue.domain.validation import ContractError


class ChromeSession:
    def __init__(self, preset: ConnectionPreset) -> None:
        self.preset = preset
        self.client = CDPClient(preset.endpoint)
        self.client.on_event = self._event
        self.client.on_disconnect = self._invalidate
        self.lease = CdpLease()
        self.active: str | None = None
        self.status: dict[str, Any] = {}
        self.generation = 0

    def _invalidate(self) -> None:
        self.generation += 1
        if self.active in self.status:
            self.status[self.active]["connection"] = "disconnected"
            self.status[self.active]["readiness"] = "unchecked"
        self.active = None

    def _event(self, frame: dict[str, Any]) -> None:
        if frame["method"] in (
            "Page.frameNavigated",
            "Page.navigatedWithinDocument",
            "Page.frameStartedLoading",
            "Runtime.executionContextsCleared",
            "Runtime.executionContextDestroyed",
            "Inspector.detached",
        ):
            self._invalidate()

    async def discover(self) -> dict[str, Any]:
        async with self.lease:
            await self.client.disconnect()
            tabs = await fetch_tabs(self.preset.endpoint)
            self.status = self._matches(tabs)
            return self.status

    def _matches(self, tabs: list[dict[str, Any]]) -> dict[str, Any]:
        targets = tuple(PageTarget(tab["id"], tab["url"]) for tab in tabs)
        result = {}
        for row in self.preset.urls:
            match = match_open_tabs(row, targets)
            result[row.row_id] = {
                "discovery": match.status.value,
                "connection": "not_attached",
                "verified_at": self.status.get(row.row_id, {}).get("verified_at"),
                "readiness": "unchecked",
                "candidates": [
                    {key: tab[key] for key in ("id", "url", "title")}
                    for tab in tabs
                    if tab["id"] in match.target_ids
                ],
            }
        return result

    async def check(self, row_id: str, target_id: str) -> dict[str, Any]:
        async with self.lease:
            async with asyncio.timeout(10):
                return await self._check(row_id, target_id)

    async def _check(self, row_id: str, target_id: str) -> dict[str, Any]:
        row = next((row for row in self.preset.urls if row.row_id == row_id and row.enabled), None)
        if row is None:
            raise ContractError("Choose an enabled URL row")
        await self.client.disconnect()
        tabs = await fetch_tabs(self.preset.endpoint)
        self.status = self._matches(tabs)
        tab = self._chosen(row_id, target_id, tabs)
        try:
            await self.client.connect(tab["webSocketDebuggerUrl"])
            generation = self.generation
            await self._verify(row.exact_url, target_id)
            if generation != self.generation:
                raise ContractError("Page context changed during verification; recheck")
            self.active = row_id
            self.status[row_id].update(
                connection="connected",
                readiness="adapter_not_verified",
                verified_at=datetime.now(UTC).isoformat(),
            )
            return self.status
        except (ContractError, TimeoutError, asyncio.CancelledError):
            await self.client.disconnect()
            raise

    def _chosen(self, row_id: str, target_id: str, tabs: list[dict[str, Any]]) -> dict[str, Any]:
        candidates = self.status[row_id]["candidates"]
        tab = next((tab for tab in tabs if tab["id"] == target_id), None)
        if tab is None or target_id not in [item["id"] for item in candidates]:
            raise ContractError("Target changed or ambiguous; rediscover and choose an exact tab")
        return tab

    async def _verify(self, exact_url: str, target_id: str) -> None:
        identity = await self.client.send("Target.getTargetInfo")
        info = _object(identity, ("result", "targetInfo"))
        if info.get("targetId") != target_id or info.get("url") != exact_url:
            raise ContractError("Target identity/URL mismatch")
        response = await self.client.send(
            "Runtime.evaluate",
            {
                "expression": "({url:location.href, state:document.readyState})",
                "returnByValue": True,
                "awaitPromise": False,
            },
        )
        result = _object(response, ("result",))
        value = _object(result, ("result", "value"))
        if result.get("exceptionDetails") or not isinstance(value, dict):
            raise ContractError("Page verification failed")
        if value.get("url") != exact_url or value.get("state") != "complete":
            raise ContractError("Page redirected or is still loading; no action authorized")

    async def close(self) -> None:
        async with self.lease:
            await self.client.disconnect()


def _object(data: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    for name in path:
        value = data.get(name)
        if not isinstance(value, dict):
            raise ContractError("Malformed Chrome verification response")
        data = value
    return data
