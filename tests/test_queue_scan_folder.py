"""Folder pick slots (2026-10-02 bugfix): every folder shape → dict, every reply JSON."""

import json
from types import SimpleNamespace

import pytest

from app.core.models import AppState
from app.ui.panels import queue_scan_folder as qsf
from app.ui.panels.queue_scan import QueueScanMixin

pytestmark = pytest.mark.unit


class Host(QueueScanMixin):
    def __init__(self, folder):
        self.state = SimpleNamespace(folder=folder, images=[], jobs=[])
        self.saved = 0
        self.pushed = []
        self._save_arena = lambda: setattr(self, "saved", self.saved + 1)
        self._log = lambda m, l="info": None
        self.undo_service = SimpleNamespace(push=lambda k, v: self.pushed.append((k, v)),
                                            history=lambda: ([], 0))
        self.undo_state_changed = SimpleNamespace(emit=lambda *a: None)
        self.history_changed = SimpleNamespace(emit=lambda *a: None)


def test_as_folder_dict_normalises_every_shape():
    assert qsf.as_folder_dict(None)["root_path"] == ""
    assert qsf.as_folder_dict("  /x/y ")["root_path"] == "/x/y"
    d = qsf.as_folder_dict({"root_path": None, "ignore_ai_suffix": False})
    assert d["root_path"] == "" and d["ignore_ai_suffix"] is False and d["supported_types"] == qsf.DEFAULT_TYPES
    assert qsf.as_folder_dict(42)["supported_types"] == qsf.DEFAULT_TYPES


@pytest.mark.parametrize("folder", [None, "/legacy/path", 7])
def test_set_folder_path_survives_non_dict_folder(tmp_path, folder):
    host = Host(folder)
    res = json.loads(host.set_folder_path(str(tmp_path)))
    assert res["ok"] is True and res["path"] == str(tmp_path)
    assert isinstance(host.state.folder, dict) and host.state.folder["root_path"] == str(tmp_path)
    assert res["folder"]["root_path"] == str(tmp_path)
    assert host.saved == 1 and host.pushed and host.pushed[0][0] == "folder"


def test_set_folder_path_rejects_missing_or_blank(tmp_path):
    host = Host({"root_path": "/before"})
    assert json.loads(host.set_folder_path(str(tmp_path / "nope"))) == {"ok": False, "error": "Folder does not exist"}
    assert json.loads(host.set_folder_path("   ")) == {"ok": False, "error": "Folder does not exist"}
    assert json.loads(host.set_folder_path(str(tmp_path / "file.txt")))["ok"] is False
    assert host.state.folder["root_path"] == "/before" and host.saved == 0


def test_pick_folder_paths(tmp_path, monkeypatch):
    host = Host(None)
    monkeypatch.setattr(qsf, "QFileDialog", None)
    assert json.loads(host.pick_folder(""))["error"] == "No file dialog"

    class Dlg:
        picked = str(tmp_path)
        seen = []

        @classmethod
        def getExistingDirectory(cls, parent, title, start):
            cls.seen.append(start)
            return cls.picked

    monkeypatch.setattr(qsf, "QFileDialog", Dlg)
    res = json.loads(host.pick_folder(str(tmp_path)))
    assert res["ok"] is True and res["path"] == str(tmp_path) and Dlg.seen == [str(tmp_path)]
    assert host.state.folder["root_path"] == str(tmp_path)
    Dlg.picked = ""
    assert json.loads(host.pick_folder("/not/a/dir")) == {"ok": False, "cancelled": True}
    assert Dlg.seen[-1] == str(tmp_path)  # falls back to the last root
    monkeypatch.setattr(qsf, "commit_folder", lambda b, p: (_ for _ in ()).throw(RuntimeError("disk")))
    Dlg.picked = str(tmp_path)
    assert json.loads(host.pick_folder(""))["error"] == "disk"


def test_resolve_pick_start_and_undo_are_fail_open(tmp_path):
    assert qsf.resolve_pick_start(None, "") == ""
    assert qsf.resolve_pick_start(str(tmp_path), "/nope") == str(tmp_path)
    assert qsf.resolve_pick_start({"root_path": "/nope"}, str(tmp_path)) == str(tmp_path)
    host = Host("/x")
    host.undo_service = None  # push raises → swallowed
    qsf.push_folder_undo(host)
    assert isinstance(host.state.folder, dict)


def test_app_state_from_dict_normalises_legacy_folder_values():
    assert AppState.from_dict({"folder": None}).folder["root_path"] == ""
    assert AppState.from_dict({"folder": "/old/style"}).folder["root_path"] == "/old/style"
    st = AppState.from_dict({"folder": {"root_path": "/d", "extra": 1}})
    assert st.folder["root_path"] == "/d" and st.folder["extra"] == 1 and st.folder["ignore_ai_suffix"] is True
    assert AppState.from_dict({}).folder["supported_types"] == [".png", ".jpg", ".jpeg", ".webp"]


def test_queue_scan_mixin_still_exposes_folder_slots():
    assert QueueScanMixin.pick_folder is qsf.FolderPickMixin.pick_folder
    assert QueueScanMixin.set_folder_path is qsf.FolderPickMixin.set_folder_path
    from app.ui.panels import queue_scan
    assert queue_scan.resolve_scan_root(None) == (None, "No folder set")
