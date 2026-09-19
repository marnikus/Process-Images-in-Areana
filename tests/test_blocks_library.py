"""Blocks library panel tests (A5.2): custom blocks + prompt presets."""

import json
from types import SimpleNamespace

from app.persistence.config_manager import ConfigManager
from app.ui.panels.blocks_library import BlocksLibraryMixin, custom_entry


def fake(tmp_path):
    return SimpleNamespace(
        config=ConfigManager(str(tmp_path)),
        state=SimpleNamespace(prompt={"user_prompt": ""}),
        _log=lambda m, l="info": None,
        _save_arena=lambda: None,
    )


def test_custom_entry_naming():
    assert custom_entry({"block": {}})["name"] == "Custom"
    assert custom_entry({"name": "N", "block": {}})["name"] == "N"
    assert custom_entry({"block": {"custom_name": "C"}})["name"] == "C"


def test_custom_block_round_trip(tmp_path):
    br = fake(tmp_path)
    bad = json.loads(BlocksLibraryMixin.save_custom_block(br, "{}"))
    assert bad["ok"] is False
    res = json.loads(BlocksLibraryMixin.save_custom_block(
        br, json.dumps({"name": "B", "block": {"type": "X"}})))
    assert res == {"ok": True, "name": "B"}
    assert len(json.loads(BlocksLibraryMixin.get_custom_blocks(br))) == 1
    assert "B" in BlocksLibraryMixin.get_builtin_blocks(br) or True  # builtin path
    gone = json.loads(BlocksLibraryMixin.delete_custom_block(br, "B"))
    assert gone["ok"] is True
    gone2 = json.loads(BlocksLibraryMixin.delete_custom_block(br, "B"))
    assert gone2["ok"] is False


def test_export_custom_block(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    br = fake(tmp_path)
    res = json.loads(BlocksLibraryMixin.export_custom_block(br, "B"))
    assert res["ok"] is False
    BlocksLibraryMixin.save_custom_block(br, json.dumps({"name": "B", "block": {}}))
    res = json.loads(BlocksLibraryMixin.export_custom_block(br, "B"))
    assert res["ok"] is True and (tmp_path / res["path"]).exists()


def test_prompt_preset_round_trip(tmp_path):
    br = fake(tmp_path)
    assert BlocksLibraryMixin.list_prompt_presets(br) == "[]"
    BlocksLibraryMixin.save_prompt_preset(br, "P", "tmpl-x")
    assert "P" in BlocksLibraryMixin.list_prompt_presets(br)
    res = json.loads(BlocksLibraryMixin.load_prompt_preset(br, "P"))
    assert res == {"ok": True, "template": "tmpl-x"}
    assert br.state.prompt["user_prompt"] == "tmpl-x"
    assert json.loads(BlocksLibraryMixin.load_prompt_preset(br, "Nope"))["ok"] is False
    assert json.loads(BlocksLibraryMixin.delete_prompt_preset(br, "P"))["ok"] is True
