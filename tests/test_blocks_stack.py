"""Blocks stack panel tests (A5.3): stack CRUD + presets + history save."""

import json
from types import SimpleNamespace

from app.persistence.config_manager import ConfigManager
from app.ui.panels.blocks_stack import (
    BlocksStackMixin,
    emit_action_blocks,
    get_action_blocks,
    save_action_blocks,
)


def fake(tmp_path):
    emitted = {}

    class Sig:
        def __init__(self, name):
            self.name = name

        def emit(self, *a):
            emitted[self.name] = a

    return SimpleNamespace(
        config=ConfigManager(str(tmp_path)),
        _log=lambda m, l="info": None,
        undo_service=SimpleNamespace(push=lambda *a: None, history=lambda: ([], -1),
                                     set_stack_projection=lambda h, i: emitted.update(proj=(h, i))),
        action_blocks_updated=Sig("blocks"),
        undo_state_changed=Sig("undo"), history_changed=Sig("hist"),
    ), emitted


def test_module_round_trip(tmp_path):
    br, emitted = fake(tmp_path)
    stack = get_action_blocks(br)
    assert len(stack) > 0  # default stack
    assert save_action_blocks(br, stack) is True
    assert "blocks" in emitted and "undo" in emitted
    emit_action_blocks(br)  # no crash, re-emits


def test_slot_crud_and_validation(tmp_path):
    br, _ = fake(tmp_path)
    assert BlocksStackMixin.get_action_blocks(br).startswith("[")
    bad = json.loads(BlocksStackMixin.save_action_blocks(br, "{}"))
    assert bad == {"ok": False, "error": "must be array"}
    empty = json.loads(BlocksStackMixin.add_action_block(br, ""))
    assert empty["ok"] is False
    res = json.loads(BlocksLibraryMixin_add(br))
    assert res["ok"] is True and res["id"]
    missing = json.loads(BlocksStackMixin.delete_action_block(br, "nope"))
    assert missing["ok"] is False
    gone = json.loads(BlocksStackMixin.delete_action_block(br, res["id"]))
    assert gone["ok"] is True
    reset = json.loads(BlocksStackMixin.reset_action_blocks(br))
    assert reset["ok"] is True and reset["count"] > 0


def BlocksLibraryMixin_add(br):
    from app.core.action_blocks import BLOCK_DEFINITIONS
    kind = next(iter(BLOCK_DEFINITIONS))
    return BlocksStackMixin.add_action_block(br, kind)


def test_stack_presets_and_export(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    br, _ = fake(tmp_path)
    (tmp_path / "config").mkdir(exist_ok=True)
    assert BlocksStackMixin.get_stack_presets(br) == "[]"
    res = json.loads(BlocksStackMixin.save_stack_preset(
        br, json.dumps({"name": "S", "blocks": [{"type": "X"}]})))
    assert res == {"ok": True, "name": "S"}
    assert "S" in BlocksStackMixin.get_stack_presets(br)
    assert json.loads(BlocksStackMixin.delete_stack_preset(br, "S"))["ok"] is True
    exp = json.loads(BlocksStackMixin.export_action_blocks(br, "[]"))
    assert exp["ok"] is False  # empty stack rejected


def test_save_stack_history_projects(tmp_path):
    br, emitted = fake(tmp_path)
    BlocksStackMixin.save_stack_history(br, "[1]", 0)
    assert emitted["proj"] == ([1], 0)
    BlocksStackMixin.save_stack_history(br, "junk", 0)  # silent ignore
    BlocksStackMixin.save_stack_history(br, "{}", "x")  # silent ignore
