"""Tests for app/core/folder_ai.py — disk _AI ops on tmp trees (no Qt)."""

import pytest

from app.core.folder_ai import delete_non_ai_images, strip_ai_name, strip_ai_suffixes

EXTS = {".png", ".jpg"}


def _tree(root):
    (root / "sub").mkdir()
    (root / ".hidden").mkdir()
    files = ["a_AI.png", "b.png", "c_AI_1.jpg", "d.txt", "e_AI.txt",
             "sub/f_AI.png", "sub/f.png", "sub/g.jpg", ".hidden/h_AI.png"]
    for f in files:
        (root / f).write_bytes(b"x")
    return files


@pytest.mark.unit
def test_strip_ai_name():
    assert strip_ai_name("photo_AI.png") == "photo.png"
    assert strip_ai_name("photo_AI_1.png") == "photo_1.png"
    assert strip_ai_name("my_AI_photo_AI.png") == "my_AI_photo.png"
    assert strip_ai_name("photo.png") is None
    assert strip_ai_name("photo_ai.png") is None
    assert strip_ai_name("photo_AI_final.png") is None
    assert strip_ai_name("") is None
    assert strip_ai_name(None) is None


@pytest.mark.unit
def test_strip_ai_suffixes(tmp_path):
    _tree(tmp_path)
    pairs, skipped, errors = strip_ai_suffixes(tmp_path, EXTS)
    assert errors == []
    assert skipped == 1  # sub/f.png already exists
    assert (tmp_path / "a.png").exists()
    assert not (tmp_path / "a_AI.png").exists()
    assert (tmp_path / "c_1.jpg").exists()  # counter kept
    assert (tmp_path / "sub/f_AI.png").exists()  # collision untouched
    assert (tmp_path / "b.png").exists()  # original untouched
    assert (tmp_path / "e_AI.txt").exists()  # non-image untouched
    assert (tmp_path / ".hidden/h_AI.png").exists()  # hidden dir skipped
    assert len(pairs) == 2


@pytest.mark.unit
def test_delete_non_ai_images(tmp_path):
    _tree(tmp_path)
    deleted, errors = delete_non_ai_images(tmp_path, EXTS)
    assert errors == []
    assert sorted(deleted) == ["b.png", "sub/f.png", "sub/g.jpg"]
    assert (tmp_path / "a_AI.png").exists()
    assert (tmp_path / "c_AI_1.jpg").exists()
    assert (tmp_path / "d.txt").exists()  # non-image kept
    assert (tmp_path / ".hidden/h_AI.png").exists()


@pytest.mark.unit
def test_os_errors_are_reported_per_file_and_never_stop_the_sweep(tmp_path, monkeypatch):
    """RULE 4 / RULE 9: a file the OS refuses shows up in `errors` by name; the others are still done."""
    from pathlib import Path
    _tree(tmp_path)
    real_rename, real_unlink = Path.rename, Path.unlink

    def rename_refusing_a(self, target):
        if self.name == "a_AI.png":
            raise PermissionError("locked")
        return real_rename(self, target)

    def unlink_refusing_b(self):
        if self.name == "b.png":
            raise PermissionError("in use")
        return real_unlink(self)

    monkeypatch.setattr(Path, "rename", rename_refusing_a)
    pairs, skipped, errors = strip_ai_suffixes(tmp_path, EXTS)
    assert errors == ["a_AI.png: locked"]
    assert ("c_AI_1.jpg", "c_1.jpg") in pairs and skipped == 1        # sub/f_AI.png → sub/f.png exists
    assert (tmp_path / "a_AI.png").exists() and (tmp_path / "c_1.jpg").exists()

    monkeypatch.setattr(Path, "unlink", unlink_refusing_b)
    deleted, errors = delete_non_ai_images(tmp_path, EXTS)
    assert errors == ["b.png: in use"] and (tmp_path / "b.png").exists()
    assert "sub/g.jpg" in deleted and not (tmp_path / "sub" / "g.jpg").exists()
