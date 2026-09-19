"""File-dialog branch tests (R12/F7): fake QFileDialog, Qt absent in CI."""

import json
from types import SimpleNamespace

from app.core.layout_service import default_grid_tree
from app.ui.panels import app_settings, blocks_stack, folder_browse, layout_state, queue_scan


class FakeDialog:
    """QFileDialog stand-in with scripted answers."""
    existing_dir = ""
    open_file = ("", "")

    @staticmethod
    def getExistingDirectory(*a):
        return FakeDialog.existing_dir

    @staticmethod
    def getOpenFileName(*a):
        return FakeDialog.open_file


class Rec:
    def __init__(self):
        self.calls = []

    def __call__(self, *a):
        self.calls.append(a)


def test_layout_export_dialog_ok_and_cancel(tmp_path, monkeypatch):
    monkeypatch.setattr(layout_state, "QFileDialog", FakeDialog)
    FakeDialog.existing_dir = str(tmp_path)
    saved = {}

    def load_preset(name):
        return {"name": name, "grid": {"tree": {}}} if name == "D" else None
    bridge = SimpleNamespace(
        config=SimpleNamespace(window_presets=SimpleNamespace(load_preset=load_preset)),
        _exported_paths=saved, _log=lambda *a: None)
    res = json.loads(layout_state.export_preset_file(bridge, "D"))
    assert res["ok"] is True and (tmp_path / "D.json").exists()
    assert saved["D"].endswith("D.json")
    assert json.loads(layout_state.export_preset_file(bridge, "Nope"))["error"] == "not found"
    FakeDialog.existing_dir = ""
    res = json.loads(layout_state.export_preset_file(bridge, "D"))
    assert res == {"ok": False, "cancelled": True}


def test_layout_import_dialog_ok_and_cancel(tmp_path, monkeypatch):
    monkeypatch.setattr(layout_state, "QFileDialog", FakeDialog)
    payload = json.dumps({"v": 4, "tree": default_grid_tree()})
    preset = tmp_path / "imp.json"
    preset.write_text(json.dumps({"name": "I", "grid": {"payload": payload}}))
    FakeDialog.open_file = (str(preset), "JSON (*.json)")
    saved, listed = {}, Rec()
    bridge = SimpleNamespace(
        config=SimpleNamespace(window_presets=SimpleNamespace(
            save_preset=lambda n, d: saved.update({n: d}))),
        list_window_presets=lambda: listed(), _log=lambda *a: None)
    res = json.loads(layout_state.import_preset_file(bridge))
    assert res == {"ok": True, "name": "I"}
    assert saved["I"]["name"] == "I" and listed.calls
    FakeDialog.open_file = ("", "")
    res = json.loads(layout_state.import_preset_file(bridge))
    assert res == {"ok": False, "cancelled": True}
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"grid": {"payload": "junk"}}))
    FakeDialog.open_file = (str(bad), "JSON (*.json)")
    res = json.loads(layout_state.import_preset_file(bridge))
    assert res["ok"] is False and "invalid grid" in res["error"]


def test_stack_export_dialog_ok_and_cancel(tmp_path, monkeypatch):
    monkeypatch.setattr(blocks_stack, "QFileDialog", FakeDialog)
    FakeDialog.existing_dir = str(tmp_path)
    bridge = SimpleNamespace(_log=lambda *a: None)
    res = json.loads(blocks_stack.export_stack_file(bridge, [{"a": 1}]))
    assert res["ok"] is True and res["path"].endswith(".json")
    written = next(tmp_path.glob("arena-action-blocks-*.json"))
    assert json.loads(written.read_text()) == [{"a": 1}]
    FakeDialog.existing_dir = ""
    res = json.loads(blocks_stack.export_stack_file(bridge, [{"a": 1}]))
    assert res == {"ok": False, "cancelled": True}


def test_app_settings_import_dialog_ok_and_cancel(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "QFileDialog", FakeDialog)
    preset = tmp_path / "p.json"
    preset.write_text(json.dumps({"folder": {"root_path": "/z"},
                                  "prompt": {"user_prompt": "hi"}}))
    FakeDialog.open_file = (str(preset), "JSON (*.json)")
    state = SimpleNamespace(urls=[], folder={}, prompt={},
                            recalculate_progress=Rec())
    fake = SimpleNamespace(state=state, _save_arena=Rec())
    res = json.loads(app_settings.AppSettingsMixin.import_preset(fake))
    assert res == {"ok": True}
    assert state.folder == {"root_path": "/z"}
    assert state.prompt == {"user_prompt": "hi"}
    assert state.recalculate_progress.calls and fake._save_arena.calls
    FakeDialog.open_file = ("", "")
    res = json.loads(app_settings.AppSettingsMixin.import_preset(fake))
    assert res == {"ok": False, "cancelled": True}


def test_pick_folder_dialog_ok_cancel_headless(tmp_path, monkeypatch):
    # BUG 03.4: pick_folder now delegates to FolderBrowseMixin (parented,
    # strategy-chained dialog) — the fake must patch folder_browse's dialog
    # and model the option flags the real QFileDialog exposes.
    FakeDialog.ShowDirsOnly = 1
    FakeDialog.DontUseNativeDialog = 2
    monkeypatch.setattr(folder_browse, "QFileDialog", FakeDialog)
    FakeDialog.existing_dir = str(tmp_path)
    state = SimpleNamespace(folder={"root_path": ""})
    fake = SimpleNamespace(state=state, _save_arena=Rec(),
                           _log=lambda *a, **k: None)
    res = json.loads(queue_scan.QueueScanMixin.pick_folder(fake, ""))
    assert res["ok"] is True and res["path"] == str(tmp_path) and res["via"] == "native"
    assert state.folder["root_path"] == str(tmp_path)
    assert fake._save_arena.calls
    FakeDialog.existing_dir = ""
    res = json.loads(queue_scan.QueueScanMixin.pick_folder(fake, ""))
    assert res["ok"] is False and res["cancelled"] is True
    monkeypatch.setattr(folder_browse, "QFileDialog", None)
    res = json.loads(queue_scan.QueueScanMixin.pick_folder(fake, ""))
    assert res["ok"] is False and "Qt file dialog unavailable" in res["error"]
