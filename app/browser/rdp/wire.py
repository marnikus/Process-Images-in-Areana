"""RDP wire codec — the `<length>:<JSON>` framing Firefox's DevTools speaks.

The prefix counts **UTF-16 code units** of the JSON body, and the body travels
as UTF-8 (so a page title with a Cyrillic letter or an emoji makes the byte
count larger than the prefix). A client that counts bytes desynchronizes the
stream the first time that happens, so this reader:

* reads exactly the declared number of bytes (a timeout-mode socket may hand
  back a partial read, so "exactly" is a loop, not one `read()` call);
* when the body is still incomplete after that — a server that counted UTF-16
  units while we read bytes — keeps reading until the JSON closes, and the
  *rest* of what it read goes back into the buffer, so an over-eager prefix
  cannot swallow the next packet;
* hands the leftovers of one packet to the next `read_packet`.

The module also owns the names everything else in the app uses: `Endpoint` (the
one socket of a browser), `tab_handle` (how a tab is remembered across attaches)
and `RdpError` (the typed failure; `kind` is `protocol` / `transport` /
`timeout` / a server error such as `noSuchActor`).

RULE 18: file ≤300, func ≤30, CC ≤10, cognitive ≤15, ≤3 params.
"""

from __future__ import annotations

import json
import select
from typing import NamedTuple

PROTOCOL = "rdp"          # the protocol name this codec speaks (see protocols.py)
DEFAULT_TIMEOUT = 5.0
GREETING_TIMEOUT = 0.6    # the root form arrives at once, or the endpoint is not RDP
READ_CHUNK = 4096


class RdpError(RuntimeError):
    """A typed RDP failure — never raised for something the caller can ignore."""

    def __init__(self, message: str, kind: str = "protocol") -> None:
        super().__init__(message)
        self.kind = kind


class Endpoint(NamedTuple):
    """One browser's DevTools socket: host + port (every tab rides it)."""

    host: str
    port: int


def base_url(point: Endpoint) -> str:
    """How the panel names this socket (`tcp://host:port` — there is no path)."""
    return f"tcp://{point.host}:{point.port}"


def tab_handle(point: Endpoint, tab_id: str) -> str:
    """The handle a tab is known by in the app: host:port + the tab's stable id.

    RDP has ONE socket per browser, so this is not a connectable URL — it is how
    a row remembers which tab it belongs to across attach/detach cycles (and why
    the tab picker refuses it by name instead of trying to dial it).
    """
    return f"rdp://{point.host}:{point.port}/{tab_id}"


def utf16_len(text: str) -> int:
    """Firefox's prefix counts UTF-16 code units, not characters and not bytes."""
    return sum(1 if ord(ch) <= 0xFFFF else 2 for ch in text)


def encode_packet(payload: dict) -> bytes:
    """One client packet, framed the way the browser expects it."""
    text = json.dumps(payload, ensure_ascii=False)
    return f"{utf16_len(text)}:{text}".encode("utf-8")


def decode_packet(body: bytes) -> dict:
    """A packet body (prefix already stripped) as a dict — typed error otherwise."""
    try:
        packet = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise RdpError(f"invalid packet body: {e}", "protocol") from e
    if not isinstance(packet, dict):
        raise RdpError(f"packet is not a JSON object ({type(packet).__name__})", "protocol")
    return packet


class PacketReader:
    """Reads framed packets from a socket (or any file-like), one deadline per call.

    The reader owns a buffer rather than a `socket.makefile`: a socket file
    object that has once timed out is permanently unusable in CPython ("cannot
    read from timed out object"), and the greeting probe deliberately times out.
    Reading straight off the socket with `select` keeps every deadline local.
    """

    def __init__(self, source, timeout=None) -> None:
        self._source = source
        self._timeout = timeout
        self._pending = b""
        self._deadline = timeout
        self._recv = getattr(source, "recv", None)

    def _pull(self, size: int) -> bytes:
        """One read from the socket/file, waiting at most `self._deadline`.

        A closed source is a typed error, not an empty packet: `select` raises
        `ValueError` on a closed socket, and a peer that ended the stream makes
        `recv` answer b"" — both mean the same thing to every caller here.
        """
        if self._recv is None:
            return self._source.read(size) or b""
        try:
            ready, _, _ = select.select([self._source], [], [], self._deadline)
        except (ValueError, OSError) as e:
            raise RdpError(f"connection closed by the browser ({e})", "transport") from e
        if not ready:
            raise RdpError(f"timeout waiting for the browser ({self._deadline}s)", "timeout")
        return self._recv(size)

    def _read(self, size: int) -> bytes:
        """Exactly `size` bytes (buffered leftovers first) or a typed error."""
        out, self._pending = self._pending[:size], self._pending[size:]
        while len(out) < size:
            chunk = self._pull(size - len(out))
            if not chunk:
                where = "closed by the browser" if not out else "closed mid-packet"
                raise RdpError(f"connection {where}", "transport")
            out += chunk
        return out

    def _more(self) -> bytes:
        """What is available now for a body longer than its prefix promised.

        At most one read: 10 bytes were short of the JSON above, and waiting for
        a full chunk would block even though the rest had already arrived.
        """
        return self._pull(READ_CHUNK)

    def _prefix(self) -> int:
        """The declared body size, one byte at a time (it is a few digits)."""
        digits = b""
        while not digits.endswith(b":"):
            digits += self._read(1)
            if len(digits) > 12:
                raise RdpError(f"invalid length prefix {digits[:12]!r}", "protocol")
        number = digits[:-1]
        if not number.isdigit():
            raise RdpError(f"invalid length prefix {digits[:12]!r}", "protocol")
        return int(number)

    def _json_body(self, declared: int) -> dict:
        """The declared bytes, extended until the JSON closes; leftovers buffered."""
        raw = self._read(declared)
        decoder = json.JSONDecoder()
        while True:
            text = raw.decode("utf-8", errors="ignore")
            try:
                packet, end = decoder.raw_decode(text)
            except ValueError:
                more = self._more()
                if not more:
                    raise RdpError("truncated packet (socket ended mid-JSON)", "transport")
                raw += more
                continue
            if not isinstance(packet, dict):
                raise RdpError(f"packet is not a JSON object ({type(packet).__name__})", "protocol")
            self._pending = text[end:].encode("utf-8") + self._pending
            return packet

    def close(self) -> None:
        """Release the reader's source (a socket is closed by its owner too)."""
        try:
            self._source.close()
        except Exception:
            pass

    def read_packet(self, timeout=None) -> dict:
        """One packet; a closed socket, a bad prefix or a timeout raises RdpError."""
        self._deadline = self._timeout if timeout is None else timeout
        try:
            return self._json_body(self._prefix())
        except RdpError:
            raise
        except OSError as e:
            raise RdpError(f"transport: {e}", "transport") from e
