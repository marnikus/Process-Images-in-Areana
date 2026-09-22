"""CDP client facade ≤150 LOC (C2) — now also the app's *any-channel* client (round 9).

Composes transport + connect + tabs + dom + probe, and (through `RemoteMixin`) the RDP/BiDi
routing that lets one object drive whichever channel an endpoint speaks: a Chrome websocket
per tab, Firefox's DevTools socket per browser, or a BiDi session. Public API is the same as
the old `cdp_client.CDPClient`; `set_protocol(protocol, browser)` declares the channel and
`protocol()` detects it when nobody declared one.
"""
from __future__ import annotations

import asyncio
import logging
from typing import List, Tuple

from .remote import RemoteMixin
from .transport import CDPTransport
from .tabs import TabInfo, fetch_tabs_sync, _build_hosts_to_try, _merge_by_id
from .probe import diagnose_sync
from .. import attached
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


class CDPClient(RemoteMixin, CDPTransport):
    """Facade — keeps same API, delegates heavy logic to submodules and channel routing."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9222, parent=None, protocol: str = ""):
        super().__init__(host=host, port=port, parent=parent)
        self._connect_lock = None
        self._connecting = False
        self._last_exc = None
        self._declared_protocol = str(protocol or "").strip().lower()
        self._detected_protocol = None
        self._attachment = None
        self._browser = ""
        self._channel_timeout = attached.DEFAULT_TIMEOUT

    def set_host_port(self, host: str = None, port: int = None):
        """The endpoint moved, so a previous detection belongs to a different endpoint."""
        CDPTransport.set_host_port(self, host, port)
        self._detected_protocol = None
        self._attachment = None

    async def connect(self, ws_url: str) -> bool:
        """QObject shadow guard, the same trap as `disconnect` below.

        PySide6 resolves an *inherited* `connect` on a QObject subclass to
        `QObject.connect` (built-in), so the call raises "not enough arguments"
        instead of attaching/dialling — the routing itself lives in `RemoteMixin`.
        """
        return await RemoteMixin.connect(self, ws_url)

    async def disconnect(self):
        """QObject shadow guard: PySide6 resolves an INHERITED `disconnect`
        on a QObject subclass to QObject.disconnect (built-in) instead of
        CDPTransport.disconnect — connect() then raises "not enough
        arguments". Defining it in this class keeps the coroutine in the
        instance's own MRO lookup. Regression: tests/test_cdp_client_stub.py
        ::test_disconnect_is_not_shadowed_by_qobject."""
        self._attachment = None      # detach = drop our socket; the browser keeps running
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
