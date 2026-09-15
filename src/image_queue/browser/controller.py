"""One persistent asyncio loop for the retained socket; called from the Qt command worker."""

import asyncio
from copy import deepcopy
from threading import Thread
from typing import Any

from image_queue.browser.session import ChromeSession
from image_queue.domain.presets import loads_preset
from image_queue.domain.validation import ContractError


class ChromeController:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = Thread(target=self.loop.run_forever, daemon=True, name="ImageQueueCDP")
        self.thread.start()
        self.session: ChromeSession | None = None

    def execute(self, request: dict[str, Any], connection: str) -> dict[str, Any]:
        future = asyncio.run_coroutine_threadsafe(self._execute(request, connection), self.loop)
        try:
            return future.result(timeout=13)
        except TimeoutError as exc:
            future.cancel()
            raise ContractError("Chrome check timed out; reconnect explicitly") from exc

    async def _execute(self, request: dict[str, Any], connection: str) -> dict[str, Any]:
        preset = loads_preset(connection)
        if self.session is None or self.session.preset != preset:
            if self.session is not None:
                await self.session.close()
            self.session = ChromeSession(preset)
        kind = request["kind"]
        if kind == "chrome_discover":
            await self.session.discover()
        elif kind == "chrome_check":
            await self.session.check(request["row_id"], request["target_id"])
        elif kind == "chrome_disconnect":
            await self.session.close()
        elif kind != "chrome_status":
            raise ContractError("Unknown Chrome operation")
        return deepcopy(self.session.status)

    def close(self) -> None:
        if self.session is not None:
            asyncio.run_coroutine_threadsafe(self.session.close(), self.loop).result(timeout=5)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)
        self.loop.close()
