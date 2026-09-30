"""Workspace save — the SAVE algorithm (W4): temp folder, manifest last,
atomic publish, required-domain abort, partial confirmation, determinism,
interrupted-save semantics, meta/quick-load. Real FS on tmp_path only.
"""

import json
import shutil
import time
from pathlib import Path

import pytest

from app.persistence.config_manager import ConfigManager
from app.persistence.workspace import fsio
from app.persistence.workspace.manifest import read_manifest
from app.services.workspace import save as ws_save
from app.services.workspace import snapshot_index as ws_index
from app.services.workspace.meta import default_base
from app.services.workspace.save import SaveRequest
from app.services.workspace.provider import CaptureResult
from app.services.workspace.registry import all_providers, get
from app.ui.bridge import Bridge

pytestmark = pytest.mark.unit

FILE_DOMAINS = {"state/session.json", "state/app_state.json", "state/undo.json",
                "state/window_presets.json", "state/arena_presets.json",
                "state/cooldowns.json", "state/captcha_stats.json",
                "state/job_history.json"}


@pytest.fixture()
def bridge(tmp_path):
    return Bridge(config_manager=ConfigManager(config_dir=str(tmp_path)),
                  state_path=tmp_path / "app_state.json")


def _save(bridge, name="snap", **kw):
    return ws_save.save_workspace(bridge, SaveRequest(name=name, **kw))


def _manifest_of(reply):
    return json.loads((Path(reply["path"]) / "manifest.json").read_text())


def test_full_save_publishes_a_valid_workspace(bridge):
    reply = _save(bridge, name="my setup")
    assert reply["ok"] and reply["result"] == "success" and reply["published"]
    root = Path(reply["path"])
    manifest, err = read_manifest(root)
    assert err is None and manifest["snapshot_kind"] == "full"
    rels = {e["path"] for e in manifest["domains"].values() if e.get("path")}
    assert rels == FILE_DOMAINS
    assert set(manifest["domains"]) == {p.domain_id for p in all_providers()}
    assert (root / "metadata/app-environment.json").exists()
    assert (root / "reports/save-report.json").exists()


def test_temp_folder_without_manifest_is_not_a_snapshot(bridge):
    """Interrupted save before the commit marker → nothing claims to be a snapshot."""
    target = default_base(bridge) / "x_20260101-000000"
    temp = fsio.new_temp_dir(target)
    fsio.write_bytes(temp, "state/app_state.json", b"{}")
    _, err = read_manifest(temp)
    assert "not a committed workspace" in err
    fsio.remove_tree(temp)


def test_save_is_deterministic_for_unchanged_state(bridge):
    from app.persistence.workspace.integrity import file_sha
    one, two = _save(bridge, name="d1"), _save(bridge, name="d2")
    assert file_sha(Path(one["path"]) / "state/app_state.json") == \
        file_sha(Path(two["path"]) / "state/app_state.json")
    m1, m2 = _manifest_of(one), _manifest_of(two)
    assert m1["domains"]["arena_state"]["sha256"] == m2["domains"]["arena_state"]["sha256"]


def test_required_domain_failure_aborts_and_keeps_previous(bridge, monkeypatch):
    first = _save(bridge, name="good")
    assert first["ok"]
    monkeypatch.setattr(get("arena_state"), "validate", lambda doc: "boom")
    before = sorted(d.name for d in default_base(bridge).iterdir())
    reply = _save(bridge, name="broken")
    after = sorted(d.name for d in default_base(bridge).iterdir())
    assert reply["ok"] is False and "failed to capture" in reply["error"]
    assert "arena_state" in reply["error"]
    assert before == after  # nothing published, no temp left, previous untouched
    _, err = read_manifest(Path(first["path"]))
    assert err is None


def test_a_non_required_domain_failure_needs_no_confirmation(bridge, monkeypatch):
    """audit #3 H4 (ported from branch A): `required` is honoured.

    `job_history` is NOT required, so its capture failing degrades the save to
    `partial` and is reported — the user does not have to tick "allow partial"
    to checkpoint a queue because a corrupt captcha_stats file exists.
    """
    assert get("job_history").required is False
    monkeypatch.setattr(get("job_history"), "capture",
                        lambda bridge: CaptureResult(ok=False, notes=["unreadable"]))
    reply = _save(bridge, name="r1")
    assert reply["ok"] and reply["result"] == "partial", reply
    assert [e["domain_id"] for e in reply["errors"]] == ["job_history"]
    assert reply["failed_required"] == []          # nothing required failed
    manifest = _manifest_of(reply)
    assert manifest["snapshot_kind"] == "partial"
    assert manifest["domains"]["job_history"]["capture"]["excluded"] is True
    assert manifest["domains"]["arena_state"]["capture"]["ok"] is True


def test_a_required_domain_failure_still_needs_explicit_confirmation(bridge, monkeypatch):
    """The positive control: a REQUIRED domain failing still refuses the save
    unless the user explicitly allows a partial snapshot.
    """
    assert get("arena_state").required is True
    monkeypatch.setattr(get("arena_state"), "validate", lambda doc: "boom")
    refused = _save(bridge, name="r1")
    allowed = _save(bridge, name="r2", allow_partial=True)
    assert refused["ok"] is False and "allow a partial snapshot" in refused["error"]
    assert "arena_state" in refused["error"]
    assert allowed["ok"] and allowed["result"] == "partial"
    assert [e["domain_id"] for e in allowed["failed_required"]] == ["arena_state"]
    manifest = _manifest_of(allowed)
    assert manifest["snapshot_kind"] == "partial"
    assert manifest["domains"]["arena_state"]["capture"]["excluded"] is True


def test_a_required_failure_names_the_real_cause_in_the_log(bridge, monkeypatch):
    """RULE 2: the refusal line says WHY, not only that it was refused."""
    lines = []
    monkeypatch.setattr(ws_save, "log_message",
                        lambda b, m, lv="info": lines.append((m, lv)))
    monkeypatch.setattr(get("arena_state"), "validate", lambda doc: "boom")
    _save(bridge, name="req")
    assert len(lines) == 1 and lines[0][1] == "error"
    assert "arena_state" in lines[0][0] and "boom" in lines[0][0]


def test_publish_failure_retains_failed_folder_and_never_claims_success(
        bridge, monkeypatch):
    def explode(temp, target):
        raise OSError("cloud sync locked the parent folder")

    monkeypatch.setattr(fsio, "publish", explode)
    reply = _save(bridge, name="locked")
    assert reply["ok"] is False and "publish failed" in reply["error"]
    assert reply["previous_snapshots_untouched"]
    failed = Path(reply["failed_folder"])
    assert failed.exists() and (failed / "manifest.json").exists()
    fsio.remove_tree(failed)


def test_selected_subset_saves_only_those_domains(bridge):
    reply = ws_save.save_workspace(bridge, SaveRequest(
        name="subset", selected=["arena_state", "undo", "grid_window"]))
    manifest = _manifest_of(reply)
    assert set(manifest["domains"]) == {"arena_state", "undo", "grid_window"}


def test_recent_and_last_snapshot_meta(bridge):
    first, second = _save(bridge, name="m1"), _save(bridge, name="m2")
    recent = ws_index.recent_snapshots(bridge)
    assert recent[0] == second["path"] and first["path"] in recent
    assert ws_index.last_snapshot(bridge) == second["path"]
    ws_index.record_restore(bridge, first["path"], "success_with_warnings")
    assert ws_index.last_restore(bridge)["result"] == "success_with_warnings"


def test_last_snapshot_drops_when_folder_removed(bridge):
    reply = _save(bridge, name="gone")
    shutil.rmtree(reply["path"])
    assert ws_index.last_snapshot(bridge) == ""
    assert reply["path"] not in ws_index.recent_snapshots(bridge)


# ── audit #3 R2: one environment read, one clock per save ────────────────────

def test_app_meta_runs_once_per_save(bridge, monkeypatch):
    """app_meta shells out to git — a save must read the environment once."""
    calls = {"n": 0}
    original = ws_save.app_meta

    def counting(b):
        calls["n"] += 1
        return original(b)

    monkeypatch.setattr(ws_save, "app_meta", counting)
    assert _save(bridge, name="once")["ok"]
    assert calls["n"] == 1, "env (git subprocess) read more than once per save"


def test_folder_stamp_and_snapshot_id_share_one_clock(bridge, monkeypatch):
    """The folder name and the snapshot id must come from ONE clock read."""
    import time as _time
    real_gmtime, ticks = _time.gmtime, {"i": 0}

    def stepping_gmtime(secs=None):
        struct = real_gmtime(secs)
        ticks["i"] += 1
        return real_gmtime(_time.mktime(struct) + ticks["i"])

    monkeypatch.setattr(_time, "gmtime", stepping_gmtime)
    reply = _save(bridge, name="clock")
    stamp = reply["snapshot_id"].split("_")[1].replace("T", "-").removesuffix("Z")
    assert Path(reply["path"]).name == f"clock_{stamp}", (
        "folder name and snapshot id disagree — two clock reads in one save")


# ── audit #3 R3: a failed save is never silent (restore parity) ──────────────

def _capture_logs(bridge, monkeypatch):
    logs = []
    monkeypatch.setattr(bridge, "_log", lambda message, level="info": logs.append((level, message)))
    return logs


def test_aborted_save_logs_its_cause(bridge, monkeypatch, tmp_path):
    logs = _capture_logs(bridge, monkeypatch)
    (tmp_path / "job_history.json").write_text("{broken", encoding="utf-8")
    reply = _save(bridge, name="abort")
    assert reply["ok"] is False and reply["result"] == "failed"
    assert [level for level, _ in logs] == ["error"], logs
    assert "job_history" in logs[0][1], "the log names the domain that failed"


def test_publish_failure_logs_its_cause(bridge, monkeypatch):
    logs = _capture_logs(bridge, monkeypatch)

    def boom(temp, target):
        raise OSError("disk full")

    monkeypatch.setattr(fsio, "publish", boom)
    reply = _save(bridge, name="pubfail")
    assert reply["ok"] is False
    assert [level for level, _ in logs] == ["error"], logs
    assert "disk full" in logs[0][1]


def test_partial_save_logs_a_warning_not_a_success(bridge, monkeypatch, tmp_path):
    logs = _capture_logs(bridge, monkeypatch)
    (tmp_path / "job_history.json").write_text("{broken", encoding="utf-8")
    reply = _save(bridge, name="partial", allow_partial=True)
    assert reply["ok"] and reply["result"] == "partial"
    assert [level for level, _ in logs] == ["warn"], logs


# ── audit #3 R4: the index is a live JSON file like any other (RULE 4) ───────

def _index_path(bridge):
    from app.services.workspace.meta import META_FILE
    from app.services.workspace.provider import config_dir
    return config_dir(bridge) / META_FILE


def test_corrupt_index_is_reported_and_rebuilt(bridge, monkeypatch):
    logs = _capture_logs(bridge, monkeypatch)
    _index_path(bridge).write_text("{not json", encoding="utf-8")
    state = json.loads(bridge.get_workspace_state())
    assert state["recent"] == [] and state["last_snapshot"] == ""
    assert [level for level, _ in logs] == ["warn"], "a broken index is not empty" \
        " — it is reported (RULE 4), not silently discarded"
    reply = _save(bridge, name="rebuilt")
    assert reply["ok"]
    index = json.loads(_index_path(bridge).read_text(encoding="utf-8"))
    assert index["recent"] == [reply["path"]], "the index is usable again"


def test_garbage_index_entries_never_break_the_state_slot(bridge, monkeypatch):
    _capture_logs(bridge, monkeypatch)
    _index_path(bridge).write_text(json.dumps({
        "recent": ["/gone", 5, None, {"a": 1}, ""],
        "last_snapshot": "not-an-object",
        "last_restore": 42,
    }), encoding="utf-8")
    state = json.loads(bridge.get_workspace_state())
    assert state["recent"] == [], "non-string entries are dropped, never iterated"
    assert state["last_snapshot"] == "" and state["last_restore"] == {}


def test_valid_index_still_reads_unchanged(bridge):
    reply = _save(bridge, name="valid")
    state = json.loads(bridge.get_workspace_state())
    assert state["recent"] == [reply["path"]]
    assert state["last_snapshot"] == reply["path"]


# ── audit #3 R8b/N6: save and restore share one selection rule ────────────────

def test_save_reports_unknown_selected_ids(bridge, monkeypatch):
    """N6: save dropped unknown ids silently while restore refused them outright."""
    logs = _capture_logs(bridge, monkeypatch)
    reply = _save(bridge, name="unknown", selected=["arena_state", "future_thing"])
    assert reply["ok"] is True and reply["unknown_domains"] == ["future_thing"]
    assert any(level == "warn" and "future_thing" in message for level, message in logs)


def test_save_refuses_a_selection_of_only_unknown_ids(bridge, monkeypatch):
    logs = _capture_logs(bridge, monkeypatch)
    reply = _save(bridge, name="none", selected=["future_thing"])
    assert reply["ok"] is False and reply["unknown_domains"] == ["future_thing"]
    assert "future_thing" in reply["error"]
    assert any(level == "warn" and "future_thing" in message for level, message in logs)


# ── audit #3 H1 (ported from branch A): two saves with one name in one second ──

def test_two_saves_in_one_second_both_publish(bridge, monkeypatch):
    """The snapshot folder is second-resolution, so two saves with one name in
    the same second collided and the second was refused with 'publish failed:
    target already exists' — a legitimate action reported as a failure.
    `recover._recovery_dir` already disambiguates ITS folder (`-02`, `-03`);
    the snapshot folder now uses the same rule, so both saves land in their own
    folder and stay chronologically ordered.
    """
    frozen = time.struct_time((2026, 1, 1, 0, 0, 0, 0, 1, 0))
    monkeypatch.setattr(ws_save.time, "gmtime", lambda *_a, **_k: frozen)
    first = _save(bridge, name="dup")
    second = _save(bridge, name="dup")
    assert first["ok"] and second["ok"], (first, second)
    assert first["result"] == second["result"] == "success"
    assert first["path"] != second["path"]
    assert Path(second["path"]).name == "dup_20260101-000000-02"
    assert sorted([first["path"], second["path"]]) == [first["path"], second["path"]]
    for reply in (first, second):
        assert _manifest_of(reply)["name"] == "dup"


def test_a_second_save_in_a_different_second_is_unaffected(bridge):
    """The positive control: a normal save still gets the plain second-resolution
    folder name — the disambiguation only fires on a real collision.

    The clock is read on both sides of the save rather than after it: on a
    loaded machine the second can tick inside `save_workspace`, and the property
    under test is "plain stamp, no `-02` suffix", not "the same second as the
    assertion".
    """
    before = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    first = _save(bridge, name="solo")
    after = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    name = Path(first["path"]).name
    assert name in (f"solo_{before}", f"solo_{after}")
    assert not name.endswith(("-02", "-03"))
