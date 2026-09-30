"""Workspace characterization — audit #3 (docs/archive/2026-09-29-workspace-refactor-3/audit.md).

Every test here pins behaviour that existed BEFORE the audit-#3 refactor and
that no test covered. They are the equivalence gate for the structural steps
(steps 1-8) and the "before" half of the behaviour steps (9-13: each of those
steps first flips the matching assertion here to the desired behaviour, so the
flip is a visible, revertable one-line diff).

Real Bridge, real snapshot folders, temporary dirs only.  Nothing here mocks
the code under test (RULE 8).
"""

import json
from pathlib import Path

import pytest

from app.persistence.config_manager import DEFAULT_SESSION, ConfigManager
from app.persistence.workspace.errors import WorkspaceError
from app.services.workspace import apply as ws_apply
from app.services.workspace import meta as ws_meta
from app.services.workspace import restore as ws_restore
from app.services.workspace import save as ws_save
from app.services.workspace.provider import CaptureResult
from app.services.workspace.registry import get
from app.services.workspace.save import SaveRequest
from app.ui.bridge import Bridge
from app.ui.panels.workspace import _do_restore
from tests.test_workspace_restore import _restamp

pytestmark = pytest.mark.unit


@pytest.fixture()
def bridge(tmp_path):
    return Bridge(config_manager=ConfigManager(config_dir=str(tmp_path)),
                  state_path=tmp_path / "app_state.json")


def _snapshot(bridge, name="ws", **kw):
    reply = ws_save.save_workspace(bridge, SaveRequest(name=name, **kw))
    assert reply["ok"], reply
    return Path(reply["path"])


def _fails(provider, cause="boom"):
    return lambda bridge: CaptureResult(ok=False, notes=[cause])


def _preview_row(preview, domain_id):
    return next(d for d in preview["domains"] if d["domain_id"] == domain_id)


def _utc_stamp():
    import time
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())


# ---- H1: two saves with one name inside the same second ---------------------

def test_two_saves_in_one_second_both_publish(bridge, monkeypatch):
    """The snapshot folder is second-resolution, so two saves with one name in
    the same second used to collide and the second was refused with
    'publish failed: target already exists' — a legitimate action reported as a
    failure. `recover._recovery_dir` already disambiguates ITS folder
    (`-02`, `-03`); the snapshot folder now uses the same rule, so both saves
    land in their own folder and stay chronologically ordered."""
    import time
    frozen = time.struct_time((2026, 1, 1, 0, 0, 0, 0, 1, 0))
    monkeypatch.setattr("app.services.workspace.save.time.gmtime", lambda *_a, **_k: frozen)
    first = ws_save.save_workspace(bridge, SaveRequest(name="dup"))
    second = ws_save.save_workspace(bridge, SaveRequest(name="dup"))
    assert first["ok"] and second["ok"]
    assert first["result"] == second["result"] == "success"
    assert first["path"] != second["path"]
    assert Path(second["path"]).name == "dup_20260101-000000-02"
    assert sorted([first["path"], second["path"]]) == [first["path"], second["path"]]
    for reply in (first, second):
        manifest = json.loads((Path(reply["path"]) / "manifest.json").read_text())
        assert manifest["name"] == "dup"


def test_a_second_save_in_a_different_second_is_unaffected(bridge):
    """The positive control: normal saves still get the plain second-resolution
    folder name — the disambiguation only fires on a real collision.

    The clock is read on both sides of the save rather than after it: on a
    loaded machine the second can tick inside `save_workspace`, and the
    property under test is "plain stamp, no `-02` suffix", not "the same
    second as the assertion".
    """
    before = _utc_stamp()
    first = ws_save.save_workspace(bridge, SaveRequest(name="solo"))
    after = _utc_stamp()
    name = Path(first["path"]).name
    assert name in (f"solo_{before}", f"solo_{after}")
    assert not name.endswith(("-02", "-03"))


# ---- H2: a refused save is silent -----------------------------------------

def test_a_refused_save_logs_one_error_line(bridge, monkeypatch):
    """RULE 2: every step is reported. A refused save used to return an error
    dict and log NOTHING, so the failure was invisible in the Activity Log and
    `logs/arena.log` — the user saw it only in the Workspace window, which is
    not on screen when the save came from a preset, an undo or an unattended
    action."""
    lines = []
    monkeypatch.setattr(ws_save, "log_message", lambda b, m, lv="info": lines.append((m, lv)))
    monkeypatch.setattr(get("arena_state"), "validate", lambda doc: "boom")
    reply = ws_save.save_workspace(bridge, SaveRequest(name="bad"))
    assert reply["ok"] is False and reply["result"] == "failed"
    assert len(lines) == 1
    message, level = lines[0]
    assert level == "error" and "arena_state" in message and "Workspace" in message


def test_a_publish_failure_logs_one_error_line(bridge, monkeypatch):
    """The other save failure path (`_publish_failed`) was silent too."""
    lines = []
    monkeypatch.setattr(ws_save, "log_message", lambda b, m, lv="info": lines.append((m, lv)))
    monkeypatch.setattr("app.persistence.workspace.fsio.publish",
                        lambda temp, target: (_ for _ in ()).throw(OSError("disk full")))
    reply = ws_save.save_workspace(bridge, SaveRequest(name="nofree"))
    assert reply["ok"] is False and "publish failed" in reply["error"]
    assert len(lines) == 1
    assert lines[0][1] == "error" and "disk full" in lines[0][0]


def test_a_save_with_no_domains_selected_logs_one_error_line(bridge, monkeypatch):
    """The third refusal path — 'no domains selected' — is silent too."""
    lines = []
    monkeypatch.setattr(ws_save, "log_message", lambda b, m, lv="info": lines.append((m, lv)))
    reply = ws_save.save_workspace(bridge, SaveRequest(name="none", selected=["nope"]))
    assert reply == {"ok": False, "error": "no domains selected"}
    assert len(lines) == 1 and lines[0][1] == "error"


def test_a_successful_save_logs_exactly_one_line(bridge, monkeypatch):
    """The positive control for the two tests above (a counting test that has a
    positive case — RULE 8)."""
    lines = []
    monkeypatch.setattr(ws_save, "log_message", lambda b, m, lv="info": lines.append((m, lv)))
    assert _snapshot(bridge, name="ok") is not None
    assert len(lines) == 1 and lines[0][1] == "success" and "Workspace saved" in lines[0][0]


# ---- H3: the on-disk restore report is missing the panel's notes ------------

def test_the_on_disk_restore_report_describes_the_whole_run(bridge):
    """`apply._finish` wrote `reports/restore-report.json` BEFORE
    `panels/workspace._do_restore` appended the clamp + RULE 24 refresh notes,
    so the file described 3 provider notes while the UI reply described 8 —
    and a refresh push that FAILED was never persisted at all. The panel now
    hands its notes to the restore service, which writes one complete report."""
    root = _snapshot(bridge, name="report")
    reply = _do_restore(bridge, str(root), {})
    on_disk = json.loads((root / "reports/restore-report.json").read_text())
    assert reply["restored"] and reply["reconciled"]
    assert on_disk["reconciled"] == reply["reconciled"]
    assert "live state re-pushed (queue, urls, settings inputs)" in on_disk["reconciled"]


def test_a_failed_live_push_reaches_the_on_disk_report(bridge, monkeypatch):
    """The note a failing push produces must survive on disk — a silent live
    refresh is exactly the 2026-09-25 'restore does nothing' class of bug, and
    the report is the only durable record of it."""
    root = _snapshot(bridge, name="pushfail")
    monkeypatch.setattr("app.ui.panels.workspace._emit_refresh",
                        lambda b, emit, note, notes: notes.append(f"{note} failed: OSError"))
    _do_restore(bridge, str(root), {})
    on_disk = json.loads((root / "reports/restore-report.json").read_text())
    assert any("failed: OSError" in n for n in on_disk["reconciled"]), on_disk["reconciled"]


# ---- H4: `required` does not gate anything ---------------------------------

def test_a_non_required_capture_failure_saves_a_partial_snapshot(bridge, monkeypatch):
    """`StateProvider.required` says "save aborts (unless allow_partial) when a
    REQUIRED domain fails", and `reports.save_report` publishes a
    `failed_required` list — but the abort condition was `if failed`, so the
    flag bought nothing: a transient `captcha_stats.json` read error blocked a
    workspace checkpoint entirely. A non-required domain now degrades the save
    to `partial`, loudly."""
    assert get("captcha_stats").required is False
    monkeypatch.setattr(get("captcha_stats"), "capture", _fails("nope"))
    reply = ws_save.save_workspace(bridge, SaveRequest(name="partial"))
    assert reply["ok"] is True and reply["result"] == "partial"
    assert [e["domain_id"] for e in reply["errors"]] == ["captcha_stats"]
    assert reply["failed_required"] == []          # nothing required failed
    root = Path(reply["path"])
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["snapshot_kind"] == "partial"
    assert manifest["domains"]["captcha_stats"]["capture"]["ok"] is False
    assert manifest["domains"]["arena_state"]["capture"]["ok"] is True


def test_a_required_capture_failure_still_refuses_the_save(bridge, monkeypatch):
    """The positive control: a REQUIRED domain failing refuses the save unless
    the user explicitly allows a partial snapshot."""
    assert get("arena_state").required is True
    monkeypatch.setattr(get("arena_state"), "validate", lambda doc: "boom")
    refused = ws_save.save_workspace(bridge, SaveRequest(name="req"))
    assert refused["ok"] is False
    assert "arena_state" in refused["error"] and refused["result"] == "failed"
    allowed = ws_save.save_workspace(bridge, SaveRequest(name="req2", allow_partial=True))
    assert allowed["ok"] and allowed["result"] == "partial"
    assert [e["domain_id"] for e in allowed["failed_required"]] == ["arena_state"]


def test_a_required_failure_names_the_real_cause_in_the_log(bridge, monkeypatch):
    """The refusal line must say WHY, not just that it was refused (RULE 2)."""
    lines = []
    monkeypatch.setattr(ws_save, "log_message", lambda b, m, lv="info": lines.append(m))
    monkeypatch.setattr(get("arena_state"), "validate", lambda doc: "boom")
    ws_save.save_workspace(bridge, SaveRequest(name="req"))
    assert len(lines) == 1 and "arena_state" in lines[0] and "boom" in lines[0]


# ---- H5: preview promises a restore that will be refused -------------------

def test_preview_marks_a_semantically_invalid_domain(bridge):
    """The per-domain checklist is the screen the user trusts most, and it
    promised a restore that the semantic gate then refused. The preview now
    runs the SAME gate the restore runs (`gates.load_files` + `provider.validate`)
    and says so in the row — status `invalid`, with the cause."""
    root = _snapshot(bridge, name="semantic")
    rel = "state/captcha_stats.json"
    (root / rel).write_text('{"per_site": "not-an-object"}')
    _restamp(root, rel)
    row = _preview_row(ws_restore.preview_restore(root), "captcha_stats")
    assert row["status"] == "invalid"
    assert "per_site" in row["note"]
    # the restore that follows really does skip it, at the same stage
    reply = ws_apply.restore_workspace(bridge, root)
    skipped = {r["domain_id"]: r for r in reply["skipped"]}
    assert skipped["captcha_stats"]["stage"] == "semantic"


def test_preview_marks_an_unsupported_schema(bridge):
    """`entry.schema_version` was shown in the row but never compared against
    `provider.supported_migrations`, so 'saved by another build' also ticked
    as `ok`."""
    root = _snapshot(bridge, name="schema")
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["domains"]["undo"]["schema_version"] = "99"
    (root / "manifest.json").write_text(json.dumps(manifest))
    row = _preview_row(ws_restore.preview_restore(root), "undo")
    assert row["status"] == "unsupported_schema" and "99" in row["note"]
    reply = ws_apply.restore_workspace(bridge, root)
    assert {r["domain_id"]: r for r in reply["skipped"]}["undo"]["stage"] == "schema"


def test_preview_marks_an_unreadable_file_before_the_size_gate(bridge):
    """A file the restore cannot parse is a `parse` row, so the preview says
    so instead of only reporting a byte count that matches."""
    root = _snapshot(bridge, name="broken")
    rel = "state/undo.json"
    (root / rel).write_text("{not json")
    _restamp(root, rel)
    row = _preview_row(ws_restore.preview_restore(root), "undo")
    assert row["status"] == "parse" and "JSON" in row["note"]


def test_a_healthy_snapshot_previews_all_ok(bridge):
    """The positive control: every file-backed domain ticks `ok`."""
    preview = ws_restore.preview_restore(_snapshot(bridge, name="healthy"))
    status = {d["domain_id"]: d["status"] for d in preview["domains"]}
    assert status["arena_state"] == "ok" and status["captcha_stats"] == "ok"
    assert status["captcha_keys"] == "excluded" and status["captcha_recordings"] == "excluded"


# ---- M9: the captured session key set is implicit --------------------------

def test_the_captured_session_key_set_is_exactly_these_24_keys():
    """`providers.session.settings_keys()` is `DEFAULT_SESSION` minus the grid
    trio, computed at call time.  Pinning the set turns "someone added a key to
    DEFAULT_SESSION" from a silent snapshot-content change into a failing test."""
    from app.services.workspace.providers.session import GRID_KEYS, settings_keys
    assert len(DEFAULT_SESSION) == 27
    assert settings_keys() == tuple(k for k in DEFAULT_SESSION if k not in GRID_KEYS)
    assert "grid_layout" not in settings_keys()
    assert "window_states" not in settings_keys() and "window_geometry" not in settings_keys()
    assert set(settings_keys()) <= set(DEFAULT_SESSION)


# ---- M8: only the two MUTATING slots are crash-guarded --------------------

def test_only_the_mutating_slots_answer_when_they_crash(tmp_path, monkeypatch):
    """BEFORE step 5: `_answer` wrapped `save_workspace` and `restore_workspace`
    only. A crash inside `get_workspace_state`, `preview_workspace` or
    `browse_workspace_folder` escaped into QWebChannel, which answers '' —
    `wsParse` then reports 'bad reply', a misleading message for an internal
    crash. Every JSON slot answers `ok:false` now."""
    import app.ui.panels.workspace as panel

    def boom(*_a, **_k):
        raise RuntimeError("kaboom")

    crashers = {"_state_payload": (boom, "get_workspace_state", (), "state"),
                "ws_restore": (type("R", (), {"preview_restore": staticmethod(boom)})(),
                               "preview_workspace", ("/nope",), "preview"),
                "QFileDialog": (boom, "browse_workspace_folder", ("restore-source",), "browse")}
    for name, (replacement, slot, args, action) in crashers.items():
        monkeypatch.setattr(panel, name, replacement)
        reply = json.loads(getattr(WorkspacePanel(), slot)(*args))
        assert reply["ok"] is False and f"workspace {action} crashed:" in reply["error"], reply
        monkeypatch.undo()


class WorkspacePanel:
    """The slot surface, unbound — every slot must survive a crash."""
    from app.ui.panels.workspace import WorkspaceMixin as _Mixin

    get_workspace_state = _Mixin.get_workspace_state
    save_workspace = _Mixin.save_workspace
    preview_workspace = _Mixin.preview_workspace
    restore_workspace = _Mixin.restore_workspace
    browse_workspace_folder = _Mixin.browse_workspace_folder

    def _log(self, *_a, **_k):
        pass


# ---- M7: the live-refresh table names domain ids as raw strings ------------

def test_the_refresh_table_names_only_registered_domains():
    """BEFORE step 5: `_REFRESH_TABLE` listed five domain ids as literals, so a
    renamed domain silently stopped getting its live push (RULE 24) and no
    test failed. The ids are now asserted against the one registry."""
    from app.services.workspace.registry import RESTORE_ORDER
    from app.ui.panels.workspace import _REFRESH_TABLE
    ids = [domain_id for domain_id, _emit, _note in _REFRESH_TABLE]
    assert ids and set(ids) <= set(RESTORE_ORDER), sorted(set(ids) - set(RESTORE_ORDER))
    assert len(ids) == len(set(ids))          # one push per restored domain


# ---- M6: the restore boundary is locked like the save boundary -------------

def test_every_restored_domain_runs_its_transaction_under_the_state_lock(bridge, monkeypatch):
    """`save.capture_all` runs every capture under `live.feed.state_lock` —
    'one coherent capture pass at the snapshot boundary'. The restore's
    per-domain transaction (pre-apply capture -> apply -> rollback) used to
    take no lock, so a background writer could change live state between an
    undo point and its write, and the rollback would revert that change too.
    The lock is an RLock, so the nested capture/apply/rollback cannot deadlock."""
    used = []
    root = _snapshot(bridge, name="lock")       # saved BEFORE the spy is armed
    monkeypatch.setattr(ws_apply, "live_run_error", lambda b: None)
    _install_lock_spy(monkeypatch, used)
    reply = ws_apply.restore_workspace(bridge, root)
    assert reply["ok"] and reply["restored"]
    # once per domain that reached the transaction, never nested
    assert len(used) == len(reply["restored"])


def test_a_save_does_take_the_state_lock(bridge, monkeypatch):
    """The positive control: one locked pass for the whole capture."""
    used = []
    _install_lock_spy(monkeypatch, used)
    _snapshot(bridge, name="locked")
    assert len(used) == 1


def test_a_refused_restore_takes_no_lock(bridge, monkeypatch):
    """A refusal must not grab the lock — nothing was touched, and blocking the
    queue writer would be a stall (RULE 9)."""
    used = []
    _install_lock_spy(monkeypatch, used)
    assert ws_apply.restore_workspace(bridge, str(Path("/nope/snapshot")))["ok"] is False
    assert used == []


def _install_lock_spy(monkeypatch, used):
    import app.services.live.feed as feed
    inner = feed.state_lock

    class Spy:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __enter__(self):
            used.append("enter")
            return self.wrapped.__enter__()

        def __exit__(self, *exc):
            return self.wrapped.__exit__(*exc)

    monkeypatch.setattr(feed, "state_lock", lambda b: Spy(inner(b)))


# ---- M5: one save, one `git` call (measured, not asserted today) -----------

def test_app_meta_never_raises_and_answers_unknown_without_git(monkeypatch, tmp_path):
    """`meta._build_sha` is the only subprocess in the package; a missing/broken
    git must degrade to the literal "unknown", never raise."""
    import subprocess

    def boom(*_a, **_k):
        raise OSError("git not found")

    monkeypatch.setattr(subprocess, "run", boom)
    bridge = Bridge(config_manager=ConfigManager(config_dir=str(tmp_path)),
                    state_path=tmp_path / "app_state.json")
    assert ws_meta.app_meta(bridge)["build"] == "unknown"


def test_one_save_asks_git_for_the_build_sha_once(bridge, monkeypatch):
    """`meta.app_meta` shells out to `git rev-parse`; the whole snapshot reads it
    ONCE and both consumers (the environment file and the manifest) share that
    snapshot of it (audit #3 M5)."""
    import subprocess
    calls = []
    real = subprocess.run

    def spy(*args, **kwargs):
        calls.append(list(args[0]) if args else kwargs.get("args"))
        return real(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy)
    _snapshot(bridge, name="git")
    assert calls == [["git", "rev-parse", "--short", "HEAD"]]


def test_the_app_environment_file_keeps_its_exact_key_set(bridge):
    """The identity bundle must not widen the published metadata format."""
    env = json.loads((_snapshot(bridge, name="keys") /
                      "metadata/app-environment.json").read_text())
    assert set(env) == {"version", "build", "platform", "python", "grid_version",
                        "workspace_format", "format", "inclusion_policy"}


# ---- M2: `restore_advice` is read through `getattr`, never declared ---------

def test_restore_advice_is_declared_on_the_provider_contract():
    """`StateProvider` declares the slot `apply._policy_row` reads, so a typo
    in a policy provider's class attribute is a contract break rather than a
    silently dropped user instruction.  `policies.RESTORE_ADVICE` is gone: it
    was a dead dict whose comment claimed `apply._policy_row` consumed it."""
    from app.services.workspace.provider import StateProvider
    from app.services.workspace.providers import policies
    assert StateProvider.restore_advice == ""
    assert get("captcha_keys").restore_advice == policies.KEYS_REAPPLY
    assert not hasattr(policies, "RESTORE_ADVICE")


def test_a_policy_row_without_advice_still_explains_itself():
    """The contract default is '' → the row still names the cause, and carries
    no `recommended_action` key at all (never a blank instruction)."""
    from app.services.workspace.provider import StateProvider
    from app.services.workspace.providers.policies import RecordingsProvider
    row = ws_apply._policy_row(RecordingsProvider(), {"capture": {"excluded_reason": "x"}})
    assert row["status"] == "skipped" and row["policy"] is True and row["cause"] == "x"
    assert row["recommended_action"] == RecordingsProvider.restore_advice
    bare = ws_apply._policy_row(StateProvider(), {"capture": {}})
    assert bare["cause"] == "policy-excluded domain" and "recommended_action" not in bare


# ---- M3: the `published=False` report branch is unreachable ----------------

def test_the_save_report_is_only_ever_built_for_a_published_snapshot(bridge, monkeypatch):
    """A save report exists only after the manifest made the folder a snapshot
    (the commit marker); a publish failure returns before any report is built,
    so the report carries no `published` flag and has no 'failed' outcome."""
    from app.services.workspace.reports import SAVE_RESULT_FAILED, save_report
    root = _snapshot(bridge, name="shape")
    report = json.loads((root / "reports/save-report.json").read_text())
    assert "published" not in report and report["result"] == "success"
    # a partial save is still a published snapshot: partial, never failed
    monkeypatch.setattr(get("captcha_stats"), "capture", _fails("nope"))
    partial = ws_save.save_workspace(bridge, SaveRequest(name="shape2", allow_partial=True))
    assert partial["ok"] and partial["result"] == "partial"
    assert save_report(timing={"snapshot_id": "x"}, domains=[], errors=[])["result"] == "success"
    assert SAVE_RESULT_FAILED == "failed"   # still the vocabulary, still used by _abort_result
