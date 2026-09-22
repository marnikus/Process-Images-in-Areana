"""The client's protocol routing — RDP and BiDi instead of "always ask Chrome" (round 9).

`CDPClient` is the object the reconciler, the pool and every job action use. It was built for
one channel (a Chrome websocket per tab) and asked every endpoint for `GET /json/list` — which
is the owner's log, where a Firefox DevTools socket on 9224 answered "Not Found" every pass.

This mixin is the routing half of the client, so the CDP half stays untouched:

* it knows the **declared** protocol of the endpoint (pushed from the browser registry by
  `apply_cdp_config`, or by the pool when it joins a tab) and otherwise **detects** it once,
  caching the answer until the endpoint changes;
* `fetch_tabs` / `fetch_tabs_sync` / `diagnose_sync` ask the endpoint over the channel it
  actually speaks — an RDP endpoint is never sent HTTP;
* `connect(ws_url)` attaches when the handle names the browser's own socket (`rdp://…/ctx-N`)
  and keeps the websocket path for a CDP page url;
* `evaluate` is the one operation every channel has, so it routes to RDP/BiDi and keeps the
  transport's `last_error` / `last_error_kind` contract for its callers (B8).

RULE 18: methods ≤15 per class — this is a separate class on purpose, so neither it nor
`CDPClient` crosses the cap.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List

from .. import attached
from ..protocols import PROTOCOL_CDP

log = logging.getLogger("arena")
DETECT_TIMEOUT = 1.0


class RemoteMixin:
    """Protocol routing for a CDP transport: declared → detected → the channel's ops."""

    # ── what this endpoint speaks ────────────────────────────────────────

    def set_protocol(self, protocol: str, browser: str = "") -> None:
        """Declare the channel of this endpoint (the registry knows; a probe would guess)."""
        self._declared_protocol = str(protocol or "").strip().lower()
        self._browser = str(browser or "")
        self._detected_protocol = None
        if self._declared_protocol != PROTOCOL_CDP:
            self._attachment = None

    def protocol(self, timeout: float = DETECT_TIMEOUT) -> str:
        """The channel this endpoint speaks: the attachment, the declaration, else a probe."""
        if self._attachment is not None:
            return self._attachment.channel
        if self._declared_protocol:
            return self._declared_protocol
        if self._detected_protocol is None:
            from ..endpoints import detect_protocol
            self._detected_protocol = detect_protocol(self._host, self._port, timeout) or ""
        return self._detected_protocol

    @property
    def is_connected(self) -> bool:
        """An attachment is a connection even though it is not a tab websocket (round 9)."""
        if getattr(self, "_attachment", None) is not None:
            return True
        return bool(getattr(self, "_connected", False) and getattr(self, "_ws", None) is not None)

    def is_remote(self) -> bool:
        """True when this client talks to the browser's own socket (RDP/BiDi), not a tab's."""
        return self._attachment is not None or self.protocol() in (attached.PROTOCOL_RDP, attached.PROTOCOL_BIDI)

    def _endpoint_handle(self) -> attached.Handle:
        """This client's endpoint as a handle — the attachment's, once attached.

        A pooled Firefox client is built for one tab on one endpoint (`rdp://…/ctx-4`), so
        after the attach that handle *is* this client's endpoint, whatever host/port the
        pool it was built for happens to name.
        """
        if self._attachment is not None:
            return self._attachment
        return attached.endpoint_handle(self._host, self._port, self.protocol(), self._browser)

    # ── listing / diagnostics over the right channel ─────────────────────

    def fetch_tabs_sync(self, host: str = None, port: int = None) -> List[attached.Handle]:
        """This endpoint's tabs — over its own channel, never HTTP on a DevTools socket."""
        if not self.is_remote():
            return self._cdp_fetch_sync(host, port)
        handle = self._endpoint_handle()
        rows, err = attached.list_rows(handle, self._fetch_timeout())
        if err and not rows:
            log.warning(f"fetch_tabs_sync ({handle.channel}) failed: {err}")
            self.error.emit(err)
        return rows

    def _cdp_fetch_sync(self, host: str = None, port: int = None):
        """The CDP path, unchanged (kept here so the MRO stays explicit)."""
        from .client import fetch_tabs_sync
        h, p = host or self._host, port or self._port
        tabs, err, tried = fetch_tabs_sync(h, p)
        if err:
            log.warning(f"fetch_tabs_sync failed: {err} tried={tried}")
            self.error.emit(err)
        return tabs

    def diagnose_sync(self, host: str = None, port: int = None) -> dict:
        """Diagnostics for this endpoint, whatever channel it speaks."""
        if not self.is_remote():
            from .probe import diagnose_sync
            return diagnose_sync(host or self._host, port or self._port)
        return attached.diagnose(self._endpoint_handle(), self._fetch_timeout())

    async def fetch_tabs(self) -> List[attached.Handle]:
        """`fetch_tabs_sync` on the event loop's executor (the sync path is what blocks)."""
        if not self.is_remote():
            return await self._cdp_fetch_async()
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.fetch_tabs_sync())

    async def _cdp_fetch_async(self):
        """The CDP path: aiohttp first, then the executor's sync fetch (unchanged)."""
        from .client import _fetch_tabs_aiohttp, _fetch_tabs_sync_fallback
        merged = await _fetch_tabs_aiohttp(self._host, self._port)
        if merged:
            return list(merged.values())
        return await _fetch_tabs_sync_fallback(self, self._host, self._port)

    # ── attach / evaluate ────────────────────────────────────────────────

    async def connect(self, ws_url: str) -> bool:
        """Attach to a tab handle, or open the CDP websocket a page url names."""
        handle = attached.parse_handle(ws_url, self._host, self._port)
        if not attached.is_remote(handle):
            from .connect import connect_with_lock
            return await connect_with_lock(self, ws_url)
        loop = asyncio.get_event_loop()
        ok, reason = await loop.run_in_executor(None, lambda: attached.attach(handle, self._fetch_timeout()))
        return self._adopt_attachment(handle, ok, reason)

    def _adopt_attachment(self, handle: attached.Handle, ok: bool, reason: str) -> bool:
        """Register (or refuse) one attach on this transport, with the signals it already has."""
        if not ok:
            self.last_error, self.last_error_kind = reason, "transport"
            log.warning(f"attach failed for {handle.label}: {reason}")
            self.error.emit(reason)
            return False
        self._attachment = handle
        self._connected = True
        self._current_tab_id = handle.tab_id
        self._current_ws_url = handle.ws_url
        self.connected.emit()
        return True

    async def evaluate(self, expression: str, await_promise: bool = True):
        """Run JS on the attached channel (CDP keeps its websocket path and B8 contract)."""
        if self._attachment is None:
            return await super().evaluate(expression, await_promise)
        loop = asyncio.get_event_loop()
        answer = await loop.run_in_executor(
            None, lambda: attached.evaluate(self._attachment, expression, self._fetch_timeout()))
        self._note_answer(answer)
        return answer.value

    def _note_answer(self, answer: attached.Answer) -> None:
        """`evaluate`'s callers only see None — remember why (B8 shape, round 9 kinds)."""
        if not answer.error:
            self.last_error, self.last_error_kind = "", ""
            return
        self.last_error, self.last_error_kind = answer.error[:300], answer.kind
        log.warning(f"evaluate {answer.kind} error: {self.last_error}")

    def _fetch_timeout(self) -> float:
        """The deadline every channel call uses for this client."""
        return float(getattr(self, "_channel_timeout", attached.DEFAULT_TIMEOUT) or attached.DEFAULT_TIMEOUT)
