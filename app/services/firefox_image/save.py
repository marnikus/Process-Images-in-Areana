"""Validate downloaded bytes and save them beside the source (I-65, RULE 15/23).

Reuses the Chrome validators and `atomic_write_bytes`. Disk full, access
denied and a failed rename stay named failures — nothing is marked completed.

Imports: core naming + services verification (same layer / core).
"""

from __future__ import annotations

import errno
from pathlib import Path

from app.core.naming import OutputSpec, atomic_write_bytes, get_output_path
from app.services.verification import (
    _check_empty,
    _check_html,
    _check_magic_bytes,
    _try_pil_validation,
)

_EXT = {"png": ".png", "jpg": ".jpg", "jpeg": ".jpg", "webp": ".webp", "bmp": ".bmp"}


def image_problem(data: bytes) -> str:
    """'' when the bytes are a real image; HTML and corrupt are named."""
    for check in (_check_empty, _check_html):
        bad = check(data or b"")
        if bad:
            return bad.error
    magic = _check_magic_bytes(data or b"")
    if magic and magic.valid:
        return ""
    pil = _try_pil_validation(data or b"", "")
    if pil.valid:
        return ""
    return pil.error or "corrupt image"


def ext_of(data: bytes) -> str:
    """Extension from the magic bytes; `.png` when the format is unnamed."""
    magic = _check_magic_bytes(data or b"")
    if not magic or not magic.valid:
        return ".png"
    return _EXT.get(str(magic.metadata.get("format") or ""), ".png")


def save_error_name(exc: OSError) -> str:
    """Disk full, access denied, or a failed atomic rename — three answers."""
    code = getattr(exc, "errno", None)
    if code in (errno.ENOSPC, 28):
        return "disk full"
    if code in (errno.EACCES, errno.EPERM, 13):
        return "access denied"
    return "atomic rename failure"


def output_spec(bridge, ext: str) -> OutputSpec:
    """The image's output settings, or the defaults when the bridge has none."""
    settings = getattr(getattr(bridge, "state", None), "settings", None)
    raw = getattr(settings, "output", None) or {}
    if not isinstance(raw, dict):
        raw = {}
    return OutputSpec(suffix=raw.get("suffix", "_AI"),
                      preserve_format=raw.get("preserve_format", True),
                      overwrite=bool(raw.get("overwrite", False)),
                      downloaded_ext=ext,
                      unique_template=raw.get("unique_suffix_template", "{base}_AI_{n}{ext}"))


def write_output(bridge, source: str, data: bytes) -> Path:
    """Atomic `*_AI` beside the source. Raises OSError on disk failure."""
    dest = get_output_path(Path(source), output_spec(bridge, ext_of(data)))
    return atomic_write_bytes(dest.parent, dest, data)
