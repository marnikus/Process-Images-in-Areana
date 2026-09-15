import base64
import io
import os
import tempfile
from pathlib import Path

from PIL import Image

from app.core.thumbnails import image_data_url, THUMB_SIDE, PREVIEW_SIDE


def _make_image(path: Path, size=(400, 300), mode="RGB", color=(200, 30, 30)):
    img = Image.new(mode, size, color)
    img.save(path, "PNG")
    return path


def _decode(url: str) -> Image.Image:
    assert url.startswith("data:image/jpeg;base64,")
    return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))


def test_thumb_is_small_jpeg_data_url():
    with tempfile.TemporaryDirectory() as tmp:
        p = _make_image(Path(tmp) / "photo.png")
        url = image_data_url(p, "thumb")
        im = _decode(url)
        assert im.format == "JPEG"
        assert max(im.size) <= THUMB_SIDE
        assert len(url) < 20000  # cheap enough to serve per queue row


def test_preview_is_larger_than_thumb():
    with tempfile.TemporaryDirectory() as tmp:
        p = _make_image(Path(tmp) / "photo.png", size=(2000, 1500))
        thumb = _decode(image_data_url(p, "thumb"))
        preview = _decode(image_data_url(p, "preview"))
        assert max(preview.size) > max(thumb.size)
        assert max(preview.size) <= PREVIEW_SIDE


def test_rgba_converts_to_jpeg():
    with tempfile.TemporaryDirectory() as tmp:
        p = _make_image(Path(tmp) / "alpha.png", mode="RGBA", color=(10, 20, 30, 128))
        im = _decode(image_data_url(p))
        assert im.format == "JPEG"


def test_unknown_kind_falls_back_to_thumb():
    with tempfile.TemporaryDirectory() as tmp:
        p = _make_image(Path(tmp) / "photo.png")
        im = _decode(image_data_url(p, "bogus"))
        assert max(im.size) <= THUMB_SIDE


def test_missing_file_returns_empty():
    assert image_data_url("/nonexistent/dir/nope.png") == ""
    assert image_data_url(None) == ""
    assert image_data_url("") == ""


def test_non_image_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "note.txt"
        p.write_text("not an image")
        assert image_data_url(p) == ""


def test_changed_file_refreshes_cache():
    with tempfile.TemporaryDirectory() as tmp:
        p = _make_image(Path(tmp) / "photo.png", color=(255, 0, 0))
        first = image_data_url(p)
        # rewrite with different pixels + bumped mtime so cache key changes
        _make_image(p, color=(0, 0, 255))
        ns = os.stat(p).st_mtime_ns + 2_000_000_000
        os.utime(p, ns=(ns, ns))
        second = image_data_url(p)
        assert first and second and first != second
