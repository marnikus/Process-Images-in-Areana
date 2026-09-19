from pathlib import Path
import tempfile
import pytest
from app.core.naming import get_output_path, atomic_write_bytes, is_ai_generated_filename

@pytest.mark.unit
def test_output_path_basic():
    src = Path("/tmp/images/photo.jpg")
    out = get_output_path(src, suffix="_AI", opts={"preserve_format": True, "overwrite": False, "downloaded_ext": None})
    assert out.name == "photo_AI.jpg"
    assert out.parent == src.parent

@pytest.mark.unit
def test_output_path_preserve_downloaded_format():
    src = Path("/tmp/images/photo.jpg")
    out = get_output_path(src, suffix="_AI", opts={"preserve_format": True, "overwrite": False, "downloaded_ext": ".png"})
    assert out.suffix == ".png"
    assert out.name == "photo_AI.png"

@pytest.mark.unit
def test_output_path_unique_suffix():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "image.png"
        src.write_bytes(b"src")
        # Create existing output
        existing = root / "image_AI.png"
        existing.write_bytes(b"existing")
        out = get_output_path(src, suffix="_AI", opts={"overwrite": False})
        assert out.name == "image_AI_2.png"
        # Create second existing
        (root / "image_AI_2.png").write_bytes(b"existing2")
        out2 = get_output_path(src, suffix="_AI", opts={"overwrite": False})
        assert out2.name == "image_AI_3.png"

@pytest.mark.unit
def test_output_path_overwrite():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "image.png"
        src.write_bytes(b"src")
        existing = root / "image_AI.png"
        existing.write_bytes(b"existing")
        out = get_output_path(src, suffix="_AI", opts={"overwrite": True})
        assert out.name == "image_AI.png"

@pytest.mark.unit
def test_never_overwrite_source():
    src = Path("/tmp/images/photo.jpg")
    out = get_output_path(src, suffix="_AI")
    assert out != src
    assert "_AI" in out.stem

@pytest.mark.unit
def test_is_ai_generated():
    assert is_ai_generated_filename(Path("photo_AI.png")) is True
    assert is_ai_generated_filename(Path("photo_AI_2.jpg")) is True
    assert is_ai_generated_filename(Path("photo.png")) is False
    assert is_ai_generated_filename(Path("my_AI_image.png")) is False  # contains but not ends? Our function checks _AI_ also, so my_AI_image would be false, but photo_AI_2 true because _AI_ in stem
    assert is_ai_generated_filename(Path("test_AI_3.png")) is True

@pytest.mark.unit
def test_atomic_write():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        final = root / "output.png"
        data = b"fake png data"
        result = atomic_write_bytes(root, final, data)
        assert result == final
        assert final.exists()
        assert final.read_bytes() == data
        # Ensure no partial left
        partials = list(root.glob("*.partial_*"))
        assert len(partials) == 0
