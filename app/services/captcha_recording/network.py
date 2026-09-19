"""Sanitized CDP Network event collection for one captcha recording.

H5/P9: CDP events arrive on the websocket thread while the recorder drains
on the Qt/asyncio loop — the handoff is a lock-protected unbounded deque
(appended under the lock, popped under the lock, recorded outside it), so
no event can be dropped by a cross-loop queue race.
"""

from __future__ import annotations

import base64
import threading
from collections import deque
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

from .sanitize import redact_text, safe_url, textual_mime

EventSink = Callable[[str, dict[str, Any], bool], Awaitable[None]]
MAX_QUEUED_EVENTS = 5_000


class NetworkCollector:
    """Collect CDP events and retrieve eligible bodies outside receive loop."""

    def __init__(self, cdp: Any, sink: EventSink, body_limit: int,
                 mark_truncated: Callable[[str], None]):
        self.cdp = cdp
        self.sink = sink
        self.body_limit = body_limit
        self.mark_truncated = mark_truncated
        self._events: deque[dict[str, Any]] = deque()
        self._lock = threading.Lock()
        self._closed = False
        # P9: events lost after close are counted here, never dropped silently
        self.dropped_events = 0
        self.responses: dict[str, dict[str, Any]] = {}

    def on_event(self, message: dict[str, Any]) -> None:
        if not str(message.get("method", "")).startswith("Network."):
            return
        with self._lock:
            if self._closed:
                self.dropped_events += 1
            else:
                self._events.append(message)

    def close(self) -> None:
        """Stop collecting; count undrained events as dropped, never lose them silently."""
        with self._lock:
            self._closed = True
            self.dropped_events += len(self._events)
            self._events.clear()

    async def drain(self) -> None:
        while True:
            with self._lock:
                if not self._events:
                    return
                message = self._events.popleft()
            await self._record(message)

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
        url = safe_url(request.get("url", ""))
        payload = {"request_id": request_id, "url": url, "category": _category(url),
                   "method": request.get("method", ""), "resource_type": params.get("type", "")}
        await self.sink("network_request", payload, True)

    async def _response(self, request_id: str, params: dict[str, Any]) -> None:
        response = params.get("response") or {}
        url = safe_url(response.get("url", ""))
        payload = {"request_id": request_id, "url": url, "category": _category(url),
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


def _category(url: str) -> str:
    """Safe endpoint class for comparisons; never inspect URL queries."""
    parts = urlsplit(url)
    value = f"{parts.hostname or ''}{parts.path}".lower()
    if "recaptcha" in value or "captcha" in value:
        return "captcha"
    if any(word in parts.path.lower() for word in ("verify", "challenge", "security")):
        return "verification"
    if any(word in parts.path.lower() for word in ("generate", "image", "completion")):
        return "generation"
    return "page_api" if "/api/" in parts.path.lower() else "other"
