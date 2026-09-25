"""Workspace core — stage vocabulary, integrity, manifest gates, folder IO (W2).

Real filesystem on tmp_path only (task test-plan rule); the manifest is the
commit marker and the only ownership registry, so its refusal reasons are
locked here.
"""

import json
import os

import pytest

from app.persistence.workspace import fsio
from app.persistence.workspace.errors import STAGES, WorkspaceError
from app.persistence.workspace.integrity import (canonical_bytes, doc_entry,
                                                safe_rel_path, sha256_bytes)
from app.persistence.workspace.manifest import (build_manifest, check_format,
                                                domain_for_file, entry_for,
                                                parse_manifest, read_manifest)

pytestmark = pytest.mark.unit


# ---- errors ----

def test_workspace_error_rejects_unknown_stage():
    with pytest.raises(ValueError):
        WorkspaceError("d", "not_a_stage", "x")


def test_workspace_error_row_is_complete_and_truncated():
    err = WorkspaceError("arena_state", "checksum", "x" * 900,
                         evidence=("abc", "abd"))
    row = err.to_dict()
    assert row["domain_id"] == "arena_state" and row["stage"] == "checksum"
    assert len(row["cause"]) <= 400
    assert row["recommended_action"]


def test_stage_vocabulary_covers_every_reported_stage():
    assert set(STAGES) == {"missing", "unsafe_path", "checksum", "parse", "schema",
                           "semantic", "migration", "dependency", "apply",
                           "reconcile", "rollback"}


# ---- integrity ----

def test_canonical_bytes_are_key_sorted_and_stable():
    one = canonical_bytes({"b": 1, "a": {"d": 2, "c": 3}})
    two = canonical_bytes({"a": {"c": 3, "d": 2}, "b": 1})
    assert one == two and b'"a"' in one


def test_doc_entry_matches_bytes():
    entry = doc_entry("state/x.json", {"k": "v"})
    assert entry["bytes"] == len(canonical_bytes({"k": "v"}))
    assert entry["sha256"] == sha256_bytes(canonical_bytes({"k": "v"}))


@pytest.mark.parametrize("rel,ok", [
    ("state/app_state.json", True),
    ("state/session.json", True),
    ("../escape.json", False),
    ("a/../../b.json", False),
    ("/abs/path.json", False),
    ("C:/win/path.json", False),
    ("back\\slash.json", True),
    ("", False),
    (None, False),
    ("./ok.json", True),
])
def test_safe_rel_path_rules(rel, ok):
    assert bool(safe_rel_path(rel)) is ok


def test_safe_rel_path_backslash_becomes_posix():
    assert safe_rel_path("back\\slash.json") == "back/slash.json"


# ---- manifest ----

def _manifest(**over):
    base = build_manifest(
        header={"snapshot_id": "ws_x", "name": "n", "description": "",
                "created_utc": "2026-09-25T00:00:00Z"},
        app_meta={"build": "f5cb06e"}, compat={"grid_version": 9},
        domains={"arena_state": {"path": "state/app_state.json", "required": True}})
    base.update(over)
    return base


def test_manifest_roundtrip_and_lookups():
    manifest = _manifest()
    parsed, err = parse_manifest(json.loads(json.dumps(manifest)))
    assert err is None and parsed["snapshot_id"] == "ws_x"
    assert entry_for(parsed, "arena_state")["path"] == "state/app_state.json"
    assert entry_for(parsed, "nope") is None
    assert domain_for_file(parsed, "state/app_state.json") == ["arena_state"]
    assert domain_for_file(parsed, "state/unknown.json") == []


@pytest.mark.parametrize("mutation,fragment", [
    ({"format": "other"}, "not a arena-workspace"),
    ({"workspace_format": "x"}, "not a number"),
    ({"workspace_format": 99}, "newer app"),
    ({"workspace_format": 0}, "older than"),
    ({"domains": {}}, "lists no domains"),
])
def test_manifest_refusal_reasons(mutation, fragment):
    _, err = parse_manifest(_manifest(**mutation))
    assert err and fragment in err


def test_read_manifest_missing_and_corrupt(tmp_path):
    _, err = read_manifest(tmp_path)
    assert "not a committed workspace" in err
    (tmp_path / "manifest.json").write_text("{broken", encoding="utf-8")
    _, err = read_manifest(tmp_path)
    assert "unreadable" in err


# ---- fsio ----

def test_snapshot_dir_name_sanitizes_and_stamps():
    import time
    stamp = time.gmtime(1786000000)
    name = fsio.snapshot_dir_name('bad:name*here?', stamp)
    assert "/" not in name and name.startswith("bad-name-here?_") or ":" not in name


def test_publish_renames_and_refuses_existing_target(tmp_path):
    temp = fsio.new_temp_dir(tmp_path / "snap")
    (temp / "manifest.json").write_bytes(b"{}")
    target = tmp_path / "snap_final"
    fsio.publish(temp, target)
    assert (target / "manifest.json").exists() and not temp.exists()
    with pytest.raises(FileExistsError):
        fsio.publish(temp2 := fsio.new_temp_dir(target), target)
    fsio.remove_tree(temp2)


def test_publish_cross_volume_copy_fallback(tmp_path, monkeypatch):
    import errno as errno_mod
    temp = fsio.new_temp_dir(tmp_path / "snap")
    (temp / "f.txt").write_bytes(b"data")
    target = tmp_path / "snap_cross"
    real_rename = os.rename
    state = {"first": True}

    def exdev_once(src, dst):
        if state["first"]:
            state["first"] = False
            raise OSError(errno_mod.EXDEV, "cross-device link")
        return real_rename(src, dst)

    monkeypatch.setattr(fsio.os, "rename", exdev_once)
    fsio.publish(temp, target)
    assert (target / "f.txt").read_bytes() == b"data"


def test_publish_transient_backoff_then_success(tmp_path, monkeypatch):
    temp = fsio.new_temp_dir(tmp_path / "snap")
    (temp / "f.txt").write_bytes(b"data")
    target = tmp_path / "snap_retry"
    real_replace = os.rename
    state = {"tries": 0}

    def busy_once(src, dst):
        state["tries"] += 1
        if state["tries"] < 3:
            raise PermissionError(11, "cloud sync holds it")
        return real_replace(src, dst)

    monkeypatch.setattr(fsio, "BACKOFF_SEC", 0.001)
    monkeypatch.setattr(fsio.os, "rename", busy_once)
    fsio.publish(temp, target)
    assert state["tries"] == 3 and (target / "f.txt").exists()


def test_write_bytes_returns_integrity_entry(tmp_path):
    entry = fsio.write_bytes(tmp_path, "state/deep/x.json", b"1234")
    assert (tmp_path / "state/deep/x.json").read_bytes() == b"1234"
    assert entry["sha256"] == sha256_bytes(b"1234") and entry["bytes"] == 4
