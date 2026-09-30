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
                                                entry_for,
                                                parse_manifest, read_manifest)

pytestmark = pytest.mark.unit


@pytest.fixture()
def bridge(tmp_path):
    from app.persistence.config_manager import ConfigManager
    from app.ui.bridge import Bridge
    return Bridge(config_manager=ConfigManager(config_dir=str(tmp_path)),
                  state_path=tmp_path / "app_state.json")


# ---- L7: a remap note that could not be produced says so ------------------

def test_an_unreadable_queue_doc_becomes_a_remap_note(tmp_path):
    """L7: `restore._remap_notes` swallowed (OSError, ValueError) with `pass`, so
    'the folder root moved' and 'we could not read the file' looked identical.
    An unreadable doc is now a note; an empty one still means 'no remap'."""
    import json as _json
    from app.persistence.workspace.integrity import canonical_bytes
    from app.services.workspace import restore as ws_restore
    from app.persistence.workspace.manifest import build_manifest
    root = tmp_path / "snap"
    (root / "state").mkdir(parents=True)
    for content, expected in ((b"{not json", "could not be read"),
                              (canonical_bytes({"queue": []}), None)):
        (root / "state/app_state.json").write_bytes(content)
        manifest = build_manifest(header={"snapshot_id": "s", "name": "s"},
                                  app_meta={}, compat={},
                                  domains={"arena_state": {"path": "state/app_state.json"}})
        (root / "manifest.json").write_bytes(canonical_bytes(manifest))
        notes = ws_restore._remap_notes(root, manifest)
        if expected:
            assert notes and expected in notes[0], notes
        else:
            assert notes == []


# ---- L4: reading the recent list must not write the index -----------------

def test_reading_the_recent_snapshots_list_does_not_write(tmp_path, monkeypatch):
    """L4: `snapshot_index.recent_snapshots` is a READER, but it rewrote
    `workspace_meta.json` whenever it pruned a vanished path — an I/O side
    effect in a getter, on a path read from a JSON file. Pruning now happens
    only when the index is written."""
    from app.services.workspace import snapshot_index
    from app.persistence.json_store import save_json_atomic
    meta = snapshot_index.META_FILE
    save_json_atomic(tmp_path / meta, {"recent": [str(tmp_path / "gone")],
                                       "last_snapshot": {"path": "x"}})
    writes = []
    monkeypatch.setattr(snapshot_index, "_write_meta",
                        lambda b, m: writes.append(m))
    assert snapshot_index.recent_snapshots(_FakeBridge(tmp_path)) == []
    assert writes == [], "a reader must not write"


class _FakeBridge:
    def __init__(self, config_dir):
        self.config = type("C", (), {"dir": config_dir})()


# ---- L6: one read per key in the watcher reconcile -----------------------

def test_the_watcher_reconcile_reads_each_key_once(bridge, monkeypatch):
    """L6: the dict comprehension called `bridge.config.get_state(key)` twice per
    key — once for the value, once for the `is not None` test."""
    from app.services.workspace.providers.session import SessionSettingsProvider
    calls = []
    real = bridge.config.get_state
    monkeypatch.setattr(bridge.config, "get_state",
                        lambda key, default=None: (calls.append(key), real(key, default))[1])
    watcher = type("W", (), {"update_config": lambda _self, **kw: None})()
    monkeypatch.setattr(bridge, "_watcher", watcher, raising=False)
    SessionSettingsProvider().reconcile(bridge)
    assert len(calls) == len(set(calls)), f"a key was read twice: {calls}"


# ---- L8: meta owns the inclusion policy, with no re-wrap -----------------

def test_the_inclusion_policy_lives_only_in_meta():
    """L8: `save.inclusion_policy()` was a one-line re-wrap of a dict that
    `save` imported from a provider module. The one home is now `meta`, and
    it hands back a copy, never the module dict itself."""
    import app.services.workspace as pkg
    from app.services.workspace import meta as ws_meta
    from app.services.workspace.providers import policies
    assert not hasattr(policies, "INCLUSION_POLICY")
    owners = [name for name in dir(pkg.save) if name == "INCLUSION_POLICY"]
    assert owners == []
    policy = ws_meta.inclusion_policy()
    policy["logs"] = "mutated"
    assert ws_meta.INCLUSION_POLICY["logs"] != "mutated"
    assert ws_meta.inclusion_policy() == ws_meta.INCLUSION_POLICY


# ---- L10: one shape validator, five call sites (audit #3) ------------------

def test_object_doc_rejects_a_non_object():
    from app.services.workspace.provider import object_doc
    assert object_doc("not a dict") == "document is not an object"
    assert object_doc({"a": 1}) is None


def test_members_check_types_for_present_and_missing_keys():
    from app.services.workspace.provider import members
    assert members({}, a=list) is None                       # absent = tolerated
    assert members({"a": []}, a=list) is None
    assert members({"a": {}}, a=list) == "'a' must be a list"
    assert members({"a": {}}, a=dict) is None
    assert members({"a": "x", "b": 1}, a=list, b=dict) == "'a' must be a list"


def test_every_single_file_provider_uses_the_shared_shape_validator():
    """The five one-file providers re-derived the same isinstance ladder; they
    now call `object_doc` / `members` from the provider contract."""
    from app.services.workspace.provider import object_doc
    from app.services.workspace.providers import (captcha_stats, cooldowns,
                                                  job_history, preset_stores, undo)
    assert captcha_stats.stats_error("nope") == object_doc("nope")
    assert cooldowns.sections_error("nope") == object_doc("nope")
    assert undo.history_error("nope") == object_doc("nope")
    assert job_history.history_error("nope") == object_doc("nope")
    assert preset_stores.WindowPresetsProvider().validate("nope") == object_doc("nope")


# ---- L3: one named truncation limit per field (audit #3) -------------------

def test_the_two_truncation_limits_are_named_not_magic():
    from app.persistence.workspace import errors
    assert errors.CAUSE_LIMIT == 400 and errors.EVIDENCE_LIMIT == 120
    long = "x" * 900
    assert errors.WorkspaceError("d", "apply", long).cause == "x" * 400
    assert errors.WorkspaceError("d", "checksum", "c", (long, long)).to_dict()["expected"] \
        == "x" * 120


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
                           "semantic", "migration", "dependency", "capture", "apply",
                           "reconcile", "rollback"}


def test_capture_failures_report_the_capture_stage_not_apply():
    """S1: a SAVE-side capture failure must not claim "previous values were kept"."""
    from app.persistence.workspace.errors import WorkspaceError
    row = WorkspaceError("job_history", "capture", "capture failed: boom").to_dict()
    assert row["stage"] == "capture"
    assert "previous values" not in row["recommended_action"]


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


def test_fsio_write_bytes_entry_matches_integrity_shape(tmp_path):
    """D1: the written-file entry is THE integrity entry, computed in one home."""
    from app.persistence.workspace.integrity import bytes_entry, canonical_bytes
    doc = {"b": 2, "a": 1}
    entry = fsio.write_bytes(tmp_path, "state/x.json", canonical_bytes(doc))
    assert entry == bytes_entry("state/x.json", canonical_bytes(doc))
    assert entry == doc_entry("state/x.json", doc)  # same bytes, same entry
