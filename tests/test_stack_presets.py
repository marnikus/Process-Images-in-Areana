"""Stack presets — named full-stack snapshots (pure helpers, no Qt)."""

import pytest

from app.core.action_blocks import remove_stack_preset, upsert_stack_preset


def test_upsert_new_preset():
    out = upsert_stack_preset([], "My stack", [{"block_id": "SUBMIT"}])
    assert out == [{"name": "My stack", "blocks": [{"block_id": "SUBMIT"}]}]


def test_upsert_overwrites_same_name_and_moves_to_end():
    existing = [{"name": "A", "blocks": [1]}, {"name": "B", "blocks": [2]}]
    out = upsert_stack_preset(existing, "A", [{"block_id": "X"}])
    assert [p["name"] for p in out] == ["B", "A"]
    assert out[1]["blocks"] == [{"block_id": "X"}]


def test_upsert_deepcopies_blocks():
    blocks = [{"block_id": "SUBMIT", "nested": {"n": 1}}]
    out = upsert_stack_preset([], "S", blocks)
    blocks[0]["nested"]["n"] = 999
    assert out[0]["blocks"][0]["nested"]["n"] == 1


def test_upsert_rejects_blank_name():
    with pytest.raises(ValueError):
        upsert_stack_preset([], "   ", [{"block_id": "SUBMIT"}])


def test_upsert_rejects_non_list_or_empty_blocks():
    with pytest.raises(ValueError):
        upsert_stack_preset([], "S", {"block_id": "SUBMIT"})
    with pytest.raises(ValueError):
        upsert_stack_preset([], "S", [])


def test_upsert_tolerates_none_and_nondicts():
    out = upsert_stack_preset(None, "S", [{"block_id": "SUBMIT"}])
    assert [p["name"] for p in out] == ["S"]
    out = upsert_stack_preset(["junk", None, {"name": "K", "blocks": [1]}], "S",
                              [{"block_id": "SUBMIT"}])
    assert [p["name"] for p in out] == ["K", "S"]


def test_remove_found():
    existing = [{"name": "A", "blocks": [1]}, {"name": "B", "blocks": [2]}]
    out, removed = remove_stack_preset(existing, "A")
    assert removed is True
    assert [p["name"] for p in out] == ["B"]


def test_remove_missing_or_none():
    existing = [{"name": "A", "blocks": [1]}]
    out, removed = remove_stack_preset(existing, "ZZ")
    assert removed is False
    assert out == existing
    out, removed = remove_stack_preset(None, "A")
    assert removed is False
    assert out == []
