"""Workspace save — the SAVE algorithm (W4): temp folder, manifest last,
atomic publish, required-domain abort, partial confirmation, determinism,
interrupted-save semantics, meta/quick-load. Real FS on tmp_path only.
"""

import json
import shutil
from pathlib import Path

import pytest

from app.persistence.config_manager import ConfigManager
from app.persistence.workspace import fsio
from app.persistence.workspace.manifest import read_manifest
from app.services.workspace import save as ws_save
from app.services.workspace.coordinator import SaveRequest, default_base
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


def test_partial_snapshot_requires_explicit_confirmation(bridge, monkeypatch):
    monkeypatch.setattr(get("job_history"), "capture",
                        lambda bridge: CaptureResult(ok=False))
    refused = _save(bridge, name="r1")
    allowed = _save(bridge, name="r2", allow_partial=True)
    assert refused["ok"] is False and "allow a partial snapshot" in refused["error"]
    assert "job_history" in refused["error"]  # ANY failed selected domain needs confirmation
    assert allowed["ok"] and allowed["result"] == "partial"
    manifest = _manifest_of(allowed)
    assert manifest["snapshot_kind"] == "partial"
    assert manifest["domains"]["job_history"]["capture"]["excluded"] is True


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
    recent = ws_save.recent_snapshots(bridge)
    assert recent[0] == second["path"] and first["path"] in recent
    assert ws_save.last_snapshot(bridge) == second["path"]
    ws_save.record_restore(bridge, first["path"], "success_with_warnings")
    assert ws_save.last_restore(bridge)["result"] == "success_with_warnings"


def test_last_snapshot_drops_when_folder_removed(bridge):
    reply = _save(bridge, name="gone")
    shutil.rmtree(reply["path"])
    assert ws_save.last_snapshot(bridge) == ""
    assert reply["path"] not in ws_save.recent_snapshots(bridge)
