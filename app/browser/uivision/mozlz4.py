"""Mozilla's `.jsonlz4` session files — magic + size + LZ4 block, no new dependency.

Modern Firefox (since v33, 2014) stopped writing plain `recovery.json` and
compresses its session backups instead — `sessionstore-backups/recovery.
jsonlz4` (the live session, rewritten every ~15s), `previous.jsonlz4`, and
`sessionstore.jsonlz4` in the profile root. The format is one small header
plus a raw LZ4 block::

    [8 bytes: b"mozLz40\\0"] [4 bytes LE: uncompressed size] [LZ4 block …]

so the old "read recovery.json" eye saw nothing on any current Firefox —
that is why the detect phase reported zero tabs while four windows stood
open. Decompression prefers the `lz4` package when it happens to be
installed, else a vendored pure-Python LZ4 block decoder (the block format
is ~15 years stable), so the owner's Windows box needs no compiler and no
new pip package. Every refusal answers None, never an exception.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

MAGIC = b"mozLz40\x00"
HEADER_LEN = 12  # magic (8) + uncompressed size (4)


def decompress_block(block: bytes) -> bytes:
    """One raw LZ4 block → the bytes (pure Python; raises ValueError if torn)."""
    out = bytearray()
    pos, end = 0, len(block)
    while pos < end:
        token = block[pos]
        pos += 1
        pos = _copy_literals(block, pos, end, out, token >> 4)
        if pos >= end:
            break                                     # last sequence holds no match
        offset, pos = _read_offset(block, pos, end, len(out))
        length, pos = _extra_length(block, pos, end, token & 0x0F)
        for _ in range(length + 4):
            out.append(out[len(out) - offset])        # overlapping copy is legal
    return bytes(out)


def _extra_length(block: bytes, pos: int, end: int, base: int) -> tuple:
    """(total length, end pos) — 15 opens the 255-continued extension bytes."""
    total = base
    if base == 15:
        while True:
            if pos >= end:
                raise ValueError("torn LZ4 block: truncated length")
            byte = block[pos]
            pos += 1
            total += byte
            if byte != 255:
                break
    return total, pos


def _copy_literals(block: bytes, pos: int, end: int, out: bytearray, base: int) -> int:
    """Append the sequence's literals; returns the position past them."""
    total, pos = _extra_length(block, pos, end, base)
    if pos + total > end:
        raise ValueError("torn LZ4 block: truncated literals")
    out += block[pos:pos + total]
    return pos + total


def _read_offset(block: bytes, pos: int, end: int, have: int) -> tuple:
    """(match offset, end pos) — zero or beyond the output is a torn block."""
    if pos + 2 > end:
        raise ValueError("torn LZ4 block: truncated match offset")
    offset = block[pos] | (block[pos + 1] << 8)
    if offset == 0 or offset > have:
        raise ValueError("torn LZ4 block: bad match offset")
    return offset, pos + 2


def _decompress_lib(payload: bytes, size: int):
    """The `lz4` package's answer, or None when absent or refusing."""
    try:
        import lz4.block
    except ImportError:
        return None
    try:
        return bytes(lz4.block.decompress(payload, uncompressed_size=size))
    except Exception:
        return None


def decompress(data: bytes) -> bytes:
    """One `.jsonlz4` file's bytes → the raw JSON bytes (ValueError when torn)."""
    blob = bytes(data or b"")
    if blob[:8] != MAGIC:
        raise ValueError("not a mozLz4 file: bad magic")
    if len(blob) < HEADER_LEN:
        raise ValueError("not a mozLz4 file: truncated header")
    size = struct.unpack_from("<I", blob, 8)[0]
    raw = _decompress_lib(blob[HEADER_LEN:], size)
    if raw is None:
        raw = decompress_block(blob[HEADER_LEN:])
    if len(raw) != size:
        raise ValueError(f"torn mozLz4 file: header says {size} bytes, got {len(raw)}")
    return raw


def read_session_file(path) -> dict | None:
    """The session document at `path` (`.jsonlz4` or legacy `.json`), else None."""
    try:
        blob = Path(path).read_bytes()
    except OSError:
        return None                                   # gone, locked — best effort
    if blob[:8] == MAGIC:
        try:
            blob = decompress(blob)
        except ValueError:
            return None                               # torn file, never an error
    try:
        doc = json.loads(blob.decode("utf-8", errors="replace"))
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None
