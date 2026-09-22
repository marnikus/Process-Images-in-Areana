"""RDP connection — one socket, paired replies, queued events (2026-09-21).

The DevTools protocol has **no request ids**: a client request is answered by
the next reply, in order. The only thing that may arrive unsolicited is an event
(Firefox pushes console/network/resource events at any time), and a client that
lets one of those consume the reply slot desynchronizes exactly like a framing
bug — so this connection holds a queue and a rule (`actors.is_event`) instead of
a promise.

Attach and detach are just `connect()` / `close()`: nothing here ever talks to
the browser process, so closing the app or the socket leaves the running Firefox
untouched (the owner's requirement R2).

RULE 18: class ≤150 / ≤15 methods; funcs ≤20; ≤3 params.
"""

from __future__ import annotations

import socket
from typing import Callable, List, Optional

from . import actors
from .wire import (DEFAULT_TIMEOUT, GREETING_TIMEOUT, Endpoint, PacketReader, RdpError,
                   base_url, encode_packet)

EVENT_QUEUE_CAP = 200


def open_socket(host: str, port: int, timeout: float) -> socket.socket:
    """The one place a TCP socket is created (tests inject their own opener)."""
    return socket.create_connection((host, int(port)), timeout=timeout)


class RdpConnection:
    """A live DevTools socket: greeting, requests, events, reconnects."""

    def __init__(self, endpoint: Endpoint, timeout: float = DEFAULT_TIMEOUT,
                 opener: Optional[Callable] = None) -> None:
        self.endpoint = endpoint
        self.timeout = float(timeout)
        self.greeting: dict = {}
        self.events: List[dict] = []
        self.ready = False
        self._sock: Optional[socket.socket] = None
        self._reader: Optional[PacketReader] = None
        self._open = opener or open_socket

    # ── lifecycle ────────────────────────────────────────────────────────

    def connect(self, greeting_wait: float = GREETING_TIMEOUT) -> "RdpConnection":
        """Open the socket and drain the greeting (idempotent).

        `greeting_wait` is how long the greeting may take. The default is a fraction of a
        second — a DevTools server answers at once, so silence means "not an RDP port".
        Firefox waiting on its "Allow connection?" dialog is the one case that deserves
        seconds, and `session.ALLOW_WAIT` is where that number lives (round 11).
        """
        if self.ready:
            return self
        try:
            self._sock = self._open(self.endpoint.host, self.endpoint.port, self.timeout)
        except OSError as e:
            raise RdpError(f"{base_url(self.endpoint)} — {e}", "transport") from e
        self._reader = PacketReader(self._sock, self.timeout)
        self.ready = True
        self.greeting = self._read_greeting(greeting_wait)
        return self

    def _read_greeting(self, greeting_wait: float = GREETING_TIMEOUT) -> dict:
        """The root form; a silent endpoint costs one short wait, never a hang."""
        try:
            packet = self._reader.read_packet(greeting_wait)
        except RdpError:
            return {}
        if str(packet.get("from") or "") == "root" and not packet.get("error"):
            return packet
        self.events.append(packet)
        return {}

    def close(self) -> None:
        """Drop the socket (idempotent) — the browser keeps running."""
        if self._reader is not None:
            self._reader.close()
        try:
            if self._sock is not None:
                self._sock.close()
        except Exception:
            pass
        self._sock = None
        self._reader = None
        self.ready = False

    # ── packets ──────────────────────────────────────────────────────────

    def send(self, packet: dict) -> None:
        """Write one packet (no reply is expected by this call)."""
        if not self.ready or self._sock is None:
            raise RdpError("not connected", "transport")
        try:
            self._sock.sendall(encode_packet(packet))
        except OSError as e:
            raise RdpError(f"send failed: {e}", "transport") from e

    def read(self, timeout=None) -> dict:
        """One packet, whatever it is."""
        if self._reader is None:
            raise RdpError("not connected", "transport")
        return self._reader.read_packet(timeout if timeout is not None else self.timeout)

    def _queue_event(self, packet: dict) -> bool:
        """Queue an unsolicited push; True when it was one."""
        if not actors.is_event(packet):
            return False
        self._queue(packet)
        return True

    def _queue(self, packet: dict) -> None:
        self.events.append(packet)
        if len(self.events) > EVENT_QUEUE_CAP:
            del self.events[:-EVENT_QUEUE_CAP]

    def request(self, packet: dict, timeout=None) -> dict:
        """Send a packet and return its reply (events are queued, errors raised).

        A failed request answers `{"error": "noSuchActor", …}` on the same slot as
        a reply, so the check lives here — one place, and every caller gets a
        typed `RdpError` whose `kind` is the server's own error name.
        """
        self.send(packet)
        reply = self.wait_response(timeout)
        error = actors.packet_error(reply)
        if error:
            raise RdpError(error, error.split(":", 1)[0].strip())
        return reply

    def wait_response(self, timeout=None) -> dict:
        """The next packet that is a reply rather than an event."""
        while True:
            packet = self.read(timeout)
            if not self._queue_event(packet):
                return packet

    def wait_for(self, predicate: Callable[[dict], bool], timeout=None) -> dict:
        """Wait for a packet a predicate accepts; everything else is queued."""
        while True:
            packet = self.read(timeout)
            if predicate(packet):
                return packet
            self._queue(packet)

    def drain_events(self) -> List[dict]:
        """Everything pushed since the last drain (clears the queue)."""
        out, self.events = self.events, []
        return out
