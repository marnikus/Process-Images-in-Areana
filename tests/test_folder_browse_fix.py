"""BUG 03.4 — Browse opens a dialog that stays in front (headless branches).

Acceptance (docs/03_bugfix_plan.md):
* a real parent window owns the modal (never parent=None);
* ordered strategy chain: native -> Qt non-native -> explicit error;
* the failure answer always carries a human `error` (JS shows a toast,
  not a silent log line).
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ui.panels import folder_browse
from app.ui.panels.folder_browse import (
    apply_folder_choice,
    open_folder_dialog,
    resolve_start_dir,
)


class _FakeDialog:
    """Scripted QFileDialog stand-in with the option flags the real one has."""
    ShowDirsOnly = 1
    DontUseNativeDialog = 2
    existing_dir = ""
    raise_on = set()  # strategy names that throw

    @classmethod
    def getExistingDirectory(cls, parent, title, start=0, options=0):
        if "native" in cls.raise_on and not (options & cls.DontUseNativeDialog):
            raise RuntimeError("shell handler broken")
        if "qt" in cls.raise_on and (options & cls.DontUseNativeDialog):
            raise RuntimeError("qt dialog failed")
        return cls.existing_dir


@pytest.mark.unit
class TestResolveStartDir:
    def test_typed_value_wins(self, tmp_path):
        saved = tmp_path / "saved"
        typed = tmp_path / "typed"
        saved.mkdir()
        typed.mkdir()
        assert resolve_start_dir({"root_path": str(saved)}, str(typed)) == str(typed)

    def test_saved_root_when_typed_missing(self, tmp_path):
        saved = tmp_path / "saved"
        saved.mkdir()
        assert resolve_start_dir({"root_path": str(saved)}, str(tmp_path / "nope")) \
            == str(saved)

    def test_home_fallback(self):
        assert resolve_start_dir(None, "") == str(Path.home())


@pytest.mark.unit
class TestOpenFolderDialog:
    def test_qt_unavailable_carries_human_error(self, monkeypatch):
        monkeypatch.setattr(folder_browse, "QFileDialog", None)
        res = open_folder_dialog("/tmp")
        assert res["ok"] is False and "cancelled" not in res
        assert "Qt file dialog unavailable" in res["error"]

    def test_native_ok(self, monkeypatch, tmp_path):
        _FakeDialog.raise_on = set()
        _FakeDialog.existing_dir = str(tmp_path)
        monkeypatch.setattr(folder_browse, "QFileDialog", _FakeDialog)
        res = open_folder_dialog(str(tmp_path))
        assert res == {"ok": True, "path": str(tmp_path), "via": "native"}

    def test_cancelled_keeps_cancelled_flag(self, monkeypatch, tmp_path):
        _FakeDialog.raise_on = set()
        _FakeDialog.existing_dir = ""
        monkeypatch.setattr(folder_browse, "QFileDialog", _FakeDialog)
        res = open_folder_dialog(str(tmp_path))
        assert res == {"ok": False, "cancelled": True, "via": "native"}

    def test_native_failure_falls_back_to_qt(self, monkeypatch, tmp_path):
        _FakeDialog.raise_on = {"native"}
        _FakeDialog.existing_dir = str(tmp_path)
        monkeypatch.setattr(folder_browse, "QFileDialog", _FakeDialog)
        res = open_folder_dialog(str(tmp_path))
        assert res["ok"] is True and res["via"] == "qt"

    def test_all_strategies_fail_reports_error(self, monkeypatch, tmp_path):
        _FakeDialog.raise_on = {"native", "qt"}
        monkeypatch.setattr(folder_browse, "QFileDialog", _FakeDialog)
        res = open_folder_dialog(str(tmp_path))
        assert res["ok"] is False and res["error"]
        assert "qt" in res["error"]  # last strategy's failure is reported

    def test_dialog_receives_real_parent_not_none(self, monkeypatch, tmp_path):
        seen = {}

        class _ParentProbe(_FakeDialog):
            @classmethod
            def getExistingDirectory(cls, parent, title, start=0, options=0):
                seen["parent"] = parent
                seen["title"] = title
                return cls.existing_dir

        _ParentProbe.existing_dir = str(tmp_path)
        monkeypatch.setattr(folder_browse, "QFileDialog", _ParentProbe)
        monkeypatch.setattr(folder_browse, "_top_level_parent", lambda: "MAINWIN")
        res = open_folder_dialog(str(tmp_path))
        assert res["ok"] is True
        assert seen["parent"] == "MAINWIN"  # never None (BUG 03.4 root cause)
        assert seen["title"] == "Select image folder"


@pytest.mark.unit
class TestApplyFolderChoice:
    def test_missing_folder_rejected(self):
        b = SimpleNamespace(state=SimpleNamespace(folder={}),
                            _save_arena=lambda: None)
        res = apply_folder_choice(b, "/no/such/folder/xyz")
        assert res["ok"] is False and "does not exist" in res["error"]

    def test_ok_persists_and_saves(self, tmp_path):
        b = SimpleNamespace(state=SimpleNamespace(folder={}),
                            _save_arena=lambda: None)
        res = apply_folder_choice(b, str(tmp_path))
        assert res == {"ok": True, "path": str(tmp_path)}
        assert b.state.folder["root_path"] == str(tmp_path)

    def test_mixin_pick_folder_json_contract(self, tmp_path, monkeypatch):
        _FakeDialog.raise_on = set()
        _FakeDialog.existing_dir = str(tmp_path)
        monkeypatch.setattr(folder_browse, "QFileDialog", _FakeDialog)
        calls = []
        bridge = SimpleNamespace(
            state=SimpleNamespace(folder={"root_path": ""}),
            _save_arena=lambda: calls.append("save"),
            _log=lambda *a, **k: None)
        out = json.loads(folder_browse.FolderBrowseMixin.pick_folder(bridge, ""))
        assert out["ok"] is True and out["via"] == "native"
        assert bridge.state.folder["root_path"] == str(tmp_path)
        assert calls == ["save"]

    def test_mixin_set_folder_path_json_contract(self, tmp_path, monkeypatch):
        bridge = SimpleNamespace(
            state=SimpleNamespace(folder={}),
            _save_arena=lambda: None,
            _log=lambda *a, **k: None)
        out = json.loads(folder_browse.FolderBrowseMixin.set_folder_path(bridge, str(tmp_path)))
        assert out["ok"] is True and out["path"] == str(tmp_path)
