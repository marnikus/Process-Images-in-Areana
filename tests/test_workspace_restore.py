"""Workspace restore — preview, fault isolation, per-domain transactions (W5/W6).

The corruption/dependency matrix of design §F, executed against a real
Bridge and a real snapshot folder: one bad file must never block unrelated
recovery; a failed apply rolls back only its own domain; strict dependents
skip while independents restore; stale live state is reconciled, never
resurrected.
"""

import json
from pathlib import Path

import pytest

from app.core.enums import JobStatus, RunState
from app.core.models import ImageItem, JobRecord
from app.persistence.config_manager import ConfigManager
from app.persistence.workspace.integrity import sha256_bytes
from app.services.workspace import restore as ws_restore
from app.services.workspace import save as ws_save
from app.services.workspace.apply import restore_workspace
from app.services.workspace.coordinator import SaveRequest
from app.services.workspace.registry import get
from app.ui.bridge import Bridge

pytestmark = pytest.mark.unit


@pytest.fixture()
def bridge(tmp_path):
    return Bridge(config_manager=ConfigManager(config_dir=str(tmp_path)),
                  state_path=tmp_path / "app_state.json")


@pytest.fixture()
def snapshot(bridge):
    """A good snapshot with recognizable values."""
    bridge.state.prompt["user_prompt"] = "saved prompt"
    bridge.config.set_state(cdp_port=9555)
    bridge.undo_service.push("prompt", {"user_prompt": "saved prompt"})
    reply = ws_save.save_workspace(bridge, SaveRequest(name="base"))
    assert reply["ok"]
    return Path(reply["path"])


def _restamp(snapshot: Path, rel: str) -> None:
    """Re-stamp one file's bytes/sha in the manifest (for gate-specific fixtures)."""
    from app.persistence.workspace.integrity import sha256_bytes
    manifest = json.loads((snapshot / "manifest.json").read_text())
    raw = (snapshot / rel).read_bytes()
    for entry in manifest["domains"].values():
        if entry.get("path") == rel:
            entry["bytes"] = len(raw)
            entry["sha256"] = sha256_bytes(raw)
    (snapshot / "manifest.json").write_text(json.dumps(manifest))


def _skip_of(reply, domain_id):
    for row in reply["skipped"]:
        if row["domain_id"] == domain_id:
            return row
    return None


# ---- preview ----

def test_preview_reads_manifest_and_mutates_nothing(bridge, snapshot):
    before = {p: p.stat().st_mtime_ns for p in sorted(bridge.config.dir.rglob("*.json"))}
    state_before = bridge.state.prompt["user_prompt"]
    preview = ws_restore.preview_restore(bridge, str(snapshot))
    after = {p: p.stat().st_mtime_ns for p in sorted(bridge.config.dir.rglob("*.json"))}
    assert before == after and state_before == bridge.state.prompt["user_prompt"]
    assert preview["ok"] and preview["snapshot_kind"] == "full"
    statuses = {d["domain_id"]: d["status"] for d in preview["domains"]}
    assert statuses["arena_state"] == "ok"
    assert statuses["captcha_keys"] == "excluded"
    assert statuses["captcha_recordings"] == "excluded"


def test_preview_flags_size_mismatch_and_missing(bridge, snapshot):
    (snapshot / "state/undo.json").write_text("{}")
    (snapshot / "state/job_history.json").unlink()
    preview = ws_restore.preview_restore(bridge, str(snapshot))
    statuses = {d["domain_id"]: d["status"] for d in preview["domains"]}
    assert statuses["undo"] == "size_mismatch"
    assert statuses["job_history"] == "missing"


def test_preview_refuses_a_foreign_folder(bridge, tmp_path):
    reply = ws_restore.preview_restore(bridge, str(tmp_path))
    assert reply["ok"] is False and "not a committed workspace" in reply["error"]


def test_preview_notes_missing_folder_root(bridge, snapshot):
    doc = json.loads((snapshot / "state/app_state.json").read_text())
    doc["folder"]["root_path"] = "/definitely/not/anywhere"
    (snapshot / "state/app_state.json").write_text(json.dumps(doc))
    preview = ws_restore.preview_restore(bridge, str(snapshot))
    assert any("re-pick the folder" in note for note in preview["path_remap_needed"])


# ---- restore all ----

def test_restore_all_round_trip(bridge, snapshot):
    bridge.state.prompt["user_prompt"] = "changed after save"
    bridge.config.set_state(cdp_port=1)
    bridge.undo_service.push("prompt", {"user_prompt": "changed after save"})
    reply = restore_workspace(bridge, str(snapshot))
    assert reply["ok"] and reply["result"] == "success"
    assert reply["skipped"] == []  # policy domains are excluded from the default selection
    assert bridge.state.prompt["user_prompt"] == "saved prompt"
    assert bridge.config.get_state("cdp_port") == 9555
    assert reply["restored"] == ["captcha_stats", "cooldowns", "arena_state",
                                 "session_settings", "grid_window", "undo",
                                 "window_presets", "arena_presets", "job_history"]
    assert (snapshot / "reports/restore-report.json").exists()
    assert reply["backup"] and Path(reply["backup"]).exists()


def test_restore_report_is_written_into_the_workspace(bridge, snapshot):
    restore_workspace(bridge, str(snapshot))
    report = json.loads((snapshot / "reports/restore-report.json").read_text())
    assert report["result"] == "success"
    assert report["backup"] and "restored" in report


# ---- one corrupt file must not block the others ----

def test_corrupt_json_skips_one_domain_and_restores_the_rest(bridge, snapshot):
    (snapshot / "state/undo.json").write_text("{not json", encoding="utf-8")
    _restamp(snapshot, "state/undo.json")  # size+sha now match → the parse gate fires
    bridge.undo_service.push("prompt", {"x": "later"})
    reply = restore_workspace(bridge, str(snapshot))
    row = _skip_of(reply, "undo")
    assert row["stage"] == "parse" and row["recommended_action"]
    assert "arena_state" in reply["restored"] and "job_history" in reply["restored"]


def test_checksum_mismatch_is_reported_with_expected_actual(bridge, snapshot):
    undo = snapshot / "state/undo.json"
    doc = json.loads(undo.read_text())
    doc["history"] = []
    undo.write_text(json.dumps(doc))
    reply = restore_workspace(bridge, str(snapshot))
    row = _skip_of(reply, "undo")
    assert row["stage"] == "checksum" and "mismatch" in row["cause"]
    assert "expected" in row and "actual" in row


def test_missing_file_skips_only_its_domain(bridge, snapshot):
    (snapshot / "state/cooldowns.json").unlink()
    reply = restore_workspace(bridge, str(snapshot))
    assert _skip_of(reply, "cooldowns")["stage"] == "missing"
    assert "arena_state" in reply["restored"]


def test_unsafe_manifest_path_is_refused(bridge, snapshot):
    manifest = json.loads((snapshot / "manifest.json").read_text())
    manifest["domains"]["undo"]["path"] = "../../outside.json"
    (snapshot / "manifest.json").write_text(json.dumps(manifest))
    reply = restore_workspace(bridge, str(snapshot))
    assert _skip_of(reply, "undo")["stage"] == "unsafe_path"


def test_unsupported_future_version_is_refused_precisely(bridge, snapshot):
    manifest = json.loads((snapshot / "manifest.json").read_text())
    manifest["domains"]["undo"]["schema_version"] = "999"
    (snapshot / "manifest.json").write_text(json.dumps(manifest))
    reply = restore_workspace(bridge, str(snapshot))
    row = _skip_of(reply, "undo")
    assert row["stage"] == "schema" and "999" in row["cause"]
    assert "Update the app" in row["recommended_action"]


def test_semantic_failure_skips_the_domain(bridge, snapshot):
    undo = snapshot / "state/undo.json"
    doc = json.loads(undo.read_text())
    sha_hit = doc  # keep bytes consistent by rewriting manifest too
    doc["history"] = "not-a-list"
    undo.write_text(json.dumps(doc))
    manifest = json.loads((snapshot / "manifest.json").read_text())
    entry = manifest["domains"]["undo"]
    from app.persistence.workspace.integrity import canonical_bytes, sha256_bytes
    raw = undo.read_bytes()
    entry["bytes"] = len(raw)
    entry["sha256"] = sha256_bytes(raw)
    (snapshot / "manifest.json").write_text(json.dumps(manifest))
    reply = restore_workspace(bridge, str(snapshot))
    row = _skip_of(reply, "undo")
    assert row["stage"] == "semantic" and "'history' must be a list" in row["cause"]


# ---- per-domain transaction ----

def test_failed_apply_rolls_back_only_that_domain(bridge, snapshot, monkeypatch):
    import app.services.workspace.providers.arena_state as arena_mod
    real_save = arena_mod.save_state
    calls = {"n": 0}

    def flaky_save(state, path):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("cloud sync replaced the file")
        real_save(state, path)

    monkeypatch.setattr(arena_mod, "save_state", flaky_save)
    bridge.state.prompt["user_prompt"] = "current live"
    reply = restore_workspace(bridge, str(snapshot))
    row = _skip_of(reply, "arena_state")
    assert row["stage"] == "apply" and row.get("rolled_back") is True
    assert bridge.state.prompt["user_prompt"] == "current live"  # rollback happened
    assert "arena_state" not in reply["restored"]
    assert "job_history" in reply["restored"]  # independents continue


def test_failed_apply_with_failed_rollback_is_damaged_and_loud(bridge, snapshot,
                                                                monkeypatch):
    import app.services.workspace.providers.arena_state as arena_mod
    monkeypatch.setattr(arena_mod, "save_state",
                        lambda state, path: (_ for _ in ()).throw(PermissionError("locked")))
    reply = restore_workspace(bridge, str(snapshot))
    damaged = [r for r in reply["skipped"] if r.get("status") == "damaged"]
    assert damaged and "recovery" in damaged[0]["cause"]
    assert reply["result"] == "success_with_warnings"  # independents still restored


def test_strict_dependency_skip_chain(bridge, snapshot, monkeypatch):
    arena = get("arena_state")
    cooldowns = get("cooldowns")
    monkeypatch.setattr(arena, "dependencies", {"cooldowns": "strict"})
    monkeypatch.setattr(cooldowns, "validate", lambda doc: "injected semantic failure")
    reply = restore_workspace(bridge, str(snapshot))
    cooldown_row = _skip_of(reply, "cooldowns")
    arena_row = _skip_of(reply, "arena_state")
    assert cooldown_row["stage"] == "semantic"
    assert arena_row["stage"] == "dependency"
    assert "cooldowns" in arena_row["cause"]
    assert "undo" in reply["restored"]  # independents never blocked


# ---- partial restore by domain ----

def test_single_domain_restore_touches_only_that_domain(bridge, snapshot):
    bridge.state.prompt["user_prompt"] = "live prompt"
    bridge.config.set_state(cdp_port=1)
    reply = restore_workspace(bridge, str(snapshot), selected=["session_settings"])
    assert reply["restored"] == ["session_settings"]
    assert bridge.config.get_state("cdp_port") == 9555
    assert bridge.state.prompt["user_prompt"] == "live prompt"  # untouched


def test_selection_by_unknown_domain_is_refused(bridge, snapshot):
    reply = restore_workspace(bridge, str(snapshot), selected=["nope"])
    assert reply["ok"] is False and "unknown domain" in reply["error"]


def test_policy_domain_selected_answers_with_its_action(bridge, snapshot):
    reply = restore_workspace(bridge, str(snapshot), selected=["captcha_keys"])
    row = _skip_of(reply, "captcha_keys")
    assert row["policy"] is True and "Re-enter the API key" in row["recommended_action"]


# ---- grid / live reconcile ----

def test_invalid_grid_keeps_current_layout_and_session_keys(bridge, snapshot):
    bridge.config.set_state(cdp_port=1, grid_layout=json.dumps({"v": 9, "tree": None}))
    current = bridge.config.get_state("grid_layout")
    undo = snapshot / "state/session.json"
    doc = json.loads(undo.read_text())
    doc["grid_layout"] = "{broken grid"
    from app.persistence.workspace.integrity import sha256_bytes
    raw = json.dumps(doc).encode("utf-8")
    undo.write_bytes(raw)
    manifest = json.loads((snapshot / "manifest.json").read_text())
    for domain_id in ("session_settings", "grid_window"):
        manifest["domains"][domain_id]["bytes"] = len(raw)
        manifest["domains"][domain_id]["sha256"] = sha256_bytes(raw)
    (snapshot / "manifest.json").write_text(json.dumps(manifest))
    reply = restore_workspace(bridge, str(snapshot))
    row = _skip_of(reply, "grid_window")
    assert row and row["stage"] == "semantic" and "invalid grid" in row["cause"]
    assert bridge.config.get_state("grid_layout") == current  # retained, not defaulted
    assert bridge.config.get_state("cdp_port") == 9555  # session keys still applied


def test_stale_run_state_and_inflight_jobs_reconcile(bridge, snapshot):
    bridge.state.run_state = RunState.RUNNING.value
    bridge.state.jobs = [JobRecord(
        job_id="j1", image_id="i1", image_path="p", url_id="u", url="x",
        correlation_id="c", attempt=1, status=JobStatus.WAITING_GENERATION.value,
        created_at="2026-09-25T00:00:00Z")]
    bridge.state.images = [ImageItem(
        id="i1", relative_path="a.png", absolute_path="/x/a.png", filename="a.png",
        base_name="a", extension=".png", size=1, mtime=0.0, fingerprint="f",
        status="processing")]
    stale = ws_save.save_workspace(bridge, SaveRequest(name="stale"))
    reply = restore_workspace(bridge, str(Path(stale["path"])))
    assert bridge.state.run_state == "idle"  # a saved run is never revived
    assert bridge.state.jobs[0].status == JobStatus.INTERRUPTED.value
    assert bridge.state.images[0].status == "failed"
    notes = " ".join(reply["reconciled"])
    assert "never revived" in notes and "interrupted" in notes


def test_recovery_backup_holds_previous_live_files(bridge, snapshot):
    bridge.state.prompt["user_prompt"] = "live"
    bridge._save_arena()  # the live state file exists on disk
    restore_workspace(bridge, str(snapshot))
    recovery_dirs = sorted((bridge.config.dir / "workspace_recovery").iterdir())
    assert recovery_dirs, "recovery snapshot missing"
    files = {p.name for p in recovery_dirs[-1].iterdir()}
    assert any(name.startswith("arena_state__") for name in files)
    recovery = json.loads((recovery_dirs[-1] / "recovery.json").read_text())
    assert any(name.startswith("arena_state__") for name in recovery["files"]["arena_state"])


def test_recovery_backup_on_a_fresh_machine_restores_without_crashing(bridge, snapshot):
    # fresh machine: no app_state.json yet — the restore must not crash; the
    # snapshot holds only the files that DO exist (providers pre-filter), and
    # the absent app_state file is simply not listed.
    reply = restore_workspace(bridge, str(snapshot))
    assert reply["ok"]
    recovery_dirs = sorted((bridge.config.dir / "workspace_recovery").iterdir())
    assert recovery_dirs, "recovery snapshot still created"
    recovery = json.loads((recovery_dirs[-1] / "recovery.json").read_text())
    assert "arena_state" not in recovery["files"]
    assert {"grid_window", "session_settings", "undo"} <= set(recovery["files"])
    assert recovery["absent"] == {}
    assert bridge.state.prompt["user_prompt"] == "saved prompt"  # restore applied


# ---- R0 characterization: the seams the refactor moves (audit §5 R0) ----

class _FakeProvider:
    """Minimal provider stand-in for dependency-expansion tests."""

    def __init__(self, domain_id, dependencies=None):
        self.domain_id = domain_id
        self.dependencies = dependencies or {}


def test_expand_strict_follows_a_transitive_chain(monkeypatch):
    from app.services.workspace import restore as ws_restore
    chain = {"a": _FakeProvider("a", {"b": "strict"}),
             "b": _FakeProvider("b", {"c": "strict"}),
             "c": _FakeProvider("c")}
    monkeypatch.setattr(ws_restore, "get", chain.get)
    monkeypatch.setattr(ws_restore, "RESTORE_ORDER", ("c", "b", "a"))
    providers = ws_restore._expand_strict([chain["a"]])
    assert [p.domain_id for p in providers] == ["c", "b", "a"]  # registry order


def test_expand_strict_keeps_registered_providers_outside_the_order_tuple(monkeypatch):
    # D3: a provider that IS registered but missing from RESTORE_ORDER must still
    # ride along — save tolerates order drift, restore must not silently drop it.
    from app.services.workspace import restore as ws_restore
    late = _FakeProvider("late")
    chain = {"a": _FakeProvider("a", {"late": "strict"}), "late": late}
    monkeypatch.setattr(ws_restore, "get", chain.get)
    monkeypatch.setattr(ws_restore, "RESTORE_ORDER", ("a",))
    providers = ws_restore._expand_strict([chain["a"]])
    assert [p.domain_id for p in providers] == ["a", "late"]  # unknown-order ids after known


def test_load_one_gate_evidence_fields(tmp_path):
    from app.persistence.workspace.integrity import sha256_bytes
    root = tmp_path
    good = b'"abcd"'  # valid JSON, parses to the string "abcd"
    entry = {"display_name": "Undo History", "path": "state/undo.json",
             "bytes": len(good), "sha256": sha256_bytes(good)}
    (root / "state").mkdir()
    (root / "state/undo.json").write_bytes(good)
    assert ws_restore._load_one(root, entry, "state/undo.json") == "abcd"
    (root / "state/undo.json").write_bytes(b'"xxxx"')  # same size, different sha
    bad_sha = ws_restore._load_one(root, entry, "state/undo.json")
    assert bad_sha.stage == "checksum" and bad_sha.expected == entry["sha256"][:12]
    assert len(bad_sha.actual) == 12
    unsafe = ws_restore._load_one(root, {"path": "../escape.json"}, "../escape.json")
    assert unsafe.stage == "unsafe_path"
    missing = ws_restore._load_one(root, {"path": "state/gone.json"}, "state/gone.json")
    assert missing.stage == "missing"
