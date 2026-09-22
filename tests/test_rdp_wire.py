"""RDP wire codec — `<length>:<JSON>` framing (2026-09-21, round 8).

Firefox's DevTools server prefixes every packet with the **UTF-16 code-unit**
count of the body, not its byte length, and the body travels as UTF-8. A client
that counts bytes desynchronizes the stream the first time a page title contains
anything outside Latin-1 — so the codec is tested in both directions with
Cyrillic and an emoji, against chunked TCP reads and against a server that
counts bytes instead.

RED at `464185a`: `app.browser.rdp` did not exist.
"""

import io
import json
import socket

import pytest

from app.browser.rdp import wire

pytestmark = pytest.mark.unit


def _reader(sock):
    """A reader straight over a socketpair (deadlines are per call)."""
    return wire.PacketReader(sock)


def test_a_packet_round_trips_with_its_utf16_length():
    """The shape the protocol docs quote: 34 UTF-16 units, then the JSON body."""
    payload = {"to": "root", "type": "listTabs"}
    body = '{"to": "root", "type": "listTabs"}'
    assert wire.utf16_len(body) == 34
    encoded = wire.encode_packet(payload)
    assert encoded == f"34:{body}".encode("utf-8")
    assert wire.decode_packet(body.encode("utf-8")) == payload


def test_the_prefix_counts_utf16_units_so_non_latin_bodies_stay_in_sync():
    payload = {"title": "Проверка 🚀", "value": "naïve"}
    body = json.dumps(payload, ensure_ascii=False)
    encoded = wire.encode_packet(payload)
    prefix, text = encoded.split(b":", 1)
    assert int(prefix) == wire.utf16_len(body)
    assert int(prefix) != len(text), "byte length would desynchronize the stream"
    assert wire.decode_packet(text) == payload


def test_packets_split_across_reads_are_reassembled():
    server, client = socket.socketpair()
    try:
        stream = _reader(client)
        blob = wire.encode_packet({"from": "root", "title": "Проверка 🚀"})
        for i in range(0, len(blob), 3):     # drip-feed: one packet, many reads
            server.sendall(blob[i:i + 3])
        assert stream.read_packet(timeout=2.0)["title"] == "Проверка 🚀"
    finally:
        server.close()
        client.close()


def test_a_server_that_counts_bytes_is_still_understood():
    """Tolerant read: accept more bytes than the prefix promised, then resync."""
    server, client = socket.socketpair()
    try:
        stream = _reader(client)
        text = json.dumps({"title": "Проверка 🚀"}, ensure_ascii=False)
        server.sendall(f"{len(text.encode('utf-8'))}:{text}".encode("utf-8"))   # byte-counted
        server.sendall(wire.encode_packet({"from": "root", "type": "tabAttached"}))
        first = stream.read_packet(timeout=2.0)
        assert first["title"] == "Проверка 🚀", "the prefix was short but the packet is complete"
        assert stream.read_packet(timeout=2.0)["type"] == "tabAttached", "and the stream resynced"
    finally:
        server.close()
        client.close()


def test_two_packets_in_one_read_are_kept_apart():
    payload_a = wire.encode_packet({"from": "root", "type": "one"})
    payload_b = wire.encode_packet({"from": "root", "type": "two"})
    stream = wire.PacketReader(io.BytesIO(payload_a + payload_b))
    assert stream.read_packet()["type"] == "one"
    assert stream.read_packet()["type"] == "two"


def test_a_garbage_prefix_or_body_raises_a_typed_error_never_a_hang():
    server, client = socket.socketpair()
    try:
        stream = _reader(client)
        server.sendall(b"12abc:{broken")
        with pytest.raises(wire.RdpError):
            stream.read_packet(timeout=2.0)
    finally:
        server.close()
        client.close()


def test_a_closed_socket_is_a_named_error_not_an_endless_wait():
    server, client = socket.socketpair()
    stream = _reader(client)
    server.close()
    with pytest.raises(wire.RdpError) as exc:
        stream.read_packet(timeout=2.0)
    assert "closed" in str(exc.value).lower() or "eof" in str(exc.value).lower()
    client.close()


def test_a_handle_survives_close_and_reuse_and_never_doubts_its_source():
    """Boundary: reading after `close` is a typed error, not a silent empty packet."""
    server, client = socket.socketpair()
    stream = _reader(client)
    stream.close()
    with pytest.raises(wire.RdpError) as exc:
        stream.read_packet(timeout=1.0)
    assert "closed" in str(exc.value).lower()
    stream.close()          # idempotent
    server.close()


def test_a_body_that_ends_mid_json_is_a_typed_error():
    server, client = socket.socketpair()
    try:
        stream = _reader(client)
        body = b'{"from": "root", "tabs": ['
        server.sendall(f"{len(body)}:".encode() + body)
        server.close()
        with pytest.raises(wire.RdpError) as exc:
            stream.read_packet(timeout=1.0)
        assert "truncated" in str(exc.value).lower(), "the body never closed, and it says so"
    finally:
        client.close()


def test_decoding_a_body_that_is_not_a_json_object_is_refused():
    with pytest.raises(wire.RdpError):
        wire.decode_packet(b'["not", "an", "object"]')
    with pytest.raises(wire.RdpError):
        wire.decode_packet(b"{broken")


def test_the_endpoint_names_one_socket_not_a_tab():
    point = wire.Endpoint("127.0.0.1", 6000)
    assert point.host == "127.0.0.1" and point.port == 6000
    assert wire.base_url(point) == "tcp://127.0.0.1:6000"
