"""The mozLZ4a decoder: literals, back-references, refusals (RULE 4/8)."""

import json
import struct

import pytest

from app.browser.uivision import lz4

pytestmark = pytest.mark.unit


def literals_block(payload: bytes) -> bytes:
    """A valid LZ4 block of pure literals (no matches)."""
    head = 15 if len(payload) >= 15 else len(payload)
    out = bytes([head << 4])
    rem = len(payload) - head
    if head == 15:
        while rem >= 255:
            out += b"\xff"
            rem -= 255
        out += bytes([rem])
    return out + payload


def container(payload: bytes, block=None) -> bytes:
    return lz4.MAGIC + struct.pack("<I", len(payload)) + (block or literals_block(payload))


def test_roundtrip_literals_small_and_big():
    for payload in (b"[]", b'{"windows": []}', bytes(range(200)) * 3):
        assert lz4.decompress(container(payload)) == payload


def test_roundtrip_back_reference():
    block = bytes([4 << 4 | 15]) + b"abcd" + bytes([4, 0, 96 - 4 - 15])
    assert lz4.decompress(container(b"abcd" * 25, block)) == b"abcd" * 25


def test_refusals_are_named_not_silent():
    with pytest.raises(ValueError):
        lz4.decompress(b"notmozlz4" + b"\x00" * 8)
    with pytest.raises(ValueError):
        lz4.decompress(lz4.MAGIC)                      # header truncated


def test_real_json_document_survives():
    doc = {"windows": [{"tabs": [{"entries": [{"url": "https://arena.ai", "title": "A"}]}]}]}
    blob = container(json.dumps(doc).encode())
    assert json.loads(lz4.decompress(blob)) == doc
