"""Thumbnail Service — pure PIL logic extracted from bridge.py (Phase 2).

Goals:
- No Qt, no signals — pure function Path → data_url.
- Testable with tmp_path, no QApplication.
- RULE 18: file 150-300 LOC ideal, current ~140 LOC.
- RULE 16: func LOC ≤30, CC ≤10, nesting ≤4, params ≤4.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Dict


def _guess_mime(ext: str) -> str:
    mapping = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }
    return mapping.get(ext.lower(), "image/png")


def _normalize_format(fmt: str) -> str:
    f = (fmt or "PNG").upper()
    if f == "JPEG":
        return "JPEG"
    if f not in ("PNG", "JPEG", "WEBP", "GIF"):
        return "PNG"
    return f


def _save_pil_to_buffer(im_pil, fmt: str, quality: int) -> tuple[bytes, str]:
    buf = io.BytesIO()
    if fmt == "PNG":
        im_pil.save(buf, format="PNG")
        return buf.getvalue(), "image/png"
    if fmt == "JPEG":
        from PIL import Image

        if im_pil.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", im_pil.size, (255, 255, 255))
            bg.paste(im_pil, mask=im_pil.split()[-1] if im_pil.mode == "RGBA" else None)
            im_pil = bg
        im_pil.save(buf, format="JPEG", quality=quality)
        return buf.getvalue(), "image/jpeg"
    im_pil.save(buf, format=fmt)
    return buf.getvalue(), f"image/{fmt.lower()}"


def _pil_thumbnail(p: Path, size: int, quality: int) -> Dict:
    from PIL import Image

    with Image.open(p) as im_pil:
        im_pil.thumbnail((size, size))
        fmt = _normalize_format(im_pil.format or "PNG")
        data, mime = _save_pil_to_buffer(im_pil, fmt, quality)
        b64 = base64.b64encode(data).decode("ascii")
        return {"ok": True, "data_url": f"data:{mime};base64,{b64}", "mime": mime}


def _fallback_read(p: Path, e_pil: Exception) -> Dict:
    try:
        data = p.read_bytes()
        if len(data) > 400 * 1024:
            return {"ok": False, "error": f"too large {len(data)} {e_pil}", "fallback_url": f"file://{p}"}
        mime = _guess_mime(p.suffix)
        b64 = base64.b64encode(data).decode("ascii")
        return {"ok": True, "data_url": f"data:{mime};base64,{b64}", "mime": mime, "fallback": True}
    except Exception as e2:
        return {"ok": False, "error": f"{e_pil} / {e2}"}


def generate_thumbnail_data_url(image_path: Path, size: int = 96, quality: int = 80) -> Dict:
    """Generate thumbnail data URL — pure IO, no Qt."""
    p = Path(image_path)
    if not p.exists():
        return {"ok": False, "error": "file not exists", "id": p.name}
    try:
        return _pil_thumbnail(p, size, quality)
    except Exception as e_pil:
        return _fallback_read(p, e_pil)


def is_cache_hit(cache: Dict[str, str], img_id: str) -> bool:
    """Pure cache check."""
    return img_id in cache


def get_cached_thumbnail(cache: Dict[str, str], img_id: str) -> str:
    """Pure cache get."""
    return cache.get(img_id, "")
