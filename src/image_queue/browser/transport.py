"""Adapt retained cdp_client_transport framing/receive lifecycle; no command replay.

Removed cookie, file-input and input helpers. Pending requests fail on disconnect,
timeout/cancellation always remove IDs, and socket details never enter application logs.
"""

import asyncio
import json
from collections.abc import Callable
from typing import Any

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException

from image_queue.browser.discovery import socket_url
from image_queue.domain.settings import ChromeEndpoint
from image_queue.domain.validation import ContractError


class CDPClient:
    def __init__(self, endpoint: ChromeEndpoint) -> None:
        self.endpoint = endpoint
        self._ws: ClientConnection | None = None
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._cmd_id = 0
        self._receive_task: asyncio.Task[None] | None = None
        self.on_event: Callable[[dict[str, Any]], None] = lambda _: None
        self.on_disconnect: Callable[[], None] = lambda: None

    async def connect(self, url: str) -> None:
        await self.disconnect()
        try:
            self._ws = await connect(
                socket_url(url, self.endpoint),
                open_timeout=3,
                close_timeout=1,
                max_size=1_000_000,
                proxy=None,
            )
            self._receive_task = asyncio.create_task(self._receive_loop())
            for domain in ("Page", "Runtime"):
                await self.send(f"{domain}.enable")
        except (OSError, WebSocketException, TimeoutError, ContractError) as exc:
            await self.disconnect()
            raise ContractError("Chrome socket connection failed") from exc

    async def disconnect(self) -> None:
        task, socket = self._receive_task, self._ws
        self._receive_task, self._ws = None, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if socket is not None:
            await socket.close()
        self._fail_pending()
        self.on_disconnect()

    async def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._ws is None:
            raise ContractError("Chrome is disconnected")
        self._cmd_id += 1
        identifier = self._cmd_id
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[identifier] = future
        try:
            await self._ws.send(
                json.dumps({"id": identifier, "method": method, "params": params or {}})
            )
            response = await asyncio.wait_for(future, timeout=3)
            if "error" in response:
                raise ContractError("Chrome rejected the verification command")
            return response
        except (OSError, WebSocketException, TimeoutError) as exc:
            raise ContractError("Chrome command failed; no automatic replay") from exc
        finally:
            self._pending.pop(identifier, None)

    async def _receive_loop(self) -> None:
        try:
            assert self._ws is not None
            async for raw in self._ws:
                self._dispatch(json.loads(raw))
        except (WebSocketException, ValueError, TypeError):
            pass
        finally:
            self._fail_pending()
            self.on_disconnect()

    def _dispatch(self, frame: Any) -> None:
        if not isinstance(frame, dict):
            raise ValueError("Invalid CDP frame")
        identifier = frame.get("id")
        if type(identifier) is int:
            future = self._pending.pop(identifier, None)
            if future is not None and not future.done():
                future.set_result(frame)
        elif isinstance(frame.get("method"), str):
            self.on_event(frame)

    def _fail_pending(self) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(ContractError("Chrome disconnected; recheck explicitly"))
        self._pending.clear()
