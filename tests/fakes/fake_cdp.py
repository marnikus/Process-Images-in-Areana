"""Fake CDP Transport — replays canned responses, no real Chrome (Phase 2).

RULE 18: file 150-300 LOC ideal, current ~100 LOC.
RULE 16: class LOC ≤150, methods ≤15, func LOC ≤30, CC ≤10.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class FakeCDPTransport:
    """Fake transport that returns canned JSON without WebSocket."""

    def __init__(self, tabs: List[Dict] | None = None):
        self._tabs = tabs or []
        self._connected = False
        self._sent: List[Dict] = []

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self, ws_url: str) -> bool:
        self._connected = True
        self._sent.append({"method": "connect", "ws_url": ws_url})
        return True

    async def disconnect(self):
        self._connected = False

    async def send(self, method: str, params: Dict | None = None, timeout: float = 5) -> Dict:
        self._sent.append({"method": method, "params": params})
        # Return canned responses based on method
        if method == "DOM.getDocument":
            return {"result": {"root": {"nodeId": 1}}}
        if method == "DOM.querySelector":
            return {"result": {"nodeId": 2}}
        if method == "DOM.setFileInputFiles":
            return {"result": {}}
        if method == "Runtime.evaluate":
            return {"result": {"result": {"value": {"ok": True}}}}
        return {"result": {}}

    async def evaluate(self, expr: str, await_promise: bool = True) -> Any:
        self._sent.append({"method": "evaluate", "expr": expr[:100]})
        return {"ok": True, "value": "fake"}

    def get_sent(self) -> List[Dict]:
        return list(self._sent)


class FakeCDPClient:
    """Fake CDP client that uses FakeCDPTransport."""

    def __init__(self, transport: FakeCDPTransport | None = None):
        self._transport = transport or FakeCDPTransport()
        self._host = "127.0.0.1"
        self._port = 9222

    @property
    def is_connected(self) -> bool:
        return self._transport.is_connected

    async def fetch_tabs(self):
        return []

    async def attach_image_cdp(self, image_path: str, selectors=None):
        return True, f"Fake attached {image_path}"

    async def evaluate(self, expr: str, await_promise: bool = True):
        return await self._transport.evaluate(expr, await_promise)
