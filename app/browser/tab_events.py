"""TabEventWatcher — new-tab events from the browser-level CDP endpoint.

Complements the periodic re-scan: Chrome publishes ``Target.targetCreated`` /
``targetDestroyed`` / ``targetInfoChanged`` on ``/json/version``'s
``webSocketDebuggerUrl``, so a newly opened arena tab is linked within a second
instead of at the next poll. Polling stays the source of truth — if the endpoint
is unreachable the watcher just backs off and never blocks a scan.

Runs on its own daemon thread + event loop, so it is independent of the Qt/UI loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Callable, Optional

log = logging.getLogger("arena")

TARGET_EVENTS = (
    "Target.targetCreated",
    "Target.targetDestroyed",
    "Target.targetInfoChanged",
    "Target.detachedFromTarget",
)
DEFAULT_RETRY_SEC = 5.0


def split_endpoint(endpoint: str) -> tuple:
    """``"127.0.0.1:9223"`` → ``("127.0.0.1", 9223)``; defaults on garbage."""
    text = str(endpoint or "").strip()
    host, _sep, port = text.rpartition(":")
    try:
        return (host or "127.0.0.1"), int(port)
    except ValueError:
        return (text or "127.0.0.1"), 9222


def _browser_ws_url(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("webSocketDebuggerUrl", "web_socket_debugger_url"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


class TabEventWatcher:
    """Subscribe to browser target events; fire ``on_event`` for page changes."""

    def __init__(
        self,
        endpoint: str,
        on_event: Callable[[str], None],
        logger: Optional[Callable[[str, str], None]] = None,
        retry_sec: float = DEFAULT_RETRY_SEC,
    ):
        self._host, self._port = split_endpoint(endpoint)
        self._on_event = on_event
        self._log = logger or (lambda m, lvl="info": log.log(20, m))
        self._retry_sec = max(0.05, float(retry_sec))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.active = False

    @property
    def endpoint(self) -> str:
        return f"{self._host}:{self._port}"

    def start(self) -> bool:
        """Start the watcher thread. False when websockets is not installed."""
        if self._thread and self._thread.is_alive():
            return True
        try:
            import websockets  # noqa: F401
        except Exception as e:
            log.debug(f"tab events unavailable (websockets missing): {e}")
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="arena-tab-events")
        self._thread.start()
        return True

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        self.active = False
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=timeout)

    # ---- thread body ----
    def _run(self) -> None:
        try:
            asyncio.run(self._session())
        except Exception as e:  # never let the watcher kill the app
            log.debug(f"tab event watcher crashed: {e}")
        finally:
            self.active = False

    async def _session(self) -> None:
        import websockets

        while not self._stop.is_set():
            ws_url = await self._discover_endpoint()
            if not ws_url:
                await self._sleep(self._retry_sec)
                continue
            try:
                await self._listen(websockets, ws_url)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if self.active:
                    self._log(f"Tab event stream lost ({e}) — falling back to periodic scan", "warn")
                self.active = False
            if not self._stop.is_set():
                await self._sleep(self._retry_sec)

    async def _discover_endpoint(self) -> str:
        try:
            from .cdp_client import _fetch_json_sync

            url = f"http://{self._host}:{self._port}/json/version"
            loop = asyncio.get_event_loop()
            data, err = await loop.run_in_executor(None, lambda: _fetch_json_sync(url, timeout=2.0))
            if err:
                return ""
            return _browser_ws_url(data or {})
        except Exception as e:
            log.debug(f"browser endpoint discovery failed: {e}")
            return ""

    async def _listen(self, websockets, ws_url: str) -> None:
        async with websockets.connect(ws_url, ping_interval=None, max_size=None, open_timeout=5) as ws:
            await ws.send(json.dumps({"id": 1, "method": "Target.setDiscoverTargets", "params": {"discover": True}}))
            self.active = True
            self._log(f"👂 Listening for new-tab events on {self.endpoint} (browser endpoint)", "info")
            await self._read_events(ws)

    async def _read_events(self, ws) -> None:
        async for raw in ws:
            if self._stop.is_set():
                return
            method = self._event_method(raw)
            if method:
                try:
                    self._on_event(method)
                except Exception as e:
                    log.debug(f"tab event callback failed: {e}")

    @staticmethod
    def _event_method(raw) -> str:
        try:
            data = json.loads(raw)
        except Exception:
            return ""
        method = str(data.get("method") or "")
        return method if method in TARGET_EVENTS else ""

    async def _sleep(self, seconds: float) -> None:
        """Interruptible backoff — returns immediately once stop() is called."""
        deadline = asyncio.get_event_loop().time() + max(0.0, seconds)
        while not self._stop.is_set():
            left = deadline - asyncio.get_event_loop().time()
            if left <= 0:
                return
            await asyncio.sleep(min(0.05, left))
