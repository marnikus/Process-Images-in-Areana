"""CDP transport — WebSocket send/receive, evaluate (C2).

RULE18: file 150-300, func ≤20, CC≤10, methods≤15.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

try:
    from PySide6.QtCore import QObject, Signal
except ImportError:
    class QObject:
        def __init__(self, *args, **kwargs):
            _ = (args, kwargs)

    def Signal(*args, **kwargs):
        _ = (args, kwargs)

        class _Sig:
            def emit(self, *a, **kw):
                _ = (a, kw)

            def connect(self, *a, **kw):
                _ = (a, kw)

        return _Sig()

from ..cdp_events import CDPEventRouter, route_cdp_message

log = logging.getLogger("arena")


class CDPTransport(QObject):
    connected = Signal()
    disconnected = Signal()
    error = Signal(str)

    def __init__(self, host: str = "127.0.0.1", port: int = 9222, parent=None):
        super().__init__(parent)
        self._host = host
        self._port = port
        self._ws = None
        self._cmd_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self.events = CDPEventRouter()
        self._receive_task: Optional[asyncio.Task] = None
        self._connected = False
        self._current_ws_url = ""
        self._current_tab_id = ""
        self.last_error = ""       # B8: why the last evaluate() answered None
        self.last_error_kind = ""  # "" | "js" | "protocol" | "transport"

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    @property
    def is_connected(self) -> bool:
        return bool(self._connected and self._ws is not None)

    def set_host_port(self, host: str = None, port: int = None):
        if host:
            self._host = str(host).strip() or self._host
        if port:
            try:
                p = int(port)
                if 1 <= p <= 65535:
                    self._port = p
            except Exception:
                pass

    def get_host_port(self):
        return self._host, self._port

    async def disconnect(self):
        self._connected = False
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except Exception:
                pass
            self._receive_task = None
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        self._pending.clear()
        self.disconnected.emit()

    async def send(self, method: str, params: dict | None = None, timeout: float = 30) -> dict:
        if not self._ws:
            raise ConnectionError("CDP not connected")
        self._cmd_id += 1
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        self._pending[self._cmd_id] = fut
        payload = json.dumps({"id": self._cmd_id, "method": method, "params": params or {}})
        await self._ws.send(payload)
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(self._cmd_id, None)
            raise TimeoutError(f"CDP command {method} timed out after {timeout}s")

    async def _receive_loop(self):
        try:
            log.info(f"CDP receive loop started for {self._current_ws_url[:80]}")
            async for raw in self._ws:
                try:
                    data = json.loads(raw)
                except Exception:
                    continue
                route_cdp_message(self, data)
            log.warning(f"CDP receive loop ended for {self._current_ws_url[:80]}")
        except asyncio.CancelledError:
            log.info(f"CDP receive loop cancelled for {self._current_ws_url[:80]}")
        except Exception as e:
            import traceback
            tb = traceback.format_exc()[-800:]
            log.error(f"CDP receive error {self._current_ws_url[:80]}: {e} — {tb}")
            self.error.emit(f"CDP receive error: {e}")
        finally:
            was = self._connected
            self._connected = False
            if was:
                log.warning(f"CDP disconnected (was connected) {self._current_ws_url[:80]}")
            else:
                log.info(f"CDP disconnected (was not) {self._current_ws_url[:80]}")
            try:
                self.disconnected.emit()
            except Exception:
                pass

    async def evaluate(self, expression: str, await_promise: bool = True):
        try:
            r = await self.send(
                "Runtime.evaluate",
                {"expression": expression, "returnByValue": True, "awaitPromise": await_promise},
            )
        except Exception as e:
            _note_eval_error(self, "transport", _exc_text(e))
            return None
        kind, text, value = _decode_reply(r)
        if kind:
            _note_eval_error(self, kind, text)
            return None
        self.last_error = ""
        self.last_error_kind = ""
        return value


def _note_eval_error(transport, kind: str, text: str) -> None:
    """Remember + log why evaluate() returns None (callers only see None)."""
    transport.last_error_kind = kind
    transport.last_error = text[:300]
    log.warning(f"evaluate {kind} error: {transport.last_error}")


def _decode_reply(r) -> tuple:
    """Runtime.evaluate reply → (error_kind, error_text, value); kind '' = ok.

    Chrome answers a protocol failure as {"error": {...}} with no "result"
    at all — the old reader took result={} and returned None silently (B8).
    """
    reply = r if isinstance(r, dict) else {}
    err = reply.get("error")
    if err:
        return "protocol", _protocol_text(err), None
    res = reply.get("result", {}) or {}
    if res.get("exceptionDetails"):
        return "js", _exception_text(res.get("exceptionDetails")), None
    return "", "", res.get("result", {}).get("value")


def _exc_text(exc: BaseException) -> str:
    """`ConnectionClosed` and friends often stringify empty — keep the type."""
    text = str(exc)
    name = type(exc).__name__
    return f"{name}: {text}" if text else name


def _protocol_text(err) -> str:
    """CDP error object → its message (Chrome: {"code": -32000, "message": ...})."""
    if isinstance(err, dict):
        return str(err.get("message") or err)
    return str(err)


def _exception_text(details) -> str:
    """Short human text for Runtime.evaluate exceptionDetails."""
    try:
        exc = details.get("exception") or {}
        return str(exc.get("description") or details.get("text") or exc.get("value") or details)
    except Exception:
        return str(details)
