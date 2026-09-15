import zipfile

import pytest

from tools.release_check import audit


def wheel(tmp_path, monkeypatch, members):
    from tools import release_check

    source = tmp_path / "src/image_queue"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("version=1")
    monkeypatch.setattr(release_check, "ROOT", tmp_path)
    path = tmp_path / "candidate.whl"
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members:
            archive.writestr(name, data)
    return path


def test_release_membership_and_source_identity(tmp_path, monkeypatch):
    path = wheel(
        tmp_path,
        monkeypatch,
        [
            ("image_queue/__init__.py", "version=1"),
            ("arena_image_queue-0.1.0.dist-info/METADATA", "metadata"),
        ],
    )
    assert audit(path) == 2


@pytest.mark.parametrize(
    "members",
    [
        [("image_queue/__init__.py", "changed")],
        [],
        [("profile/Cookies", "secret")],
        [("image_queue/private.json", "unexpected")],
        [("arena_image_queue-0.1.0.dist-info/../profile", "bad")],
    ],
)
def test_release_rejects_missing_changed_and_unexpected(tmp_path, monkeypatch, members):
    with pytest.raises(ValueError):
        audit(wheel(tmp_path, monkeypatch, members))


def test_release_rejects_duplicate_members(tmp_path, monkeypatch):
    with pytest.warns(UserWarning, match="Duplicate"):
        path = wheel(tmp_path, monkeypatch, [("image_queue/__init__.py", "version=1")] * 2)
    with pytest.raises(ValueError, match="Duplicate"):
        audit(path)
