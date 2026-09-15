"""Actual filesystem durability, backup, lock and fault injection tests."""

import json
import os
import subprocess
import sys
from copy import deepcopy

import pytest

from image_queue.domain.validation import ContractError
from image_queue.persistence import atomic, codec
from image_queue.persistence.store import SnapshotStore
from image_queue.workspace.history import edit_state
from image_queue.workspace.service import WorkspaceService


def test_state_history_and_redo_survive_restart(tmp_path, state):
    store = SnapshotStore(tmp_path)
    service = WorkspaceService(store.load(state), store)
    workspace = deepcopy(state["workspace"])
    workspace["prompt"] = "saved"
    current = service.execute(
        {"kind": "edit", "revision": 0, "workspace": workspace, "label": "Prompt"}
    )
    undone = service.execute({"kind": "undo", "revision": current["revision"]})
    store.close()
    reopened = SnapshotStore(tmp_path)
    try:
        assert reopened.load(state) == undone
        service = WorkspaceService(reopened.load(state), reopened)
        redone = service.execute({"kind": "redo", "revision": undone["revision"]})
        assert redone["workspace"]["prompt"] == "saved"
    finally:
        reopened.close()


def test_live_instance_lock_and_release_after_close(tmp_path, state):
    store = SnapshotStore(tmp_path)
    with pytest.raises(ContractError, match="already open"):
        SnapshotStore(tmp_path)
    store.close()
    with pytest.raises(ContractError, match="lock"):
        store.save(state)
    reopened = SnapshotStore(tmp_path)
    reopened.close()


def test_os_releases_lock_on_crash(tmp_path):
    code = (
        "from pathlib import Path; from image_queue.persistence.store import SnapshotStore; "
        "import os,sys; s=SnapshotStore(Path(sys.argv[1])); os._exit(7)"
    )
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], check=False)
    assert result.returncode == 7
    store = SnapshotStore(tmp_path)
    store.close()


def test_corrupt_primary_requires_explicit_backup_recovery(tmp_path, state):
    store = SnapshotStore(tmp_path)
    store.save(state)
    new = edit_state(state, {**state["workspace"], "prompt": "second"}, "Prompt")
    store.save(new)
    store.path.write_bytes(b"broken")
    with pytest.raises(ContractError):
        store.load(state)
    assert store.path.read_bytes() == b"broken"
    restored = store.recover_backup()
    assert restored == state
    assert next(tmp_path.glob("state.corrupt-*.json")).read_bytes() == b"broken"
    store.close()


def test_missing_primary_with_backup_or_partial_does_not_start_empty(tmp_path, state):
    store = SnapshotStore(tmp_path)
    orphan = tmp_path / ".workspace-orphan.partial"
    orphan.write_bytes(b"partial")
    with pytest.raises(ContractError, match="recovery evidence"):
        store.load(state)
    orphan.unlink()
    store.backup.write_bytes(codec.encode_state(state))
    with pytest.raises(ContractError, match="recovery evidence"):
        store.load(state)
    store.close()


def test_failure_before_publication_preserves_primary_and_stops_writer(
    tmp_path, state, monkeypatch
):
    store = SnapshotStore(tmp_path)
    store.save(state)
    service = WorkspaceService(state, store)

    def fail_replace(source, target):
        raise OSError("disk full")

    monkeypatch.setattr(atomic.os, "replace", fail_replace)
    with pytest.raises(ContractError, match="Saving failed"):
        service.execute(
            {
                "kind": "edit",
                "revision": 0,
                "workspace": {**state["workspace"], "prompt": "new"},
                "label": "Prompt",
            }
        )
    assert service.snapshot() == state
    assert codec.decode_state(store.path.read_bytes()) == state
    assert not list(tmp_path.glob("*.partial"))
    with pytest.raises(ContractError, match="Persistence fault"):
        store.save(state)
    store.close()


def test_failure_after_publication_never_acknowledged_but_recoverable(tmp_path, state, monkeypatch):
    store = SnapshotStore(tmp_path)

    def fail_directory(_directory):
        raise OSError("directory flush failed")

    monkeypatch.setattr(atomic, "sync_directory", fail_directory)
    with pytest.raises(ContractError, match="Saving failed"):
        store.save(state)
    assert store.failed
    assert codec.decode_state(store.path.read_bytes()) == state
    store.close()
    reopened = SnapshotStore(tmp_path)
    assert reopened.load(state) == state
    reopened.close()


def test_tampered_duplicate_invalid_and_future_state_rejected(state):
    raw = codec.encode_state(state)
    assert codec.decode_state(raw) == state
    data = json.loads(raw)
    data["state"]["revision"] = 1
    with pytest.raises(ContractError, match="checksum"):
        codec.decode_state(json.dumps(data).encode())
    for bad in [b"null", b"{", b' {"format":1,"format":2}', b"\xff", b"[" * 2000]:
        with pytest.raises(ContractError):
            codec.decode_state(bad)
    data = json.loads(raw)
    data["format"] = "other"
    with pytest.raises(ContractError, match="unsupported"):
        codec.decode_state(json.dumps(data).encode())
    with pytest.raises(ContractError):
        codec.encode_state({**state, "version": 2})


def test_size_and_non_json_data_fail_before_disk(state, monkeypatch):
    monkeypatch.setattr(codec, "MAX_STATE_BYTES", 10)
    with pytest.raises(ContractError, match="limit"):
        codec.encode_state(state)
    with pytest.raises(ContractError, match="limit"):
        codec.decode_state(b"a" * 11)
    for bad in [object(), float("nan"), "\ud800"]:
        changed = deepcopy(state)
        changed["jobs"] = {"bad": bad}
        with pytest.raises(ContractError, match="serialize"):
            codec.encode_state(changed)


def test_readback_failure_faults_store(tmp_path, state, monkeypatch):
    store = SnapshotStore(tmp_path)
    monkeypatch.setattr(store, "_read", lambda _path: {"wrong": True})
    with pytest.raises(ContractError, match="Saving failed"):
        store.save(state)
    assert store.failed
    store.close()


def test_file_fsync_failure_cleans_partial(tmp_path, state, monkeypatch):
    def fail_fsync(_fd):
        raise OSError("fsync failure")

    monkeypatch.setattr(os, "fsync", fail_fsync)
    with pytest.raises(OSError):
        atomic.atomic_write(tmp_path / "state.json", codec.encode_state(state))
    assert not (tmp_path / "state.json").exists()
    assert not list(tmp_path.glob("*.partial"))


def test_explicit_backup_recovery_when_primary_is_missing(tmp_path, state):
    store = SnapshotStore(tmp_path)
    store.backup.write_bytes(codec.encode_state(state))
    assert store.recover_backup() == state
    assert store.load(state) == state
    store.close()
