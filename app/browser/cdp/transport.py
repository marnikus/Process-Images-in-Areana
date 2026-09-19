"""CDP websocket transport: command send + receive loop (W2 split)."""
from __future__ import annotations

import asyncio
import json

from ..cdp_events import route_cdp_message

log = __import__("logging").getLogger("arena")


class CdpTransportMixin:
    """send()/disconnect()/_receive_loop() over the raw websocket."""

    async def send(self, method: str, params: dict | None = None, timeout: float = 30) -> dict:
        """Send one CDP command and await its matching response."""
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

    async def disconnect(self):
        """Tear down receive task + websocket and emit disconnected."""
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

    async def _receive_loop(self):
        """Route incoming websocket frames until close/cancel; emits disconnected."""
        try:
            log.info(f"CDP receive loop started for {self._current_ws_url[:80]}")
            async for raw in self._ws:
                try:
                    data = json.loads(raw)
                except Exception:
                    continue
                route_cdp_message(self, data)
            log.warning(f"CDP receive loop ended normally for {self._current_ws_url[:80]} — websocket closed by Chrome")
        except asyncio.CancelledError:
            log.info(f"CDP receive loop cancelled for {self._current_ws_url[:80]}")
            pass
        except Exception as e:
            import traceback
            tb = traceback.format_exc()[-800:]
            log.error(f"CDP receive error for {self._current_ws_url[:80]}: {e} — {tb}")
            self.error.emit(f"CDP receive error: {e}")
        finally:
            self._receive_loop_done()

    def _receive_loop_done(self):
        """Final bookkeeping after the receive loop exits."""
        was_connected = self._connected
        self._connected = False
        if was_connected:
            log.warning(f"CDP disconnected (was connected) for {self._current_ws_url[:80]}")
        else:
            log.info(f"CDP disconnected (was not connected) for {self._current_ws_url[:80]}")
        try:
            self.disconnected.emit()
        except Exception:
            pass
