"""Reply truth — what the user is told equals what is on disk (audit #3, R0).

These are **characterization** tests: they pin today's service-level contract
before audit #3 moves the safe-path rule (R1), the index read rule (R4) and the
save/restore logging (R3/N4). What they must prove:

1. a save's reply carries every key the durable `save-report.json` holds, with
   the same values (audit #2 S1's rule, still true);
2. a *service-level* restore reply equals the durable `restore-report.json`
   byte-for-byte in values — the panel may add UI-only notes in the reply (R6
   fixes that), but the service layer never diverges;
3. the preview and the restore file gates answer the SAME verdict for the same
   manifest path — one security rule, two entry points (D1), which R1 collapses
   into `integrity.resolve_inside`.
"""

import json
from pathlib import Path

import pytest

from app.persistence.config_manager import ConfigManager
from app.services.workspace import apply as ws_apply
from app.services.workspace import gates as ws_gates
from app.services.workspace import save as ws_save
from app.services.workspace import restore as ws_restore
from app.services.workspace.save import SaveRequest
from app.ui.bridge import Bridge

pytestmark = pytest.mark.unit

REPORT_KEYS = {"workspace", "restored", "skipped", "migrated", "reconciled",
               "backup", "result"}

# Paths a hand-edited or hostile manifest can carry; the first is legal.
# `""` is deliberately absent: both sides short-circuit an entry without a path
# into the policy branch (pinned by test_policy_domain_selected_answers_with_its_action
# and test_all_registered_domains_are_in_the_manifest), so the gates are never
# asked about it.
PATH_TABLE = [
    "state/undo.json",
    "state/./undo.json",
    "state/nested/../undo.json",
    "../outside.json",
    "/etc/passwd",
    "C:/windows/system32/undo.json",
    "state\\undo.json",
]


@pytest.fixture()
def bridge(tmp_path):
    return Bridge(config_manager=ConfigManager(config_dir=str(tmp_path)),
                  state_path=tmp_path / "app_state.json")


@pytest.fixture()
def snapshot(bridge):
    bridge.state.prompt["user_prompt"] = "reply truth"
    reply = ws_save.save_workspace(bridge, SaveRequest(name="truth"))
    assert reply["ok"]
    return Path(reply["path"])


def _report_file(root: Path, name: str) -> dict:
    return json.loads((root / "reports" / name).read_text(encoding="utf-8"))


def test_save_reply_carries_what_the_save_report_on_disk_says(bridge):
    reply = ws_save.save_workspace(bridge, SaveRequest(name="keys"))
    disk = _report_file(Path(reply["path"]), "save-report.json")
    assert set(reply) >= set(disk), "reply must not hide a report key"
    assert {key: reply[key] for key in disk} == disk


def test_service_restore_reply_equals_the_restore_report_on_disk(bridge, snapshot):
    reply = ws_apply.restore_workspace(bridge, snapshot)
    disk = _report_file(snapshot, "restore-report.json")
    assert set(disk) == REPORT_KEYS, "the durable report shape is frozen"
    for key in REPORT_KEYS:
        assert disk[key] == reply[key], f"{key} differs between reply and disk"


def _rewrite_domain_path(root: Path, rel: str) -> dict:
    """Point arena_state's manifest entry at `rel` (hand-edited snapshot)."""
    path = root / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["domains"]["arena_state"]["path"] = rel
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


@pytest.mark.parametrize("rel", PATH_TABLE)
def test_preview_and_file_gates_agree_on_the_safe_path_rule(snapshot, rel):
    """D1: the preview's path check and the restore gate's path check are one rule."""
    root = Path(snapshot)
    manifest = _rewrite_domain_path(root, rel)
    entry = manifest["domains"]["arena_state"]

    preview_row = next(row for row in ws_restore.preview_restore(root)["domains"]
                       if row["domain_id"] == "arena_state")
    loaded = ws_gates.load_one(root, entry, rel)

    preview_refused = preview_row["status"] == "unsafe_path"
    gate_refused = getattr(loaded, "stage", "") == "unsafe_path"
    assert preview_refused == gate_refused, (
        f"preview says {preview_row['status']!r}, gates say "
        f"{getattr(loaded, 'stage', 'ok')!r} for path {rel!r}")


def test_legal_path_in_the_table_is_really_legal(snapshot):
    """Guard for the table above: it must contain a path both sides accept."""
    root = Path(snapshot)
    manifest = _rewrite_domain_path(root, "state/undo.json")
    entry = manifest["domains"]["arena_state"]
    row = next(r for r in ws_restore.preview_restore(root)["domains"]
               if r["domain_id"] == "arena_state")
    assert row["status"] != "unsafe_path"
    assert not getattr(ws_gates.load_one(root, entry, "state/undo.json"), "stage",
                       "").endswith("unsafe_path")


# ── audit #3 R6/N3: the panel's live-refresh notes are NOT durable report data ─

def test_panel_restore_keeps_ui_notes_out_of_the_durable_report(bridge, snapshot):
    """N3: `_do_restore` appended its live-refresh notes to `reconciled`, so the
    reply carried more notes (8) than restore-report.json on disk (3)."""
    reply = json.loads(bridge.restore_workspace(str(snapshot), "{}"))
    disk = _report_file(Path(snapshot), "restore-report.json")
    assert reply["reconciled"] == disk["reconciled"]
    assert reply["refresh"], "UI-only notes must still be shown"
    assert not any("re-pushed" in note for note in disk["reconciled"])


def test_a_restore_that_restored_nothing_has_no_refresh_notes(bridge, tmp_path):
    reply = json.loads(bridge.restore_workspace(str(tmp_path), "{}"))
    assert reply["ok"] is False and reply.get("refresh") is None
