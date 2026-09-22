"""RDP transport — one asyncio socket to a manually launched Firefox.

Owns exactly one thing: turning framed bytes into request/reply and event
streams. It knows nothing about tabs, consoles or clicks.

Two protocol facts shape the design (see `framing`):

* **No request ids.** A reply is matched by sender *and* shape, so only one
  request may be in flight at a time — `_lock` enforces that rather than
  leaving it to callers.
* **A timeout poisons the connection.** The server was never told we stopped
  listening, so the abandoned reply is still coming and would be read as the
  *next* call's answer — a wrong result with no symptom. A timed-out call
  therefore closes the socket; reconnecting is a cheap localhost connect.

Attach/detach is the whole point: `close()` drops our socket and leaves the
browser, its profile and its tabs untouched, so the app can reattach later.

Layer: browser leaf — asyncio + framing only; no Qt, no app imports.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from .framing import decode_packets, encode_packet, is_reply_from

__all__ = ["RDPTransport", "RDPClosed", "DEFAULT_PORT", "DEFAULT_TIMEOUT"]

DEFAULT_PORT = 6000        # `--start-debugger-server` default (NOT --remote-debugging-port)
DEFAULT_TIMEOUT = 15.0
_READ_CHUNK = 65536


class RDPClosed(RuntimeError):
    """The socket is gone or was poisoned by a timeout — reconnect to continue."""


class RDPTransport:
    """One framed connection: `request` for replies, `drain_events` for pushes."""

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                 timeout: float = DEFAULT_TIMEOUT):
        self.host, self.port, self.timeout = host, int(port), float(timeout)
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._buffer = b""
        self._events: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self.last_error = ""

    @property
    def is_connected(self) -> bool:
        return self._writer is not None

    async def connect(self) -> Dict[str, Any]:
        """Open the socket and consume Firefox's unsolicited root greeting."""
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), self.timeout)
        self._buffer, self._events, self.last_error = b"", [], ""
        return await self._read_matching("root")

    async def close(self) -> None:
        """Detach: drop our socket only — Firefox and its tabs keep running."""
        writer, self._writer, self._reader = self._writer, None, None
        self._buffer = b""
        if writer is None:
            return
        try:
            writer.close()
            await writer.wait_closed()
        except (OSError, asyncio.TimeoutError, RuntimeError):
            pass  # a half-dead socket is still detached

    async def request(self, packet: Dict[str, Any]) -> Dict[str, Any]:
        """Send one packet and return its direct reply (one call at a time)."""
        actor = str(packet.get("to", ""))
        async with self._lock:
            writer = self._require_writer()
            writer.write(encode_packet(packet))
            await writer.drain()
            return await self._read_matching(actor)

    def drain_events(self) -> List[Dict[str, Any]]:
        """Take the unsolicited packets buffered so far (e.g. `evaluationResult`)."""
        events, self._events = self._events, []
        return events

    def _require_writer(self) -> asyncio.StreamWriter:
        if self._writer is None:
            raise RDPClosed("not connected to Firefox")
        return self._writer

    async def _read_matching(self, actor: str) -> Dict[str, Any]:
        """Read until `actor` answers; everything else is buffered as an event."""
        while True:
            for packet in self._take_buffered(actor):
                return packet
            await self._fill()

    def _take_buffered(self, actor: str) -> List[Dict[str, Any]]:
        """Pop the reply from what is already decoded ([] when it has not arrived)."""
        packets, self._buffer = decode_packets(self._buffer)
        hit: List[Dict[str, Any]] = []
        for packet in packets:
            if not hit and is_reply_from(packet, actor):
                hit.append(packet)
            else:
                self._events.append(packet)
        return hit

    async def _fill(self) -> None:
        """One read; a timeout poisons the connection rather than desyncing it."""
        reader = self._reader
        if reader is None:
            raise RDPClosed("not connected to Firefox")
        try:
            chunk = await asyncio.wait_for(reader.read(_READ_CHUNK), self.timeout)
        except asyncio.TimeoutError:
            self.last_error = "timeout"
            await self.close()
            raise RDPClosed(f"no answer from Firefox in {self.timeout}s — connection dropped") from None
        if not chunk:
            self.last_error = "eof"
            await self.close()
            raise RDPClosed("Firefox closed the debugger connection")
        self._buffer += chunk
