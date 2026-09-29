"""CDP transport — WebSocket send/receive, evaluate (C2)."""
from __future__ import annotations

import asyncio
import json
import logging
import time
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

from ...cdp_events import CDPEventRouter, route_cdp_message
from ..liveness import note_late_reply, note_timed_out
from ..dialogs import DialogWatch, close_open_dialog, send_unblocked
from ..home_loop import on_home_loop, running_loop

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
        self.dialogs = DialogWatch()             # I-71: a JS dialog blocks every evaluate
        self.events.add(self.dialogs.on_event)
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
        await _disconnect(self)

    @on_home_loop            # I-76: the socket is only ever touched by the loop that opened it
    async def send(self, method: str, params: dict | None = None, timeout: float = 30) -> dict:
        if (ws := self._ws) is None or not self._connected:
            raise ConnectionError("CDP not connected")
        self._cmd_id += 1
        cmd_id = self._cmd_id    # I-71: THIS command's id — `self._cmd_id` moves on meanwhile
        fut = asyncio.get_event_loop().create_future()
        self._pending[cmd_id] = fut
        payload = json.dumps({"id": cmd_id, "method": method, "params": params or {}})
        await _send_payload(self, cmd_id, ws, payload)
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            note_timed_out(self, cmd_id, method, timeout)
            raise TimeoutError(f"CDP command {method} timed out after {timeout}s") from None
        finally:                 # timeout or cancel: free our own waiter, never a neighbour's
            self._pending.pop(cmd_id, None)

    async def _receive_loop(self):
        try:
            log.info(f"CDP receive loop started for {self._current_ws_url[:80]}")
            async for raw in self._ws:
                try:
                    data = json.loads(raw)
                except Exception:
                    continue
                _route(self, raw, data)
            log.warning(f"CDP receive loop ended for {self._current_ws_url[:80]}")
        except asyncio.CancelledError:
            log.info(f"CDP receive loop cancelled for {self._current_ws_url[:80]}")
        except Exception as e:
            _receive_error(self, e)
        finally:
            was = _receive_teardown(self)
            if was:
                log.warning(f"CDP disconnected (was connected) {self._current_ws_url[:80]}")
            else:
                log.info(f"CDP disconnected (was not) {self._current_ws_url[:80]}")
            try:
                self.disconnected.emit()
            except Exception:
                pass

    async def evaluate(self, expression: str, await_promise: bool = True, timeout: float = 30.0):
        try:
            await close_open_dialog(self)
            params = {"expression": expression, "returnByValue": True, "awaitPromise": await_promise}
            r = await send_unblocked(self, "Runtime.evaluate", params, timeout)
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



from .routing import _route, _send_payload
from .teardown import _disconnect, _receive_error, _receive_teardown
from .errors import _note_eval_error, _decode_reply, _exc_text
