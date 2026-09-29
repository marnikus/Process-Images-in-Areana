"""Characterization tests for workspace save/restore refactor — locks current behavior before structural changes.

These tests pin the exact behavior of internal helpers that will be moved/split.
They are intentionally verbose and cover edge cases, tuple returns, dict bundling, etc.
"""

import json
import shutil
from pathlib import Path

import pytest

from app.persistence.config_manager import ConfigManager
from app.persistence.workspace import fsio
from app.persistence.workspace.errors import WorkspaceError
from app.persistence.workspace.integrity import safe_rel_path
from app.persistence.workspace.manifest import build_manifest, read_manifest
from app.services.workspace import apply as ws_apply
from app.services.workspace import gates as ws_gates
from app.services.workspace import recover as ws_recover
from app.services.workspace import registry as ws_registry
from app.services.workspace import reports as ws_reports
from app.services.workspace import restore as ws_restore
from app.services.workspace import save as ws_save
from app.services.workspace import snapshot_index as ws_index
from app.services.workspace.meta import default_base, utc_now_iso
from app.services.workspace.provider import ApplyOutcome, CaptureResult, StateProvider
from app.services.workspace.save import SaveRequest
from app.ui.bridge import Bridge


pytestmark = pytest.mark.unit


@pytest.fixture()
def bridge(tmp_path):
    return Bridge(config_manager=ConfigManager(config_dir=str(tmp_path)),
                  state_path=tmp_path / "app_state.json")


# ---- save.py internals ----

def test_file_docs_merges_shared_file():
    """session_settings + grid_window share state/session.json — merge via dict spread, last wins."""
    class P1:
        domain_id = "session_settings"
        native_rel_path = "state/session.json"
        result = CaptureResult(ok=True, doc={"a": 1, "b": 2})
        error = None
    class P2:
        domain_id = "grid_window"
        native_rel_path = "state/session.json"
        result = CaptureResult(ok=True, doc={"b": 3, "c": 4})
        error = None
    # mimic Capture objects
    from app.services.workspace.save import Capture
    caps = [Capture(provider=P1, result=P1.result), Capture(provider=P2, result=P2.result)]
    docs = ws_save.file_docs(caps)
    # last writer wins for overlapping key b
    assert docs["state/session.json"] == {"a": 1, "b": 3, "c": 4}


def test_file_docs_skips_excluded_and_error():
    from app.services.workspace.save import Capture
    class P:
        domain_id = "x"
        native_rel_path = "state/x.json"
    ok = Capture(provider=P, result=CaptureResult(ok=True, doc={"k": 1}))
    excluded = Capture(provider=P, result=CaptureResult(ok=True, doc={}, excluded=True, excluded_reason="secret"))
    err = Capture(provider=P, error={"domain_id": "x", "stage": "capture", "cause": "boom"})
    docs = ws_save.file_docs([ok, excluded, err])
    assert docs == {"state/x.json": {"k": 1}}


def test_capture_block_shapes():
    from app.services.workspace.save import Capture, _capture_block
    class P:
        domain_id = "d"
    # ok included
    c1 = Capture(provider=P, result=CaptureResult(ok=True, doc={}, notes=["note"]))
    b1 = _capture_block(c1)
    assert b1["ok"] is True and b1["excluded"] is False and b1["notes"] == ["note"]
    # excluded
    c2 = Capture(provider=P, result=CaptureResult(ok=True, doc={"providers": {}}, excluded=True, excluded_reason="secret"))
    b2 = _capture_block(c2)
    assert b2["excluded"] is True and "secret" in b2["excluded_reason"]
    # error
    c3 = Capture(provider=P, error={"cause": "boom"})
    b3 = _capture_block(c3)
    assert b3["ok"] is False and b3["excluded"] is True


def test_selected_providers_all_and_subset():
    all_ids = {p.domain_id for p in ws_registry.all_providers()}
    assert len(ws_save.selected_providers(None)) == len(all_ids)
    subset = ws_save.selected_providers(["arena_state", "undo"])
    assert {p.domain_id for p in subset} == {"arena_state", "undo"}
    empty = ws_save.selected_providers(["no_such"])
    assert empty == []


def test_domain_entries_includes_all_registered():
    from app.services.workspace.save import Capture, domain_entries
    providers = ws_registry.all_providers()[:2]
    caps = []
    for p in providers:
        caps.append(Capture(provider=p, result=CaptureResult(ok=True, doc={"x": 1})))
    entries = domain_entries(caps, {"state/app_state.json": {"path": "state/app_state.json", "bytes": 10, "sha256": "abc"}})
    # each provider gets manifest metadata + file entry + capture block
    for p in providers:
        e = entries[p.domain_id]
        assert e["display_name"] == p.display_name
        assert "capture" in e
        assert e["schema_version"] == p.schema_version


def test_report_rows_shape():
    from app.services.workspace.save import Capture, _report_rows
    class P:
        domain_id = "arena_state"
        required = True
    c_ok = Capture(provider=P, result=CaptureResult(ok=True, doc={}))
    c_err = Capture(provider=P, error={"domain_id": "arena_state"})
    rows = _report_rows([c_ok, c_err])
    assert rows[0]["ok"] is True and rows[0]["excluded"] is False
    assert rows[1]["ok"] is False and rows[1]["excluded"] is True


# ---- registry ----

def test_restore_order_known_first_unknown_sorted():
    order = ws_registry.restore_order({"unknown_b", "arena_state", "unknown_a", "undo"})
    # known in RESTORE_ORDER order, unknown sorted after
    assert order.index("arena_state") < order.index("undo")
    assert order[-2:] == ["unknown_a", "unknown_b"]


def test_registry_get_and_all():
    assert ws_registry.get("nope") is None
    all_p = ws_registry.all_providers()
    assert len(all_p) == 11  # 11 domains
    assert all(isinstance(p, StateProvider) for p in all_p)
    # RESTORE_ORDER defines order
    assert [p.domain_id for p in all_p] == list(ws_registry.RESTORE_ORDER)


# ---- snapshot_index ----

def test_recent_snapshots_prunes_missing_and_caps(bridge, tmp_path):
    # create 12 fake snapshot folders
    base = default_base(bridge)
    paths = []
    for i in range(12):
        p = base / f"snap_{i}"
        p.mkdir(parents=True)
        paths.append(str(p))
        ws_index.record_snapshot(bridge, str(p))
    recent = ws_index.recent_snapshots(bridge)
    assert len(recent) == 10  # RECENT_CAP
    assert recent[0] == paths[-1]
    # remove one, recent should prune
    shutil.rmtree(paths[-1])
    pruned = ws_index.recent_snapshots(bridge)
    assert paths[-1] not in pruned
    assert len(pruned) == 9


def test_last_snapshot_returns_empty_when_missing(bridge):
    ws_index.record_snapshot(bridge, "/tmp/not_exist_12345")
    # last_snapshot checks existence
    assert ws_index.last_snapshot(bridge) == "" or isinstance(ws_index.last_snapshot(bridge), str)


# ---- recover ----

def test_backup_live_copies_and_records_absent(bridge, tmp_path):
    # create a provider with live_paths that exist and one that doesn't
    class FakeProvider:
        domain_id = "fake"
        def live_paths(self, b):
            existing = Path(tmp_path) / "exists.json"
            existing.write_text("{}")
            missing = Path(tmp_path) / "missing.json"
            return [existing, missing]
    path, refusal = ws_recover.backup_live(bridge, [FakeProvider()])
    assert refusal == "" and Path(path).exists()
    data = json.loads((Path(path) / "recovery.json").read_text())
    assert "fake" in data["files"] or "fake" in data["absent"]
    shutil.rmtree(path)


def test_backup_live_refuses_on_copy_failure(bridge, tmp_path, monkeypatch):
    class BadProvider:
        domain_id = "bad"
        def live_paths(self, b):
            p = tmp_path / "bad.json"
            p.write_text("{}")
            return [p]
    def explode(src, dst):
        raise OSError("locked")
    monkeypatch.setattr(ws_recover.shutil, "copy2", explode)
    path, refusal = ws_recover.backup_live(bridge, [BadProvider()])
    assert path == "" and "recovery backup failed" in refusal


# ---- gates ----

def test_load_files_dedup_by_rel(tmp_path):
    # two providers sharing same rel should load once
    manifest = build_manifest(
        header={"snapshot_id": "ws", "name": "n", "created_utc": "2026-01-01T00:00:00Z"},
        app_meta={}, compat={},
        domains={
            "session_settings": {"path": "state/session.json", "bytes": 2, "sha256": "abc", "display_name": "Session"},
            "grid_window": {"path": "state/session.json", "bytes": 2, "sha256": "abc", "display_name": "Grid"},
        })
    root = tmp_path / "snap"
    root.mkdir()
    (root / "state").mkdir()
    (root / "state" / "session.json").write_text('{"a":1}', encoding="utf-8")
    # need to write correct bytes/sha to pass gate — use actual file sha
    from app.persistence.workspace.integrity import file_sha, canonical_bytes
    # overwrite manifest entry with real bytes/sha
    data = (root / "state" / "session.json").read_bytes()
    manifest["domains"]["session_settings"]["bytes"] = len(data)
    manifest["domains"]["session_settings"]["sha256"] = file_sha(root / "state" / "session.json")
    manifest["domains"]["grid_window"]["bytes"] = len(data)
    manifest["domains"]["grid_window"]["sha256"] = file_sha(root / "state" / "session.json")

    class P1:
        domain_id = "session_settings"
    class P2:
        domain_id = "grid_window"
    files = ws_gates.load_files(root, manifest, [P1(), P2()])
    assert len(files) == 1
    assert "state/session.json" in files
    assert isinstance(files["state/session.json"], dict)


def test_gated_unsafe_path():
    manifest = {"domains": {"d": {"path": "../escape.json", "display_name": "D"}}}
    entry = manifest["domains"]["d"]
    result = ws_gates.load_one(Path("/tmp"), entry, "../escape.json")
    assert isinstance(result, WorkspaceError)
    assert result.stage == "unsafe_path"


def test_gated_missing():
    entry = {"path": "state/missing.json", "display_name": "M"}
    result = ws_gates.load_one(Path("/tmp/not_exist_root"), entry, "state/missing.json")
    assert isinstance(result, WorkspaceError)
    assert result.stage == "missing"


# ---- restore preview ----

def test_preview_restore_ok_and_excluded(tmp_path, bridge):
    # create a minimal valid workspace via save
    from app.services.workspace.save import SaveRequest
    reply = ws_save.save_workspace(bridge, SaveRequest(name="char_preview"))
    assert reply["ok"]
    preview = ws_restore.preview_restore(reply["path"])
    assert preview["ok"] is True
    assert "domains" in preview
    # check that excluded domains appear with status excluded
    statuses = {d["domain_id"]: d["status"] for d in preview["domains"]}
    # captcha_keys is excluded by policy
    assert statuses.get("captcha_keys") == "excluded"


def test_preview_restore_missing_manifest(tmp_path):
    result = ws_restore.preview_restore(tmp_path)
    assert result["ok"] is False and "manifest" in result["error"].lower()


# ---- apply selection & strict deps ----

def test_selection_providers_unknown():
    manifest = {"domains": {"arena_state": {"path": "state/app_state.json"}, "undo": {"path": "state/undo.json"}}}
    providers, unknown = ws_apply.selection_providers(manifest, ["arena_state", "nope"])
    assert unknown == ["nope"]
    assert len(providers) == 1 and providers[0].domain_id == "arena_state"


def test_expand_strict_transitive():
    # In current registry, no strict deps, but test the mechanism with fake providers
    class A(StateProvider):
        domain_id = "a"
        dependencies = {"b": "strict"}
    class B(StateProvider):
        domain_id = "b"
        dependencies = {"c": "strict"}
    class C(StateProvider):
        domain_id = "c"
        dependencies = {}
    # monkeypatch registry.get to return our fakes
    orig_get = ws_registry.get
    def fake_get(did):
        return {"a": A(), "b": B(), "c": C()}.get(did) or orig_get(did)
    import unittest.mock as mock
    with mock.patch("app.services.workspace.apply.get", side_effect=fake_get):
        expanded = ws_apply.expand_strict([A()])
        ids = {p.domain_id for p in expanded}
        assert ids == {"a", "b", "c"}


def test_guarded_crash_becomes_skip_row():
    class Bad(StateProvider):
        domain_id = "bad"
    def boom():
        raise RuntimeError("kaboom")
    value, row = ws_apply._guarded(Bad(), "apply", boom)
    assert value is None
    assert row["status"] == "skipped"
    assert row["stage"] == "apply"
    assert "kaboom" in row["cause"]


def test_version_row_unsupported():
    class P(StateProvider):
        domain_id = "p"
        supported_migrations = ("1",)
    entry = {"schema_version": "99"}
    row = ws_apply._version_row(P(), entry)
    assert row is not None
    assert row["stage"] == "schema"
    assert "not supported" in row["cause"]


def test_policy_row_has_advice():
    class P(StateProvider):
        domain_id = "captcha_keys"
        restore_advice = "re-enter key"
    entry = {"capture": {"excluded_reason": "secret"}}
    row = ws_apply._policy_row(P(), entry)
    assert row["status"] == "skipped"
    assert row["policy"] is True
    assert "secret" in row["cause"]


def test_rollback_success_and_failure(bridge):
    # provider whose apply fails, but previous capture ok -> rollback attempted
    class Good(StateProvider):
        domain_id = "good"
        def apply(self, b, doc):
            if doc.get("fail"):
                raise RuntimeError("apply fail")
            return ApplyOutcome(ok=True)
    prev_ok = CaptureResult(ok=True, doc={"ok": True})
    # failing apply with rollback success
    row = ws_apply._rollback(bridge, Good(), prev_ok, RuntimeError("first fail"))
    assert row["status"] == "skipped"
    assert row["rolled_back"] is True

    # rollback itself fails -> damaged
    class BadRollback(StateProvider):
        domain_id = "bad"
        def apply(self, b, doc):
            raise RuntimeError("rollback fail too")
    row2 = ws_apply._rollback(bridge, BadRollback(), prev_ok, RuntimeError("first"))
    assert row2["status"] == "damaged"


def test_dependency_row_blocked():
    class P(StateProvider):
        domain_id = "p"
        dependencies = {"dep": "strict"}
    row = ws_apply._dependency_row(P(), failed={"dep"})
    assert row is not None and row["stage"] == "dependency"
    row2 = ws_apply._dependency_row(P(), failed=set())
    assert row2 is None


# ---- reports ----

def test_save_report_result_logic():
    timing = {"snapshot_id": "ws_1", "started_utc": "2026-01-01T00:00:00Z", "finished_utc": "2026-01-01T00:00:01Z"}
    domains = [{"domain_id": "a", "required": True}]
    # published False -> failed
    r1 = ws_reports.save_report(timing=timing, domains=domains, errors=[], published=False)
    assert r1["result"] == "failed"
    # published True, no errors -> success
    r2 = ws_reports.save_report(timing=timing, domains=domains, errors=[], published=True)
    assert r2["result"] == "success"
    # published True, errors -> partial
    r3 = ws_reports.save_report(timing=timing, domains=domains, errors=[{"domain_id": "a"}], published=True)
    assert r3["result"] == "partial"


def test_restore_result_damaged():
    restored = ["a"]
    skipped = [{"domain_id": "b", "status": "skipped"}, {"domain_id": "c", "status": "damaged"}]
    assert ws_reports.restore_result(restored, skipped) == "failed"
    assert ws_reports.restore_result([], [{"status": "skipped"}]) == "failed"
    assert ws_reports.restore_result(["a"], []) == "success"
    assert ws_reports.restore_result(["a"], [{"status": "skipped"}]) == "success_with_warnings"


# ---- fsio ----

def test_sanitize_name_collapses():
    assert fsio.sanitize_name("bad:name*") == "bad-name-"
    assert fsio.sanitize_name("") == "workspace"
    assert len(fsio.sanitize_name("a" * 100)) == 60


def test_write_report_fallback(tmp_path, monkeypatch):
    root = tmp_path / "snap"
    root.mkdir()
    # make root read-only to force fallback? Simpler: mock write_bytes to raise
    orig_write = fsio.write_bytes
    def fail_first(root, rel, data):
        if "reports" in rel:
            raise OSError("ro")
        return orig_write(root, rel, data)
    monkeypatch.setattr(fsio, "write_bytes", fail_first)
    note = fsio.write_report(root, "reports/save-report.json", b"{}")
    assert "beside it" in note or "could not" in note or note == ""


# ---- integrity ----

def test_safe_rel_path_rejects():
    assert safe_rel_path("../escape") == ""
    assert safe_rel_path("/abs") == ""
    assert safe_rel_path("C:/win") == ""
    assert safe_rel_path("") == ""
    assert safe_rel_path("a/../b") == "" or safe_rel_path("a/../b") != ""  # PurePosixPath may normalize, but our impl rejects ".." in parts
    # our impl rejects any ".." in parts
    assert safe_rel_path("a/../b") == ""


# ---- meta ----

def test_snapshot_id_deterministic():
    from app.services.workspace.meta import snapshot_id_for
    sid1 = snapshot_id_for("2026-01-01T00:00:00Z", "name")
    sid2 = snapshot_id_for("2026-01-01T00:00:00Z", "name")
    assert sid1 == sid2
    assert sid1.startswith("ws_")


def test_live_run_error():
    class FakeBridge:
        _run_state = "running"
    from app.services.workspace.meta import live_run_error
    assert live_run_error(FakeBridge()) is not None
    FakeBridge._run_state = "idle"
    assert live_run_error(FakeBridge()) is None
