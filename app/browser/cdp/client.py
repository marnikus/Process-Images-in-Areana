"""CDPClient — Chrome DevTools Protocol client (W2 split).

Core state + tab discovery; connection lifecycle lives in
app/browser/cdp/connection.py, transport in transport.py, DOM ops in dom.py.
"""
from __future__ import annotations

import asyncio
import logging

try:
    from PySide6.QtCore import QObject, Signal
    _qt_core = True
except ImportError:
    _qt_core = False

if not _qt_core:  # headless shim (no PySide6)
    class QObject:
        def __init__(self, *qt_shim_args, **qt_shim_kwargs): pass

    def Signal(*sig_shim_args, **sig_shim_kwargs):
        class _Sig:
            def emit(self, *emit_shim_args, **emit_shim_kwargs): pass
            def connect(self, *connect_shim_args, **connect_shim_kwargs): pass
        return _Sig()

from ..cdp_events import CDPEventRouter
from .connection import CdpConnectionMixin
from .dom import CdpDomMixin
from .endpoints import hosts_to_try
from .tabs import TabInfo, _parse_tabs, diagnose_sync, fetch_tabs_sync
from .transport import CdpTransportMixin

log = logging.getLogger("arena")


class CDPClient(CdpConnectionMixin, CdpTransportMixin, CdpDomMixin, QObject):
    """Async CDP client over a Chrome remote-debugging websocket."""

    connected = Signal()
    disconnected = Signal()
    error = Signal(str)

    def __init__(self, host: str = "127.0.0.1", port: int = 9222, parent=None):
        super().__init__(parent)
        self._host = host
        self._port = port
        self._ws = None
        self._cmd_id = 0
        self._pending = {}
        self.events = CDPEventRouter()
        self._receive_task = None
        self._connected = False
        self._current_ws_url = ""
        self._current_tab_id = ""
        self._connect_lock = None
        self._connecting = False

    # PySide6: QObject's C++ connect/disconnect hide mixin methods of the
    # same name — own-class delegates keep the public API working.
    async def connect(self, ws_url: str) -> bool:
        """Connect to a Chrome tab websocket (CdpConnectionMixin.connect)."""
        return await CdpConnectionMixin.connect(self, ws_url)

    async def disconnect(self):
        """Tear down the websocket (CdpTransportMixin.disconnect)."""
        return await CdpTransportMixin.disconnect(self)

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    @property
    def is_connected(self) -> bool:
        return bool(self._connected and self._ws is not None)

    def set_host_port(self, host: str = None, port: int = None):
        """Update host/port (validated); keeps current values on bad input."""
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

    def fetch_tabs_sync(self, host: str = None, port: int = None):
        """Sync tab fetch (logs + emits error on failure)."""
        h = host or self._host
        p = port or self._port
        tabs, err, tried = fetch_tabs_sync(h, p)
        if err:
            log.warning(f"fetch_tabs_sync failed: {err} tried={tried}")
            self.error.emit(err)
        return tabs

    def diagnose_sync(self, host: str = None, port: int = None) -> dict:
        """Sync full diagnostics (port/version/list per candidate host)."""
        h = host or self._host
        p = port or self._port
        return diagnose_sync(h, p)

    async def fetch_tabs(self):
        """Fetch tabs via HTTP /json/list — tries aiohttp first, merging all hosts, fallback to sync."""
        merged = await self._fetch_tabs_aiohttp()
        if merged:
            return list(merged.values())
        return await self._fetch_tabs_sync_fallback()

    async def _fetch_tabs_aiohttp(self) -> dict:
        """aiohttp /json/list across candidate hosts, merged by tab id."""
        merged: dict = {}
        try:
            import aiohttp
        except ImportError:
            log.debug("aiohttp not available, using sync fallback")
            return merged
        try:
            for h in hosts_to_try(self._host):
                tabs = await self._fetch_tabs_aiohttp_host(h)
                _merge_tab_rows(merged, tabs)
        except Exception as e:
            log.debug(f"aiohttp path failed: {e}")
        return merged

    async def _fetch_tabs_aiohttp_host(self, host: str) -> list:
        """One host's tabs via aiohttp ([] on any failure)."""
        import aiohttp
        try:
            url = f"http://{host}:{self._port}/json/list"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as r:
                    if r.status != 200:
                        return []
                    items = await r.json()
                    return _parse_tabs(items, preferred_host=self._host, preferred_port=self._port)
        except Exception as e:
            log.debug(f"fetch_tabs aiohttp {host} failed: {e}")
            return []

    async def _fetch_tabs_sync_fallback(self):
        """Threadpool fallback to the sync fetcher."""
        try:
            loop = asyncio.get_event_loop()
            tabs, err, tried = await loop.run_in_executor(None, lambda: fetch_tabs_sync(self._host, self._port))
            if err and not tabs:
                self.error.emit(err)
            return tabs
        except Exception as e:
            log.warning(f"fetch_tabs fallback failed: {e}")
            self.error.emit(str(e))
            return []


def _merge_tab_rows(merged: dict, tabs: list) -> None:
    """Merge TabInfo rows by id (first wins)."""
    for t in tabs:
        key = t.id or t.ws_url
        if key and key not in merged:
            merged[key] = t
