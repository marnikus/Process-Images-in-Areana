"""Mozilla's `.jsonlz4` session files — magic + size + LZ4 block (I-63).

RULE 8: hand-built LZ4 blocks (literals, matches, extended lengths, torn
tails) pin the vendored decoder byte for byte; no Firefox and no `lz4`
package needed — the `lz4` round trip runs only where it is installed.
"""

import json

import pytest

from app.browser.uivision import mozlz4

pytestmark = pytest.mark.unit


def literals_block(raw: bytes) -> bytes:
    """One match-free LZ4 block (the test fixture's tiny encoder)."""
    out = bytearray()
    rest = len(raw)
    if rest <= 15:
        out.append(rest << 4)
    else:
        out.append(0xF0)
        rest -= 15
        while rest >= 255:
            out.append(255)
            rest -= 255
        out.append(rest)
    out += raw
    return bytes(out)


def packed(doc) -> bytes:
    """One `.jsonlz4` file's bytes for a JSON document."""
    raw = json.dumps(doc).encode("utf-8")
    return mozlz4.MAGIC + len(raw).to_bytes(4, "little") + literals_block(raw)


def test_decompress_block_copies_literals():
    assert mozlz4.decompress_block(b"\x20hi") == b"hi"
    assert mozlz4.decompress_block(b"\x00") == b""
    assert mozlz4.decompress_block(b"") == b""


def test_decompress_block_replays_matches_with_overlap():
    assert mozlz4.decompress_block(b"\x20ab\x02\x00") == b"ababab"
    assert mozlz4.decompress_block(b"\x4fabcd\x04\x00\x01") == b"abcd" * 6


def test_decompress_block_reads_extended_lengths():
    assert mozlz4.decompress_block(b"\xf0\x05" + b"x" * 20) == b"x" * 20


def test_decompress_block_refuses_torn_input():
    for torn in (b"\xf0",                    # truncated length extension
                 b"\x20h",                   # 2 literals promised, 1 present
                 b"\x10a\x00\x00",           # zero match offset
                 b"\x10a\x09\x00",           # offset beyond the output
                 b"\x10a\x01"):              # truncated match offset
        with pytest.raises(ValueError, match="[Tt]orn"):
            mozlz4.decompress_block(torn)


def test_decompress_checks_magic_header_and_size():
    raw = b'{"w": []}'
    assert len(raw) < 15
    blob = mozlz4.MAGIC + len(raw).to_bytes(4, "little") + literals_block(raw)
    assert mozlz4.decompress(blob) == raw
    with pytest.raises(ValueError, match="[Mm]agic"):
        mozlz4.decompress(b"nope" + blob[4:])
    with pytest.raises(ValueError, match="[Tt]runcated"):
        mozlz4.decompress(mozlz4.MAGIC + b"\x01")
    with pytest.raises(ValueError, match="[Tt]orn"):
        mozlz4.decompress(blob[:-2])          # the size header still promises all


def test_read_session_file_answers_dict_or_none(tmp_path):
    doc = {"windows": [{"tabs": [{"entries": [{"url": "https://arena.ai", "title": "A"}]}]}]}
    bundle = tmp_path / "recovery.jsonlz4"
    bundle.write_bytes(packed(doc))
    assert mozlz4.read_session_file(bundle) == doc
    plain = tmp_path / "recovery.json"
    plain.write_text(json.dumps(doc), encoding="utf-8")
    assert mozlz4.read_session_file(plain) == doc
    assert mozlz4.read_session_file(tmp_path / "gone.jsonlz4") is None
    torn = tmp_path / "torn.jsonlz4"
    torn.write_bytes(mozlz4.MAGIC + b"\xff\x00\x00\x00oops")
    assert mozlz4.read_session_file(torn) is None
    listed = tmp_path / "list.json"
    listed.write_text("[1, 2]", encoding="utf-8")
    assert mozlz4.read_session_file(listed) is None


def test_decompress_round_trips_the_lz4_package_when_installed():
    lz4_block = pytest.importorskip("lz4.block")
    raw = b'{"windows": [{"tabs": []}]}' * 40
    blob = mozlz4.MAGIC + len(raw).to_bytes(4, "little")
    blob += lz4_block.compress(raw, store_size=False)
    assert mozlz4.decompress(blob) == raw
