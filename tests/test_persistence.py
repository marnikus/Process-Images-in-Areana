from pathlib import Path
import tempfile
import json
from app.core.models import AppState, UrlRow, ImageItem
from app.core.persistence import load_state, save_state, save_preset, load_preset, reconcile_with_filesystem
from app.core.enums import ImageStatus

def test_save_load_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "app_state.json"
        state = AppState()
        state.urls.append(UrlRow.create("https://arena.ai/c/test"))
        state.folder["root_path"] = "/tmp"
        state.prompt["user_prompt"] = "Test prompt"
        save_state(state, path)
        assert path.exists()
        loaded = load_state(path)
        assert len(loaded.urls) == 1
        assert loaded.urls[0].url == "https://arena.ai/c/test"
        assert loaded.prompt["user_prompt"] == "Test prompt"

def test_atomic_write_no_corruption():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "state.json"
        state = AppState()
        state.urls.append(UrlRow.create("https://example.com"))
        save_state(state, path)
        # Overwrite
        state.urls.append(UrlRow.create("https://example2.com"))
        save_state(state, path)
        loaded = load_state(path)
        assert len(loaded.urls) == 2

def test_preset_save_load():
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "state.json"
        preset_path = Path(tmp) / "preset.json"
        state = AppState()
        state.urls.append(UrlRow.create("https://arena.ai/c/test"))
        state.prompt["user_prompt"] = "Hello"
        save_state(state, state_path)
        save_preset(state, preset_path)
        assert preset_path.exists()
        data = load_preset(preset_path)
        assert "urls" in data
        assert "prompt" in data
        assert "settings" in data
        assert "images" not in data  # preset should not contain images
        assert "jobs" not in data

def test_reconcile_filesystem():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.png").write_bytes(b"data")
        (root / "b.jpg").write_bytes(b"data2")

        state = AppState()
        state.folder["root_path"] = str(root)
        # Simulate previous scan with one file
        from app.core.scanner import scan_folder
        scanned = scan_folder(root)
        # Create ImageItems
        for s in scanned:
            state.images.append(ImageItem.from_scan_dict(s, selected=True))

        # Add a fake image that no longer exists
        fake = ImageItem(
            id="fake",
            relative_path="missing.png",
            absolute_path=str(root / "missing.png"),
            filename="missing.png",
            base_name="missing",
            extension=".png",
            size=100,
            mtime=0,
            fingerprint="fake",
            status=ImageStatus.PENDING.value,
            selected=True,
        )
        state.images.append(fake)

        # Now reconcile
        result = reconcile_with_filesystem(state, root)
        # Should detect removed? Our reconcile marks missing as skipped, not removed from list? Actually it marks skipped
        # Check that fake is marked skipped
        fake_after = next((i for i in state.images if i.relative_path == "missing.png"), None)
        assert fake_after is not None
        assert fake_after.status == ImageStatus.SKIPPED.value

def test_load_nonexistent_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "nonexistent.json"
        state = load_state(path)
        assert isinstance(state, AppState)
        assert len(state.urls) == 0
