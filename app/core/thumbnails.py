"""Thumbnails — base64 data URLs for queue thumbs and image preview.

Why data URLs: Qt WebEngine blocks (or mangles) `file://` URLs built from
raw Windows paths (`F:\\...` + spaces), so the queue thumb `<img>` and the
preview frame can never load local files directly. The bridge serves small
JPEG data URLs instead; the frontend fetches each image once and caches it.

Cache key includes mtime_ns so re-processed outputs refresh automatically.
"""
from __future__ import annotations

import base64
import functools
import io
import os

THUMB_SIDE = 96
THUMB_QUALITY = 65
PREVIEW_SIDE = 1200
PREVIEW_QUALITY = 80


def _render_jpeg(path_str: str, max_side: int, quality: int) -> bytes:
    """Render path to JPEG bytes bounded by max_side. Raises on failure."""
    from PIL import Image, ImageOps

    with Image.open(path_str) as im:
        im = ImageOps.exif_transpose(im)
        im.thumbnail((max_side, max_side))
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality)
        return buf.getvalue()


@functools.lru_cache(maxsize=1024)
def _cached_thumb(path_str: str, mtime_ns: int) -> bytes:
    return _render_jpeg(path_str, THUMB_SIDE, THUMB_QUALITY)


@functools.lru_cache(maxsize=4)
def _cached_preview(path_str: str, mtime_ns: int) -> bytes:
    return _render_jpeg(path_str, PREVIEW_SIDE, PREVIEW_QUALITY)


def image_data_url(path: object, kind: str = "thumb") -> str:
    """Base64 data URL for path, or "" when missing/unreadable.

    kind: "thumb" (96px, cheap, cached for whole queues) or "preview"
    (1200px, on-demand single image). Unknown kind falls back to thumb.
    """
    try:
        path_str = os.fspath(path)
        mtime_ns = os.stat(path_str).st_mtime_ns
    except (TypeError, ValueError, OSError):
        return ""
    try:
        if kind == "preview":
            raw = _cached_preview(path_str, mtime_ns)
        else:
            raw = _cached_thumb(path_str, mtime_ns)
    except Exception:
        return ""
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")
