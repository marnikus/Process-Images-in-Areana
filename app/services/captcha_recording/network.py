"""Sanitized CDP Network event collection for one captcha recording."""

from __future__ import annotations

import asyncio
import base64
from typing import Any, Awaitable, Callable

from .sanitize import redact_text, safe_url, textual_mime

EventSink = Callable[[str, dict[str, Any], bool], Awaitable[None]]


class NetworkCollector:
    """Queue CDP events and retrieve eligible bodies outside receive loop."""

    def __init__(self, cdp: Any, sink: EventSink, body_limit: int,
                 mark_truncated: Callable[[str], None]):
        self.cdp = cdp
        self.sink = sink
        self.body_limit = body_limit
        self.mark_truncated = mark_truncated
        self.queue: asyncio.Queue = asyncio.Queue()
        self.responses: dict[str, dict[str, Any]] = {}

    def on_event(self, message: dict[str, Any]) -> None:
        if str(message.get("method", "")).startswith("Network."):
            self.queue.put_nowait(message)

    async def drain(self) -> None:
        while not self.queue.empty():
            await self._record(self.queue.get_nowait())

    async def _record(self, message: dict[str, Any]) -> None:
        method = message.get("method", "")
        params = message.get("params") or {}
        request_id = str(params.get("requestId", ""))
        handlers = {"Network.requestWillBeSent": self._request,
                    "Network.responseReceived": self._response,
                    "Network.loadingFinished": self._body,
                    "Network.loadingFailed": self._failure}
        handler = handlers.get(method)
        if handler is not None:
            await handler(request_id, params)

    async def _request(self, request_id: str, params: dict[str, Any]) -> None:
        request = params.get("request") or {}
        payload = {"request_id": request_id, "url": safe_url(request.get("url", "")),
                   "method": request.get("method", ""), "resource_type": params.get("type", "")}
        await self.sink("network_request", payload, True)

    async def _response(self, request_id: str, params: dict[str, Any]) -> None:
        response = params.get("response") or {}
        payload = {"request_id": request_id, "url": safe_url(response.get("url", "")),
                   "status": response.get("status"), "mime": response.get("mimeType", ""),
                   "resource_type": params.get("type", ""),
                   "from_cache": bool(response.get("fromDiskCache"))}
        self.responses[request_id] = payload
        await self.sink("network_response", payload, True)

    async def _failure(self, request_id: str, params: dict[str, Any]) -> None:
        payload = {"request_id": request_id,
                   "error": redact_text(params.get("errorText", ""), 500),
                   "canceled": bool(params.get("canceled")),
                   "resource_type": params.get("type", "")}
        await self.sink("network_failure", payload, True)

    async def _body(self, request_id: str, _params: dict[str, Any]) -> None:
        meta = self.responses.pop(request_id, None)
        if not meta or not textual_mime(meta.get("mime", "")):
            return
        try:
            reply = await self.cdp.send("Network.getResponseBody", {"requestId": request_id}, timeout=5)
            result = reply.get("result") or {}
            body = result.get("body", "")
            if result.get("base64Encoded"):
                body = base64.b64decode(body).decode("utf-8", errors="replace")
            clipped = len(body) > self.body_limit
            if clipped:
                self.mark_truncated("response_bodies")
            payload = {"request_id": request_id, "body": redact_text(body, self.body_limit),
                       "truncated": clipped}
            await self.sink("response_body", payload, False)
        except Exception as exc:
            message = f"response body unavailable: {type(exc).__name__}"
            await self.sink("warning", {"message": message}, False)
