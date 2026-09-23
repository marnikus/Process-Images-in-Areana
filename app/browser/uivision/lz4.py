"""Mozilla's jsonlz4 container: magic + size + one LZ4 block — decoded in pure Python.

Firefox keeps its session store compressed (`sessionstore.jsonlz4`,
`previous.jsonlz4`, older `recovery.jsonlz4`): eight magic bytes (`mozLZ4a` + NUL),
the little-endian decompressed length, then a raw LZ4 block. Reading the open
tab list must work without any debugger and without third-party packages
(owner's rule + RULE 0), so the block decoder lives here — literals and
back-references, nothing else. A refusal (gone, locked, truncated, wrong
magic) answers None, never an exception (RULE 4).
"""

from __future__ import annotations

MAGIC = b"mozLZ4a\x00"   # eight bytes: the seven-char tag plus NUL
_HEADER = 12          # magic (8) + uint32 little-endian decompressed length


def _run_length(blob: bytes, i: int, base: int) -> tuple:
    """(length, next index) for a literal or match length starting at `base`."""
    total = base
    if base != 15:
        return total, i
    while True:
        byte = blob[i]
        i += 1
        total += byte
        if byte != 255:
            return total, i


def _copy_match(out: bytearray, offset: int, length: int) -> None:
    """Append `length` bytes back-referenced by `offset` (byte-by-byte: overlaps)."""
    start = len(out) - offset
    for pos in range(length):
        out.append(out[start + pos])


def _one_sequence(blob: bytes, i: int, out: bytearray) -> int:
    """Decode one token (literals + match); returns the next index (or -1 done)."""
    token = blob[i]
    i += 1
    lit, i = _run_length(blob, i, token >> 4)
    out += blob[i:i + lit]
    i += lit
    if i >= len(blob):
        return -1
    offset = blob[i] | (blob[i + 1] << 8)
    i += 2
    if not offset:
        raise ValueError("lz4 back-reference with offset 0")
    match, i = _run_length(blob, i, token & 15)
    _copy_match(out, offset, match + 4)
    return i


def decompress(blob: bytes) -> bytes:
    """The decompressed payload of one mozLZ4a container (ValueError when junk)."""
    if not blob.startswith(MAGIC) or len(blob) < _HEADER:
        raise ValueError("not a mozLZ4a container")
    out, i = bytearray(), _HEADER
    while 0 <= i < len(blob):
        i = _one_sequence(blob, i, out)
    return bytes(out)
