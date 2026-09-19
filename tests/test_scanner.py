from pathlib import Path
import tempfile
import pytest
from app.core.scanner import ScanSpec, scan_folder, detect_changes

@pytest.mark.integration
def test_scan_recursive_and_ignore_ai():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "sub").mkdir()
        (root / "a.png").write_bytes(b"pngdata")
        (root / "b.jpg").write_bytes(b"jpgdata")
        (root / "c_AI.png").write_bytes(b"should be ignored")
        (root / "sub" / "d.jpeg").write_bytes(b"jpeg")
        (root / "sub" / "e_AI_2.jpg").write_bytes(b"ignore")
        (root / "sub" / "f.txt").write_bytes(b"not image")

        spec = ScanSpec(supported_exts={".png", ".jpg", ".jpeg", ".webp"}, ignore_ai_suffix=True)
        results = scan_folder(root, spec)
        rel_paths = {r["relative_path"] for r in results}
        assert "a.png" in rel_paths
        assert "b.jpg" in rel_paths
        assert "sub/d.jpeg" in rel_paths
        assert "c_AI.png" not in rel_paths
        assert "sub/e_AI_2.jpg" not in rel_paths
        assert "sub/f.txt" not in rel_paths
        assert len(results) == 3

@pytest.mark.integration
def test_scan_preserve_structure():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a").mkdir()
        (root / "a" / "b").mkdir(parents=True)
        (root / "a" / "b" / "image.png").write_bytes(b"data")
        results = scan_folder(root)
        assert results[0]["relative_path"] == "a/b/image.png"

@pytest.mark.integration
def test_detect_changes():
    prev = [
        {"relative_path": "a.png", "size": 100, "mtime": 1},
        {"relative_path": "b.jpg", "size": 200, "mtime": 2},
    ]
    curr = [
        {"relative_path": "a.png", "size": 100, "mtime": 1},
        {"relative_path": "b.jpg", "size": 250, "mtime": 3},
        {"relative_path": "c.png", "size": 300, "mtime": 4},
    ]
    changes = detect_changes(prev, curr)
    assert len(changes["added"]) == 1
    assert changes["added"][0]["relative_path"] == "c.png"
    assert len(changes["changed"]) == 1
    assert len(changes["unchanged"]) == 1
    assert len(changes["removed"]) == 0

    prev2 = curr
    curr2 = [{"relative_path": "a.png", "size": 100, "mtime": 1}]
    changes2 = detect_changes(prev2, curr2)
    assert len(changes2["removed"]) == 2
