"""CDP client facade ≤150 LOC (C2).

Composes transport + connect + tabs + dom + probe.
Public API same as old cdp_client.CDPClient for backward compat.
"""
from __future__ import annotations

import asyncio
import logging
from typing import List, Tuple

from .transport import CDPTransport
from .connect import connect_with_lock
from .tabs import TabInfo, fetch_tabs_sync, _build_hosts_to_try, _merge_by_id
from .probe import diagnose_sync
from .dom import (
    HighlightSpec,
    get_document as dom_get_document,
    query_selector as dom_query_selector,
    query_selector_all as dom_query_selector_all,
    set_file_input_files as dom_set_file_input_files,
    attach_image_cdp as dom_attach_image_cdp,
    highlight_element as dom_highlight_element,
    clear_highlights as dom_clear_highlights,
)

log = logging.getLogger("arena")


async def _fetch_tabs_aiohttp(host: str, port: int) -> dict[str, TabInfo]:
    merged: dict[str, TabInfo] = {}
    try:
        import aiohttp
        for h in _build_hosts_to_try(host):
            try:
                url = f"http://{h}:{port}/json/list"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as r:
                        if r.status != 200:
                            continue
                        items = await r.json()
                        from .tabs import _parse_tabs
                        tabs = _parse_tabs(items, preferred_host=host, preferred_port=port)
                        _merge_by_id(merged, tabs, host)
            except Exception as e:
                log.debug(f"fetch_tabs aiohttp {h} failed: {e}")
                continue
    except ImportError:
        log.debug("aiohttp not available")
    except Exception as e:
        log.debug(f"aiohttp path failed: {e}")
    return merged


async def _fetch_tabs_sync_fallback(transport, host: str, port: int) -> List[TabInfo]:
    try:
        loop = asyncio.get_event_loop()
        tabs, err, _ = await loop.run_in_executor(None, lambda: fetch_tabs_sync(host, port))
        if err and not tabs:
            transport.error.emit(err)
        return tabs
    except Exception as e:
        log.warning(f"fetch_tabs fallback failed: {e}")
        transport.error.emit(str(e))
        return []


class CDPClient(CDPTransport):
    """Facade — keeps same API, delegates heavy logic to submodules."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9222, parent=None):
        super().__init__(host=host, port=port, parent=parent)
        self._connect_lock = None
        self._connecting = False
        self._last_exc = None

    def fetch_tabs_sync(self, host: str = None, port: int = None):
        h = host or self._host
        p = port or self._port
        tabs, err, tried = fetch_tabs_sync(h, p)
        if err:
            log.warning(f"fetch_tabs_sync failed: {err} tried={tried}")
            self.error.emit(err)
        return tabs

    def diagnose_sync(self, host: str = None, port: int = None) -> dict:
        h = host or self._host
        p = port or self._port
        return diagnose_sync(h, p)

    async def fetch_tabs(self):
        merged = await _fetch_tabs_aiohttp(self._host, self._port)
        if merged:
            return list(merged.values())
        return await _fetch_tabs_sync_fallback(self, self._host, self._port)

    async def connect(self, ws_url: str) -> bool:
        return await connect_with_lock(self, ws_url)

    async def disconnect(self):
        """QObject shadow guard: PySide6 resolves an INHERITED `disconnect`
        on a QObject subclass to QObject.disconnect (built-in) instead of
        CDPTransport.disconnect — connect() then raises "not enough
        arguments". Defining it in this class keeps the coroutine in the
        instance's own MRO lookup. Regression: tests/test_cdp_client_stub.py
        ::test_disconnect_is_not_shadowed_by_qobject."""
        await CDPTransport.disconnect(self)

    # ---- DOM delegations ----
    async def get_document(self):
        return await dom_get_document(self)

    async def query_selector(self, node_id: int, selector: str):
        return await dom_query_selector(self, node_id, selector)

    async def query_selector_all(self, node_id: int, selector: str):
        return await dom_query_selector_all(self, node_id, selector)

    async def set_file_input_files(self, node_id: int, files: List[str]) -> bool:
        return await dom_set_file_input_files(self, node_id, files)

    async def attach_image_cdp(self, image_path: str, selectors: List[str] = None) -> Tuple[bool, str]:
        return await dom_attach_image_cdp(self, image_path, selectors)

    async def highlight_element(self, selector: str, spec: HighlightSpec = None):
        if spec is None:
            spec = HighlightSpec()
        return await dom_highlight_element(self, selector, spec)

    async def clear_highlights(self):
        return await dom_clear_highlights(self)
