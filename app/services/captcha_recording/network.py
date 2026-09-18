"""Sanitized CDP Network event collection for one captcha recording."""

from __future__ import annotations

import base64
from collections import deque
import threading
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

from .sanitize import redact_text, safe_url, textual_mime

EventSink = Callable[[str, dict[str, Any], bool], Awaitable[None]]
MAX_QUEUED_EVENTS = 5_000


#: Only captcha traffic carries evidence a comparison needs; page bodies are
#: private content and the main noise source of a diff (RULE 20 / P8).
BODY_CATEGORIES = frozenset({"captcha", "verification"})
MAX_TRACKED_RESPONSES = 200


class NetworkCollector:
    """Queue CDP events and retrieve eligible bodies outside receive loop."""

    def __init__(self, cdp: Any, sink: EventSink, body_limit: int,
                 mark_truncated: Callable[[str], None]):
        self.cdp = cdp
        self.sink = sink
        self.body_limit = body_limit
        self.mark_truncated = mark_truncated
        self.queue: deque[dict[str, Any]] = deque()
        self._lock = threading.Lock()
        self.dropped = 0
        self._reported_dropped = 0
        self.responses: dict[str, dict[str, Any]] = {}
        self.bodies_captured = 0
        self.bodies_skipped = 0
        self.responses_evicted = 0

    def on_event(self, message: dict[str, Any]) -> None:
        if str(message.get("method", "")).startswith("Network."):
            with self._lock:
                if len(self.queue) >= MAX_QUEUED_EVENTS:
                    self.dropped += 1
                    self.mark_truncated("network_events")
                else:
                    self.queue.append(message)

    async def drain(self) -> None:
        while True:
            with self._lock:
                message = self.queue.popleft() if self.queue else None
                dropped = self.dropped
            if message is None:
                if dropped > self._reported_dropped:
                    self._reported_dropped = dropped
                    await self.sink("warning", {"message": "network events dropped",
                                                "count": dropped}, False)
                return
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
        self._track(request_id, payload)
        await self.sink("network_response", payload, True)

    def _track(self, request_id: str, payload: dict[str, Any]) -> None:
        """Keep the response map bounded; the oldest entry is the least useful."""
        if len(self.responses) >= MAX_TRACKED_RESPONSES:
            for key in list(self.responses)[:1]:
                self.responses.pop(key, None)
                self.responses_evicted += 1
        self.responses[request_id] = payload

    async def _failure(self, request_id: str, params: dict[str, Any]) -> None:
        payload = {"request_id": request_id,
                   "error": redact_text(params.get("errorText", ""), 500),
                   "canceled": bool(params.get("canceled")),
                   "resource_type": params.get("type", "")}
        await self.sink("network_failure", payload, True)

    def summary(self) -> dict[str, int]:
        """Bounded counters for the finish update (evidence-loss accounting)."""
        return {"queued_dropped": self.dropped, "bodies_captured": self.bodies_captured,
                "bodies_skipped": self.bodies_skipped, "responses_evicted": self.responses_evicted}

    async def _body(self, request_id: str, _params: dict[str, Any]) -> None:
        meta = self.responses.pop(request_id, None)
        if not meta or not textual_mime(meta.get("mime", "")):
            return
        if meta.get("category") not in BODY_CATEGORIES:
            self.bodies_skipped += 1
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
            self.bodies_captured += 1
            payload = {"request_id": request_id, "body": redact_text(body, self.body_limit),
                       "truncated": clipped, "category": meta.get("category", "")}
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
