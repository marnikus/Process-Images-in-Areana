"""Undo history panel + entries tests (A5.4): remember/apply/step/project."""

import json
from types import SimpleNamespace

from app.core.layout_service import default_payload
from app.core.undo_service import UndoService
from app.persistence.config_manager import ConfigManager
from app.ui.panels.undo_history import (
    UndoHistoryMixin,
    project_grid_result,
    project_stack_result,
)
from app.ui.services import undo_entries as entries


def fake(tmp_path):
    emitted = []

    class Sig:
        def __init__(self, name):
            self.name = name

        def emit(self, *a):
            emitted.append(self.name)

    config = ConfigManager(str(tmp_path))
    return SimpleNamespace(
        config=config,
        undo_service=UndoService(config.undo),
        state=SimpleNamespace(urls=[], folder={}, images=[],
                              prompt={"user_prompt": ""},
                              settings=SimpleNamespace(timeouts={}, output={},
                                                       highlight={}),
                              recalculate_progress=lambda: None),
        _log=lambda m, l="info": emitted.append(("log", m)),
        _save_arena=lambda: emitted.append("save"),
        grid_layout_changed=Sig("grid"), grid_layout_persisted=Sig("persisted"),
        action_blocks_updated=Sig("blocks"), undo_state_changed=Sig("undo"),
        history_changed=Sig("hist"),
    ), emitted


def test_coerce_push_value():
    payload = default_payload()
    value, ok = entries.coerce_push_value("grid", payload)
    assert ok is True and json.loads(value)["tree"] == json.loads(payload)["tree"]
    _, ok = entries.coerce_push_value("grid", "junk")
    assert ok is False
    value, ok = entries.coerce_push_value("prompt", "x")
    assert (value, ok) == ("x", True)


def test_remember_kinds(tmp_path):
    br, emitted = fake(tmp_path)
    entries.remember_global_edit(br, "grid", default_payload())
    assert br.config.get_state("grid_layout") == default_payload()
    entries.remember_global_edit(br, "window_states", {"closed": [], "minimized": []})
    assert br.config.get_state("window_states") == {"closed": [], "minimized": []}
    entries.remember_global_edit(br, "urls", [{"id": "u1", "url": "https://a"}])
    assert br.state.urls[0].id == "u1" and "save" in emitted
    entries.remember_global_edit(br, "folder", {"root_path": "/x"})
    assert br.state.folder["root_path"] == "/x"
    br.state.images = [SimpleNamespace(id="i1", selected=False)]
    entries.remember_global_edit(br, "queue", [{"id": "i1", "selected": True}])
    assert br.state.images[0].selected is True
    entries.remember_global_edit(br, "prompt", "hello")
    assert br.state.prompt["user_prompt"] == "hello"
    entries.remember_global_edit(br, "prompt", {"template": "t2"})
    assert br.state.prompt["user_prompt"] == "t2"
    entries.remember_global_edit(br, "settings", {"timeouts": {"a": 1}})
    assert br.state.settings.timeouts == {"a": 1}
    entries.remember_global_edit(br, "action_blocks", [{"t": 1}])
    assert br.config.get_state("action_blocks") == [{"t": 1}]
    entries.remember_global_edit(br, "arena", {"urls": [{"id": "u", "url": "https://a"}],
                                               "folder": {"root_path": "/y"},
                                               "prompt": {"template": "p"}})
    assert br.state.urls[0].id == "u" and br.state.prompt["user_prompt"] == "p"
    entries.remember_global_edit(br, "nope", 1)  # unknown ignored


def test_apply_entries(tmp_path):
    br, _ = fake(tmp_path)
    assert entries.apply_undo_entry(br, None) is False
    assert entries.apply_undo_entry(br, {"kind": "urls", "value": [{"id": "u"}]}) is True
    assert br.state.urls[0].id == "u"
    assert entries.apply_undo_entry(br, {"kind": "prompt", "value": "p1"}) is True
    assert br.state.prompt["user_prompt"] == "p1"
    assert entries.apply_undo_entry(br, {"kind": "action_blocks", "value": []}) is True
    assert entries.apply_undo_entry(br, {"kind": "mystery", "value": 1}) is True
    assert entries.apply_undo_entry(br, {"kind": "arena", "value": {
        "urls": [{"id": "u2", "url": "https://b"}], "folder": {"r": 1},
        "prompt": "raw"}}) is True
    assert br.state.urls[0].id == "u2"


def test_undo_to_empty_branches(tmp_path):
    br, _ = fake(tmp_path)
    entries.undo_to_empty(br, "grid")
    assert br.config.get_state("grid_layout") == default_payload()
    entries.undo_to_empty(br, "window_states")
    entries.undo_to_empty(br, "urls")
    assert br.state.urls == []
    entries.undo_to_empty(br, "folder")
    assert br.state.folder["root_path"] == ""
    entries.undo_to_empty(br, "prompt")
    assert br.state.prompt["user_prompt"] == ""
    entries.undo_to_empty(br, "queue")  # log-only branch


def test_undo_redo_round_trip(tmp_path):
    br, _ = fake(tmp_path)
    assert UndoHistoryMixin.undo(br) == "null"  # nothing to undo
    assert UndoHistoryMixin.push_global_history(br, "prompt", json.dumps("v1")) is True
    assert UndoHistoryMixin.push_global_history(br, "prompt", json.dumps("v2")) is True
    assert br.state.prompt["user_prompt"] == "v2"
    res = json.loads(UndoHistoryMixin.undo(br))
    assert res["kind"] == "prompt"
    assert br.state.prompt["user_prompt"] == "v1"  # previous entry applied
    res = json.loads(UndoHistoryMixin.redo(br))
    assert br.state.prompt["user_prompt"] == "v2"
    assert json.loads(UndoHistoryMixin.get_undo_history(br))["index"] == 1


def test_push_global_grid_paths(tmp_path):
    br, _ = fake(tmp_path)
    assert UndoHistoryMixin.push_global_history(br, "grid", default_payload()) is True
    assert UndoHistoryMixin.push_global_history(br, "grid", "junk") is False


def test_stack_and_grid_projections(tmp_path):
    assert project_stack_result('{"kind": "prompt", "value": "v"}') == '"v"'
    assert project_stack_result('{"kind": "grid", "value": "g"}') == "null"
    assert project_stack_result("junk") == "null"
    assert project_grid_result('{"kind": "grid", "value": "g"}') == "g"
    assert project_grid_result('{"kind": "prompt", "value": "v"}') == "null"
    br, _ = fake(tmp_path)
    UndoHistoryMixin.push_stack_history(br, "[1]")
    proj = json.loads(UndoHistoryMixin.get_stack_history(br))
    assert proj["history"] == [{"kind": "arena", "value": [1]}]
    UndoHistoryMixin.push_stack_history(br, "junk")  # silent ignore
    br.undo = UndoHistoryMixin.undo.__get__(br)
    br.redo = UndoHistoryMixin.redo.__get__(br)
    assert UndoHistoryMixin.undo_stack(br) == "null"  # nothing stacked
    assert UndoHistoryMixin.undo_grid_layout(br) == "null"


# ── B7: URL rows round-trip through undo/redo/push with their tab link ──

def test_url_rows_from_js_keep_tab_link():
    rows = entries.url_rows_from_js([
        {"id": "u1", "url": "https://a", "tab_id": "T1", "status": "ok", "last_checked": "t",
         "receiver": True, "reason": ""},
        {"url": "https://b"},                       # no id, no tab
        {"id": "u3", "url": "https://c", "tab_id": None},
    ])
    assert [(r.id, r.tab_id) for r in rows] == [("u1", "T1"), ("url_1", ""), ("u3", "")]
    assert rows[0].last_status == "ok" and rows[0].last_checked == "t"
    assert (rows[0].receiver, rows[0].receiver_reason) == (True, "")  # S7: kept
    arena_rows = entries.arena_url_rows_from_js([{"id": "u1", "url": "https://a", "tab_id": "T9",
                                                  "receiver": False, "reason": "offline"}])
    assert (arena_rows[0].id, arena_rows[0].tab_id) == ("u1", "T9")
    assert (arena_rows[0].receiver, arena_rows[0].receiver_reason) == (False, "offline")  # S7


def test_remember_and_apply_urls_keep_tab_link(tmp_path):
    br, _ = fake(tmp_path)
    snap = [{"id": "u1", "url": "https://a", "tab_id": "T1"}]
    entries.remember_global_edit(br, "urls", snap)
    assert br.state.urls[0].tab_id == "T1"
    br.state.urls = []
    assert entries.apply_undo_entry(br, {"kind": "urls", "value": snap}) is True
    assert br.state.urls[0].tab_id == "T1"
    entries.remember_global_edit(br, "arena", {"urls": [{"id": "u2", "url": "https://b", "tab_id": "T2"}]})
    assert br.state.urls[0].tab_id == "T2"
