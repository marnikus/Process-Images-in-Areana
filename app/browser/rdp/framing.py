"""Firefox RDP wire codec — `<byte-length>:<json>` framing (pure, no I/O).

The DevTools Remote Debugging Protocol frames every packet as the **byte**
length of the UTF-8 JSON, a colon, then the JSON itself::

    34:{ "to":"root", "type":"listTabs" }

Two properties of this protocol drive the whole client and live here as
named predicates, because getting them wrong is silent and expensive:

* **No request ids.** A reply carries only `from`. Correlating by `from`
  alone is wrong: the same actor also pushes unsolicited *events*. The
  discriminator is shape — a direct response sets **no** `type` key, an
  event always does (`is_reply_from` / `is_event`).
* **Length is bytes, not characters.** A non-ASCII selector makes
  `len(str)` disagree with the frame; the prefix must count encoded bytes.

Layer: browser leaf — pure functions, no sockets, no Qt, no app imports.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

__all__ = ["encode_packet", "decode_packets", "is_event", "is_reply_from",
           "FramingError", "MAX_PACKET_BYTES"]

MAX_PACKET_BYTES = 64 * 1024 * 1024  # a frame this big means a desynced stream, not a real packet


class FramingError(ValueError):
    """The byte stream is not valid RDP framing (RULE 4: broken, not empty)."""


def encode_packet(packet: Dict[str, Any]) -> bytes:
    """Serialise one packet to `<byte-length>:<json>`."""
    body = json.dumps(packet, separators=(",", ":")).encode("utf-8")
    return str(len(body)).encode("ascii") + b":" + body


def _split_header(buffer: bytes) -> Tuple[int, int]:
    """(payload length, header size) of the leading frame; (-1, 0) when incomplete."""
    sep = buffer.find(b":")
    if sep < 0:
        if len(buffer) > 32:  # a colon must arrive within a few digits
            raise FramingError("no length prefix in stream")
        return -1, 0
    digits = buffer[:sep]
    if not digits.isdigit():
        raise FramingError(f"bad length prefix {digits[:32]!r}")
    size = int(digits)
    if size > MAX_PACKET_BYTES:
        raise FramingError(f"frame of {size} bytes exceeds the sanity cap")
    return size, sep + 1


def decode_packets(buffer: bytes) -> Tuple[List[Dict[str, Any]], bytes]:
    """Drain every whole frame; return (packets, the still-incomplete tail).

    A partial frame is normal on a stream socket — it is kept, never raised.
    """
    out: List[Dict[str, Any]] = []
    while buffer:
        size, head = _split_header(buffer)
        if size < 0 or len(buffer) < head + size:
            break
        body = buffer[head:head + size]
        buffer = buffer[head + size:]
        try:
            out.append(json.loads(body.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise FramingError(f"undecodable frame: {e}") from e
    return out, buffer


def is_event(packet: Dict[str, Any]) -> bool:
    """Unsolicited push (it carries `type`), not an answer to our request."""
    return bool(packet) and "type" in packet


def is_reply_from(packet: Dict[str, Any], actor: str) -> bool:
    """The direct answer of `actor`: right sender **and** no `type` key.

    Shape, not just sender — a `consoleAPICall` from the same actor would
    otherwise be mistaken for the reply and consume the wrong packet.
    """
    return bool(actor) and packet.get("from") == actor and not is_event(packet)
