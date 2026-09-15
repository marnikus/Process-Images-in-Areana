"""Stable source read, SHA-256 and metadata-free thumbnail; never writes source files."""

import base64
import hashlib
import io
import os
import stat
import warnings
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

from image_queue.domain.validation import ContractError


def read_source(path: Path, limit: int) -> tuple[bytes, os.stat_result]:
    if path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400):
        raise ContractError("Links/reparse points are not authorized image sources")
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    )
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise ContractError("Source is not a regular image within the size limit")
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    current = path.lstat()

    def identity(info: os.stat_result) -> tuple[int, int, int, int]:
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)

    if identity(before) != identity(after) or identity(before) != identity(current):
        raise ContractError("Source changed while scanning; rescan before selecting")
    if len(raw) != before.st_size:
        raise ContractError("Source read was incomplete or exceeded size limit")
    return raw, before


def image_metadata(raw: bytes) -> dict[str, Any]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.width * image.height > 40_000_000 or getattr(image, "n_frames", 1) != 1:
                    raise ContractError("Image is too large or animated/multipage")
                if image.format not in ("PNG", "JPEG", "WEBP", "BMP", "TIFF"):
                    raise ContractError("Unsupported image bytes")
                image.verify()
            return _thumbnail(raw)
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        ValueError,
    ) as exc:
        raise ContractError("Image cannot be safely decoded") from exc


def _thumbnail(raw: bytes) -> dict[str, Any]:
    with Image.open(io.BytesIO(raw)) as image:
        size, fmt = image.size, image.format
        thumb = ImageOps.exif_transpose(image).convert("RGB")
        thumb.thumbnail((96, 96))
        clean = Image.new("RGB", thumb.size)
        clean.paste(thumb)
        output = io.BytesIO()
        clean.save(output, format="JPEG", quality=60)
    return {
        "width": size[0],
        "height": size[1],
        "format": fmt,
        "thumbnail": "data:image/jpeg;base64,"
        + base64.b64encode(output.getvalue()).decode("ascii"),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
