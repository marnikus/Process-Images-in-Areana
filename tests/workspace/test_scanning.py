import io
import os
from copy import deepcopy
from pathlib import Path

import pytest
from PIL import Image

from image_queue.domain.validation import ContractError
from image_queue.operations import Operations
from image_queue.persistence.store import SnapshotStore
from image_queue.scanning.files import source_paths
from image_queue.scanning.images import image_metadata, read_source
from image_queue.scanning.scanner import FolderScanner, reconcile
from image_queue.workspace.extensions import defaults
from image_queue.workspace.history import initial_state
from image_queue.workspace.observations import validate_sources
from image_queue.workspace.queue import queue_rows, select_sources
from image_queue.workspace.service import WorkspaceService


def image(path, color="red", fmt="PNG"):
    Image.new("RGB", (12, 8), color).save(path, format=fmt)


def test_recursive_supported_generated_links_and_thumbnails(tmp_path):
    image(tmp_path / "source.PNG")
    image(tmp_path / "source_AI.png")
    image(tmp_path / "source_AI_2.PNG")
    image(tmp_path / "camera_ai_12.jpg", fmt="JPEG")
    (tmp_path / "not.txt").write_text("no")
    sub = tmp_path / "sub"
    sub.mkdir()
    image(sub / "second.webp", fmt="WEBP")
    output = tmp_path / "output"
    output.mkdir()
    image(output / "unmarked.png")
    os.link(tmp_path / "source.PNG", tmp_path / "z-alias.png")
    # On Windows symlink creation may require Developer Mode; hardlink coverage remains mandatory.
    if os.name != "nt":
        (tmp_path / "link.png").symlink_to(tmp_path / "source.PNG")
        (sub / "cycle").symlink_to(tmp_path, target_is_directory=True)
    options = {**defaults()["scan_options"], "output_folder": str(output)}
    rows = FolderScanner().scan(str(tmp_path), options)
    assert {r["relative"] for r in rows.values()} == {
        "source.PNG",
        str(Path("sub") / "second.webp"),
    }
    validate_sources(rows)
    for row in rows.values():
        assert row["status"] == "available"
        assert row["thumbnail"].startswith("data:image/jpeg;base64,")
        assert row["width"] == 12 and row["height"] == 8
        assert len(row["sha256"]) == 64
    flat = FolderScanner().scan(str(tmp_path), {**options, "recursive": False})
    assert len(flat) == 1
    assert (tmp_path / "source.PNG").read_bytes() == (tmp_path / "z-alias.png").read_bytes()


def test_missing_changed_reconciliation_and_fingerprint_bound_selection(tmp_path, workspace):
    path = tmp_path / "a.png"
    image(path)
    scanner = FolderScanner()
    options = defaults()["scan_options"]
    first = scanner.scan(str(tmp_path), options)
    key = next(iter(first))
    selected = select_sources(workspace, first, {"ids": [key], "decision": "selected"})
    assert queue_rows(first, workspace["selection"])[0]["selected"] is False
    assert queue_rows(first, selected["selection"])[0]["selected"] is True
    image(path, "blue")
    changed = reconcile(first, scanner.scan(str(tmp_path), options))
    assert changed[key]["status"] == "changed"
    assert not queue_rows(changed, selected["selection"])[0]["selected"]
    assert queue_rows(changed, selected["selection"])[0]["needs_review"]
    approved = select_sources(selected, changed, {"ids": [key], "decision": "selected"})
    assert queue_rows(changed, approved["selection"])[0]["selected"]
    path.unlink()
    missing = reconcile(changed, scanner.scan(str(tmp_path), options))
    assert missing[key]["status"] == "missing"
    assert not queue_rows(missing, approved["selection"])[0]["selected"]
    assert first[key]["status"] == "available"  # inputs never mutated
    with pytest.raises(ContractError):
        select_sources(workspace, missing, {"ids": [key], "decision": "selected"})


def test_corrupt_oversized_animated_and_wrong_bytes(tmp_path):
    (tmp_path / "corrupt.png").write_bytes(b"not image")
    image(tmp_path / "large.jpg")
    frames = [Image.new("RGB", (2, 2), c) for c in ("red", "blue")]
    frames[0].save(tmp_path / "animated.png", save_all=True, append_images=frames[1:])
    rows = FolderScanner().scan(str(tmp_path), defaults()["scan_options"])
    assert sorted(r["status"] for r in rows.values()) == ["available", "invalid", "invalid"]
    small = FolderScanner().scan(str(tmp_path), {**defaults()["scan_options"], "max_bytes": 1})
    assert all(r["status"] == "invalid" for r in small.values())
    validate_sources(small)
    gif = io.BytesIO()
    frames[0].save(gif, format="GIF")
    with pytest.raises(ContractError):
        image_metadata(gif.getvalue())


def test_scan_validation_limits_and_traversal_failure(tmp_path, monkeypatch):
    options = defaults()["scan_options"]
    for folder in ["", "\x00", str(tmp_path / "missing")]:
        with pytest.raises((ContractError, OSError)):
            FolderScanner().scan(folder, options)
    for folder in (tmp_path, tmp_path.parent):
        with pytest.raises(ContractError):
            source_paths(tmp_path, {**options, "output_folder": str(folder)})
    path = tmp_path / "a.png"
    image(path)
    if os.name != "nt":
        link = tmp_path / "link"
        link.symlink_to(tmp_path, target_is_directory=True)
        with pytest.raises(ContractError):
            source_paths(link, options)
        with pytest.raises(ContractError):
            read_source(link, 10)
    monkeypatch.setattr("image_queue.scanning.scanner.source_paths", lambda *a: [path] * 2001)
    with pytest.raises(ContractError, match="2000"):
        FolderScanner().scan(str(tmp_path), options)


def test_enumeration_and_byte_time_budgets(tmp_path, monkeypatch):
    from image_queue.scanning import files, scanner

    path = tmp_path / "a.png"
    image(path)
    with pytest.raises(ContractError):
        files._walk(tmp_path, None, True, 0)
    monkeypatch.setattr(scanner.time, "monotonic", iter([0, 100]).__next__)
    monkeypatch.setattr(scanner, "source_paths", lambda *a: [path])
    with pytest.raises(ContractError, match="time limit"):
        scanner.FolderScanner().scan(str(tmp_path), defaults()["scan_options"])


@pytest.mark.parametrize(
    "command",
    [
        {"ids": [], "decision": "selected"},
        {"ids": ["a"], "decision": "completed"},
        {"ids": ["missing"], "decision": "selected"},
        {"ids": [None], "decision": "review"},
    ],
)
def test_invalid_selection(workspace, command):
    with pytest.raises(ContractError):
        select_sources(workspace, {}, command)


def test_scanning_persistence_undo_restart_and_failed_scan(tmp_path, workspace):
    source = tmp_path / "sources"
    source.mkdir()
    image(source / "a.png")
    workspace["folder"] = str(source)
    directory = tmp_path / "state"
    with_store = SnapshotStore(directory)
    try:
        service = WorkspaceService(initial_state(workspace), with_store)
        ops = Operations(service)

        def execute(kind, **kwargs):
            return ops.execute({"kind": kind, "revision": service.snapshot()["revision"], **kwargs})

        execute("scan")
        current = service.snapshot()
        key = next(iter(current["jobs"]["sources"]))
        execute("select", ids=[key], decision="selected")
        assert execute("queue")["result"][0]["selected"]
        execute("undo")
        assert not execute("queue")["result"][0]["selected"]
        assert service.snapshot()["jobs"] == current["jobs"]
        execute("redo")
        assert execute("queue")["result"][0]["selected"]
        # A failed traversal must not mark previously seen records missing.
        edit = service.snapshot()["workspace"]
        edit["folder"] = str(tmp_path / "absent")
        execute("edit", workspace=edit, label="Missing directory")
        before = service.snapshot()
        with pytest.raises(OSError):
            execute("scan")
        assert service.snapshot() == before
        service.busy = True
        with pytest.raises(ContractError):
            execute("scan")
        with pytest.raises(ContractError):
            service.record_sources({}, before["revision"])
        service.busy = False
        with pytest.raises(ContractError):
            service.record_sources({}, -1)
    finally:
        with_store.close()
    reopened = SnapshotStore(directory)
    try:
        restored = WorkspaceService(reopened.load(initial_state(workspace)), reopened)
        assert restored.snapshot() == before
    finally:
        reopened.close()


def test_observation_schema_rejects_completion_and_invalid_metadata(tmp_path):
    image(tmp_path / "x.png")
    sources = FolderScanner().scan(str(tmp_path), defaults()["scan_options"])
    key = next(iter(sources))
    variants = [
        ("status", "completed"),
        ("sha256", "bad"),
        ("sha256", ""),
        ("width", False),
        ("path", "\x00"),
        ("thumbnail", "https://remote/image"),
        ("thumbnail", "x" * 20001),
    ]
    for field, value in variants:
        bad = deepcopy(sources)
        bad[key][field] = value
        with pytest.raises(ContractError):
            validate_sources(bad)
    for bad in [[], {"bad-id": {}}, {key: {}}, {key: {**sources[key], "unknown": 1}}]:
        with pytest.raises(ContractError):
            validate_sources(bad)
    bad = deepcopy(sources)
    del bad[key]["width"]
    with pytest.raises(ContractError):
        validate_sources(bad)


def test_changed_during_read_and_short_read(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from image_queue.scanning import images

    path = tmp_path / "source.png"
    image(path)
    real_fstat = os.fstat
    calls = 0

    def changed(fd):
        nonlocal calls
        info = real_fstat(fd)
        calls += 1
        if calls == 2:
            return SimpleNamespace(
                st_dev=info.st_dev,
                st_ino=info.st_ino,
                st_size=info.st_size,
                st_mtime_ns=info.st_mtime_ns + 1,
            )
        return info

    with monkeypatch.context() as patch:
        patch.setattr(images.os, "fstat", changed)
        with pytest.raises(ContractError, match="changed"):
            read_source(path, 10000)
    real_fdopen = os.fdopen

    class ShortReader:
        def __init__(self, fd, mode):
            self.stream = real_fdopen(fd, mode)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, limit):
            return self.stream.read(limit)[:-1]

    monkeypatch.setattr(images.os, "fdopen", ShortReader)
    with pytest.raises(ContractError, match="incomplete"):
        read_source(path, 10000)


def test_total_scan_byte_budget(tmp_path, monkeypatch):
    for index in range(5):
        with (tmp_path / f"{index}.png").open("wb") as stream:
            stream.truncate(64 * 1024 * 1024)
    monkeypatch.setattr(FolderScanner, "_item", lambda *args: {})
    with pytest.raises(ContractError, match="byte budget"):
        FolderScanner().scan(
            str(tmp_path), {**defaults()["scan_options"], "max_bytes": 64 * 1024 * 1024}
        )


def test_invalid_output_folder():
    from image_queue.workspace.extensions import validate_extensions

    value = defaults()
    value["scan_options"]["output_folder"] = "\x00"
    with pytest.raises(ContractError):
        validate_extensions(value)
