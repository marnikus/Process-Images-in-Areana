"""CDP transport — WebSocket send/receive, evaluate (C2).

RULE18: file 150-300, func ≤20, CC≤10, methods≤15.
"""
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

from ..cdp_events import CDPEventRouter, route_cdp_message
from .liveness import note_late_reply, note_timed_out
from .dialogs import DialogWatch, close_open_dialog, send_unblocked
from .home_loop import on_home_loop, running_loop

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


def _route(transport, raw, data: dict) -> None:
    """Note what arrived (I-72: a silent socket names its last message), then route it."""
    size, kind = len(raw), str(data.get("method") or "reply")
    transport.last_rx = {"at": time.monotonic(), "bytes": size, "kind": kind}
    if size > getattr(transport, "largest_rx", {}).get("bytes", 0):
        transport.largest_rx = {"bytes": size, "kind": kind}
    note_late_reply(transport, data.get("id"))
    route_cdp_message(transport, data)


async def _send_payload(transport, cmd_id: int, ws, payload: str) -> None:
    """Write one frame; a failed write must not leave a pending waiter."""
    try:
        await ws.send(payload)
    except Exception:
        transport._pending.pop(cmd_id, None)
        raise


@on_home_loop
async def _disconnect(transport) -> None:
    """Close on purpose: fail waiters, stop the receive loop, close the socket."""
    transport._connected = False
    _fail_pending(transport, "CDP disconnected")   # waiters must not burn timeouts
    ws, transport._ws = transport._ws, None        # detach first; teardown owns close
    if transport._receive_task:
        transport._receive_task.cancel()
        try:
            await transport._receive_task
        except Exception:
            pass
        transport._receive_task = None
    if ws:
        try:
            await ws.close()
        except Exception:
            pass
    transport.disconnected.emit()


def _receive_teardown(transport) -> bool:
    """Receive loop is dead: drop the socket, fail in-flight commands NOW.

    Returns whether the transport was connected when the loop ended.
    """
    was = transport._connected
    transport._connected = False
    transport._ws = None                            # later sends must fail fast
    _fail_pending(transport, "CDP connection lost")  # no full-timeout waiters
    return was


def _fail_pending(transport, reason: str) -> None:
    """Fail every in-flight command NOW — a dead connection answers nothing.

    Waiters used to serve their full timeout and report a misleading
    TimeoutError (owner log: evaluate burned 30 s while the socket was already
    gone, "no close frame received or sent"). Module-level to keep
    CDPTransport at its recorded class/method ratchets (2026-09-25).
    """
    pending, transport._pending = transport._pending, {}
    for fut in pending.values():
        _fail_on_its_loop(fut, ConnectionError(reason))


def _fail_on_its_loop(fut, exc: Exception) -> None:
    """Fail a waiter on its OWN loop (I-76): directly when we are on it, else thread-safe.

    `_fail_pending` also runs from a garbage-collected receive loop on any
    thread; a direct set_exception there is qasync's `assert timerid not in
    self.__callbacks` (owner log 2026-09-27).
    """
    try:
        loop = fut.get_loop()
        if loop is running_loop():
            _set_exception_if_pending(fut, exc)
        else:
            loop.call_soon_threadsafe(_set_exception_if_pending, fut, exc)
    except RuntimeError:
        pass                      # its loop is closed — nobody waits on it any more


def _set_exception_if_pending(fut, exc: Exception) -> None:
    if not fut.done():
        fut.set_exception(exc)


def _receive_error(transport, e: Exception) -> None:
    """Receive-side failure: capped traceback + error signal (module-level to
    keep `_receive_loop` under the file's 28-LOC floor)."""
    import traceback
    tb = traceback.format_exc()[-800:]
    log.error(f"CDP receive error {transport._current_ws_url[:80]}: {e} — {tb}")
    transport.error.emit(f"CDP receive error: {e}")


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
