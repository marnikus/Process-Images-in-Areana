"""Workspace failure edges — audit #2 (docs/archive/2026-09-28-workspace-refactor-2/audit.md).

Each test reproduces one defect the audit found by probing the real code
(P1–P10) and pins the contract of design §F: a crash inside one domain is
that domain's row, the run always ends in a report, nothing claims more than
happened. Real Bridge, real snapshot folders, temporary dirs only.
"""

import json
from pathlib import Path

import pytest

from app.persistence.config_manager import ConfigManager
from app.services.workspace import save as ws_save
from app.services.workspace import snapshot_index
from app.services.workspace.apply import restore_workspace
from app.services.workspace.registry import get
from app.services.workspace.save import SaveRequest
from app.ui.bridge import Bridge
from tests.test_workspace_restore import _restamp

pytestmark = pytest.mark.unit


@pytest.fixture()
def bridge(tmp_path):
    return Bridge(config_manager=ConfigManager(config_dir=str(tmp_path)),
                  state_path=tmp_path / "app_state.json")


@pytest.fixture()
def snapshot(bridge):
    bridge.state.prompt["user_prompt"] = "saved prompt"
    bridge.undo_service.push("prompt", {"user_prompt": "saved prompt"})
    reply = ws_save.save_workspace(bridge, SaveRequest(name="base"))
    assert reply["ok"]
    return Path(reply["path"])


def _row(reply, domain_id):
    return next(r for r in reply["skipped"] if r["domain_id"] == domain_id)


def _raise(exc):
    def boom(*_a, **_k):
        raise exc
    return boom


# ---- step 4 (A1): a provider crash is its own domain's row -------------------

def test_malformed_stamped_doc_is_one_row_not_a_crash(bridge, snapshot):
    """P1: an unhashable image id made arena_state.validate raise out of the run."""
    rel = "state/app_state.json"
    doc = json.loads((snapshot / rel).read_text())
    doc["images"] = [{"id": ["unhashable"], "relative_path": "a.png"}]
    (snapshot / rel).write_text(json.dumps(doc))
    _restamp(snapshot, rel)
    reply = restore_workspace(bridge, snapshot)
    row = _row(reply, "arena_state")
    assert row["stage"] == "semantic" and "TypeError" in row["cause"]
    assert "undo" in reply["restored"]
    assert (snapshot / "reports" / "restore-report.json").exists()
    assert snapshot_index.last_restore(bridge)["path"] == str(snapshot)


def test_migration_that_raises_is_a_migration_row(bridge, snapshot, monkeypatch):
    manifest = json.loads((snapshot / "manifest.json").read_text())
    manifest["domains"]["grid_window"]["schema_version"] = "8"
    (snapshot / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(type(get("grid_window")), "migrate", _raise(KeyError("tree")))
    reply = restore_workspace(bridge, snapshot)
    row = _row(reply, "grid_window")
    assert row["stage"] == "migration" and "KeyError" in row["cause"]
    assert "session_settings" in reply["restored"]


def test_pre_apply_capture_crash_never_applies(bridge, snapshot, monkeypatch):
    """No rollback point → the domain is not touched at all."""
    provider = type(get("undo"))
    applied = []
    monkeypatch.setattr(provider, "capture", _raise(OSError("locked")))
    monkeypatch.setattr(provider, "apply", lambda self, b, d: applied.append(d))
    reply = restore_workspace(bridge, snapshot, selected=["undo"])
    row = _row(reply, "undo")
    assert applied == [] and row["stage"] == "apply" and not row.get("rolled_back")
    assert "not applied" in row["cause"]


def test_unreadable_snapshot_file_is_a_row_not_a_crash(bridge, snapshot, monkeypatch):
    from app.services.workspace import gates
    monkeypatch.setattr(gates, "file_sha", _raise(PermissionError(13, "locked by sync")))
    reply = restore_workspace(bridge, snapshot)
    assert reply["result"] == "failed"
    assert {r["stage"] for r in reply["skipped"] if not r.get("policy")} == {"parse"}


# ---- step 5 (A2, A3): the report never claims more than happened ------------

def test_rolled_back_only_when_a_rollback_ran(bridge, snapshot, monkeypatch):
    """P2: no usable pre-apply capture → no rollback → rolled_back is False."""
    from app.services.workspace.provider import CaptureResult
    provider = type(get("undo"))
    monkeypatch.setattr(provider, "capture", lambda self, b: CaptureResult(ok=False))
    monkeypatch.setattr(provider, "apply", _raise(RuntimeError("disk")))
    row = _row(restore_workspace(bridge, snapshot, selected=["undo"]), "undo")
    assert row["stage"] == "apply" and row["rolled_back"] is False


def test_rolled_back_true_when_the_rollback_succeeded(bridge, snapshot, monkeypatch):
    provider = type(get("undo"))
    real_apply, calls = provider.apply, []

    def apply_once_fails(self, b, doc):
        calls.append(doc)
        if len(calls) == 1:
            raise RuntimeError("disk")
        return real_apply(self, b, doc)
    monkeypatch.setattr(provider, "apply", apply_once_fails)
    row = _row(restore_workspace(bridge, snapshot, selected=["undo"]), "undo")
    assert row["rolled_back"] is True and len(calls) == 2


def test_damaged_domain_fails_the_restore(bridge, snapshot, monkeypatch):
    """P3: apply AND rollback failed → live state unknown → result failed, not warnings."""
    monkeypatch.setattr(type(get("undo")), "apply", _raise(RuntimeError("disk")))
    reply = restore_workspace(bridge, snapshot)
    assert _row(reply, "undo")["status"] == "damaged"
    assert reply["result"] == "failed" and reply["ok"] is False
    assert "session_settings" in reply["restored"]


# ---- step 6 (C1, A5, C2, C3): the recovery backup is real or the restore refuses

def _logs(bridge, monkeypatch) -> list:
    lines: list = []
    monkeypatch.setattr(bridge, "_log", lambda message, level="info": lines.append((level, message)))
    return lines


def test_backup_copy_failure_refuses_before_any_change(bridge, snapshot, monkeypatch):
    """P7: a locked live file was recorded as `absent` and the restore said success."""
    from app.services.workspace import recover
    bridge.state.prompt["user_prompt"] = "live prompt"
    monkeypatch.setattr(recover.shutil, "copy2", _raise(PermissionError(13, "locked")))
    reply = restore_workspace(bridge, snapshot)
    assert reply["ok"] is False and "recovery backup" in reply["error"]
    assert "nothing was changed" in reply["error"]
    assert bridge.state.prompt["user_prompt"] == "live prompt"


def test_backup_folder_failure_refuses(bridge, snapshot, monkeypatch):
    """A5: mkdir / recovery.json OSError escaped the restore."""
    from app.services.workspace import recover
    monkeypatch.setattr(recover, "_recovery_dir", _raise(PermissionError(13, "read-only config")))
    reply = restore_workspace(bridge, snapshot)
    assert reply["ok"] is False and "recovery backup" in reply["error"]


def test_same_second_restores_keep_separate_backups(bridge, snapshot, monkeypatch):
    """P8: the second backup overwrote the first — the only pre-restore copy."""
    from app.services.workspace import recover
    monkeypatch.setattr(recover.time, "strftime", lambda fmt, *a: "20260928-120000")
    first = restore_workspace(bridge, snapshot)["backup"]
    second = restore_workspace(bridge, snapshot)["backup"]
    assert first != second and Path(first).is_dir() and Path(second).is_dir()
    assert sorted([first, second]) == [first, second]      # prune order stays chronological


def test_prune_logs_what_it_removed(bridge, snapshot, monkeypatch):
    """C3: prune was documented as logged; nothing logged."""
    from app.services.workspace import recover
    base = Path(bridge.config.dir) / recover.RECOVERY_DIR
    for i in range(recover.RECOVERY_KEEP):
        (base / f"20200101-0000{i:02d}").mkdir(parents=True)
    lines = _logs(bridge, monkeypatch)
    restore_workspace(bridge, snapshot)
    assert any("recovery" in m and "pruned 1" in m for _lvl, m in lines)


# ---- step 7 (R1): the preview applies the restore's safe-path rule ------------

def test_preview_never_reads_outside_the_snapshot(snapshot, tmp_path):
    """P9: `../../x` was stat-ed and parsed; restore refuses the same path."""
    from app.services.workspace.restore import preview_restore
    outside = tmp_path / "outside_secret.json"          # snapshot = tmp/workspaces/<snap>
    outside.write_text(json.dumps({"folder": {"root_path": "/nonexistent/secret"}}))
    manifest = json.loads((snapshot / "manifest.json").read_text())
    manifest["domains"]["arena_state"]["path"] = "../../" + outside.name
    (snapshot / "manifest.json").write_text(json.dumps(manifest))
    preview = preview_restore(snapshot)
    row = next(d for d in preview["domains"] if d["domain_id"] == "arena_state")
    assert row["status"] == "unsafe_path"
    assert preview["path_remap_needed"] == []


def test_preview_of_a_non_object_queue_file_does_not_crash(snapshot):
    from app.services.workspace.restore import preview_restore
    (snapshot / "state" / "app_state.json").write_text("[]")
    preview = preview_restore(snapshot)
    assert preview["ok"] and preview["path_remap_needed"] == []
