"""Workspace panel — the 6 Global Saving System slots on a real Bridge (W8).

Headless (qt_compat shim, no QFileDialog): the slots must answer honest
errors, save to the default base dir, preview, restore, and reveal — the
same contract the JS window drives over QWebChannel.
"""

import json

import pytest

from app.persistence.config_manager import ConfigManager
from app.services.workspace import save as ws_save
from app.services.workspace.coordinator import SaveRequest, default_base
from app.ui.bridge import Bridge

pytestmark = pytest.mark.unit


@pytest.fixture()
def bridge(tmp_path):
    return Bridge(config_manager=ConfigManager(config_dir=str(tmp_path)),
                  state_path=tmp_path / "app_state.json")


def _json(raw):
    return json.loads(raw)


def test_get_workspace_state_shape(bridge):
    payload = _json(bridge.get_workspace_state())
    assert payload["default_dir"] == str(default_base(bridge))
    assert payload["recent"] == [] and payload["last_snapshot"] == ""


def test_save_workspace_slot_saves_to_the_default_dir(bridge):
    reply = _json(bridge.save_workspace(json.dumps({"name": "from ui"})))
    assert reply["ok"] and reply["result"] == "success"
    assert reply["path"].startswith(str(default_base(bridge)))
    state = _json(bridge.get_workspace_state())
    assert state["last_snapshot"] == reply["path"] and len(state["recent"]) == 1


def test_save_workspace_slot_survives_garbage_options(bridge):
    reply = _json(bridge.save_workspace("not json"))
    assert reply["ok"] and reply["result"] == "success"  # name falls back to 'workspace'


def test_preview_and_restore_slots_round_trip(bridge):
    bridge.state.prompt["user_prompt"] = "panel prompt"
    saved = _json(bridge.save_workspace(json.dumps({"name": "rt"})))
    bridge.state.prompt["user_prompt"] = "changed"
    preview = _json(bridge.preview_workspace(saved["path"]))
    assert preview["ok"] and preview["name"] == "rt"
    reply = _json(bridge.restore_workspace(saved["path"], json.dumps({})))
    assert reply["ok"] and "arena_state" in reply["restored"]
    assert bridge.state.prompt["user_prompt"] == "panel prompt"


def test_restore_slot_reports_a_bad_folder(bridge, tmp_path):
    reply = _json(bridge.restore_workspace(str(tmp_path), "{}"))
    assert reply["ok"] is False and "not a committed workspace" in reply["error"]


def test_browse_workspace_folder_headless_error(bridge):
    reply = _json(bridge.browse_workspace_folder("restore-source"))
    assert reply["ok"] is False and "headless" in reply["error"]


def test_open_workspace_path_reports_failure(bridge):
    assert bridge.open_workspace_path("/definitely/not/there") is False


def test_geometry_clamp_helper_is_best_effort(bridge):
    bridge.config.set_state(window_geometry={"x": -5000, "y": -5000,
                                             "width": 10000, "height": 10000})
    note = __import__("app.ui.panels.workspace", fromlist=["clamp_restored_geometry"]) \
        .clamp_restored_geometry(bridge)
    geometry = bridge.config.get_state("window_geometry")
    assert geometry["width"] <= 10000  # headless: no screen service → numbers kept
    assert note in ("", "window geometry clamped to this screen")
