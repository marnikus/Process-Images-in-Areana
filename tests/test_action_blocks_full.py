"""D5 mutation triage: action_blocks full-behavior tests.

Targets the biggest survivor cluster (from_dict 464 + create_default_block
198): every defn-driven default, fallback default, migration, id rules,
required-block auto-append, validation, JSON parse fallback, preset upsert.
"""

import copy

from app.core import action_blocks as ab
from app.core.action_blocks import (
    ActionBlock,
    BLOCK_DEFINITIONS,
    BUILTIN_BLOCKS,
    DEFAULT_STACK_ORDER,
    RETIRED_KEYS,
    create_default_block,
    default_stack,
    load_stack_from_dicts,
    parse_stack_json,
    remove_stack_preset,
    stack_to_dicts,
    upsert_stack_preset,
    validate_stack,
)


class TestFromDict:
    def test_unknown_block_uses_plain_fallbacks(self):
        b = ActionBlock.from_dict({"block_id": "NOPE", "id": "x1"})
        assert b.block_id == "NOPE"
        assert b.id == "x1"
        assert b.name == ""
        assert b.description == ""
        assert b.icon == ""
        assert b.enabled is True
        assert b.selector == ""
        assert b.match_mode == "contains"
        assert b.click_enabled is True
        assert b.highlight_enabled is True
        assert b.color == "#FF0000"
        assert b.timeout_ms == 10000
        assert b.pre_delay_ms == 200
        assert b.highlight_ms == 2000
        assert b.confirm_pause_ms == 700
        assert b.highlight_duration_ms == 2000
        assert b.required is False
        assert b.category == "action"
        assert b.extra == {}

    def test_empty_dict_gets_auto_id(self):
        b = ActionBlock.from_dict({})
        assert b.block_id == ""
        assert b.id  # non-empty auto id
        assert b.id.startswith("_")

    def test_known_block_uses_definition_defaults(self):
        for bid, defn in BLOCK_DEFINITIONS.items():
            b = ActionBlock.from_dict({"block_id": bid})
            assert b.block_id == bid
            assert b.name == defn.get("name", "")
            assert b.icon == defn.get("icon", "")
            assert b.category == defn.get("category", "action")
            assert b.required == defn.get("required", False)
            assert b.color == defn.get("default_color", "#FF0000")
            assert b.timeout_ms == defn.get("default_timeout_ms", 10000)
            assert b.pre_delay_ms == defn.get("default_pre_delay_ms", 200)
            assert b.highlight_ms == defn.get("default_highlight_ms", 2000)
            assert b.confirm_pause_ms == defn.get("default_confirm_pause_ms", 700)
            assert b.highlight_duration_ms == b.highlight_ms

    def test_specific_defn_values(self):
        # NOTE: from_dict does NOT inherit default_selector / default_enabled
        # from the definition (only name/icon/category/required/defaults for
        # the explicit list) — characterization of current behavior, D5 triage.
        b = ActionBlock.from_dict({"block_id": "CUSTOM_FIND"})
        assert b.selector == ""
        assert b.match_mode == "contains"
        c = ActionBlock.from_dict({"block_id": "CHECK_SECURITY"})
        assert c.match_text == "Security Verification"
        o = ActionBlock.from_dict({"block_id": "OBSERVE_BASELINE"})
        assert o.highlight_enabled is False
        assert o.required is True
        assert o.name == "Observe Baseline"

    def test_retired_keys_are_dropped(self):
        data = {"block_id": "PAUSE"}
        for rk in RETIRED_KEYS:
            data[rk] = "junk"
        b = ActionBlock.from_dict(data)
        assert b.block_id == "PAUSE"
        assert all(rk not in data for rk in RETIRED_KEYS)

    def test_highlight_duration_migration(self):
        b = ActionBlock.from_dict({"block_id": "PAUSE", "highlight_duration_ms": 555})
        assert b.highlight_ms == 555
        assert b.highlight_duration_ms == 555

    def test_explicit_fields_win_over_defaults(self):
        b = ActionBlock.from_dict({
            "block_id": "CUSTOM_FIND",
            "id": "keep_me",
            "enabled": False,
            "selector": "a",
            "match_mode": "exact",
            "click_enabled": False,
            "color": "#123456",
            "timeout_ms": 1,
            "custom_name": "  My name ",
            "highlight_ms": 77,
        })
        assert b.id == "keep_me"
        assert b.enabled is False
        assert b.selector == "a"
        assert b.match_mode == "exact"
        assert b.click_enabled is False
        assert b.color == "#123456"
        assert b.timeout_ms == 1
        assert b.custom_name == "  My name "
        assert b.highlight_ms == 77
        assert b.highlight_duration_ms == 77

    def test_extra_passthrough(self):
        b = ActionBlock.from_dict({"block_id": "PAUSE", "extra": {"k": 1}})
        assert b.extra == {"k": 1}

    def test_display_name(self):
        assert ActionBlock.from_dict({"block_id": "PAUSE"}).display_name == "Custom Pause"
        assert ActionBlock.from_dict({"block_id": "PAUSE", "custom_name": "  Zed "}).display_name == "Zed"
        assert ActionBlock.from_dict({"block_id": "PAUSE", "custom_name": "   "}).display_name == "Custom Pause"


class TestToDict:
    def test_round_trip(self):
        original = ActionBlock.from_dict({"block_id": "CUSTOM_FIND", "selector": "img"})
        data = original.to_dict()
        assert data["highlight_duration_ms"] == original.highlight_ms
        back = ActionBlock.from_dict(dict(data))
        assert back.selector == "img"
        assert back.timeout_ms == original.timeout_ms

    def test_stack_to_dicts(self):
        stack = default_stack()
        dicts = stack_to_dicts(stack)
        assert [d["block_id"] for d in dicts] == DEFAULT_STACK_ORDER


class TestCreateDefaultBlock:
    def test_known_type_from_definition(self):
        b = create_default_block("CUSTOM_FIND")
        assert b.block_id == "CUSTOM_FIND"
        assert b.name == "Find & Click"
        assert b.selector == "button"
        assert b.click_enabled is True
        assert b.category == "action"

    def test_unknown_type_fallbacks(self):
        b = create_default_block("Mystery")
        assert b.block_id == "Mystery"
        assert b.name == "Mystery"
        assert b.icon == "extension"
        assert b.enabled is True
        assert b.color == "#FF0000"
        assert b.timeout_ms == 10000
        assert b.pre_delay_ms == 200
        assert b.highlight_ms == 2000
        assert b.highlight_duration_ms == 2000
        assert b.confirm_pause_ms == 700
        assert b.required is False
        assert b.category == "action"
        assert b.extra == {}

    def test_custom_id_respected(self):
        assert create_default_block("PAUSE", custom_id="abc").id == "abc"

    def test_auto_id_prefixed(self):
        assert create_default_block("PAUSE").id.startswith("pause_")

    def test_extra_defaults_copied_not_shared(self):
        b1 = create_default_block("PAUSE")
        b2 = create_default_block("PAUSE")
        b1.extra["x"] = 1
        assert "x" not in b2.extra

    def test_every_definition_type_creates(self):
        for bid in BLOCK_DEFINITIONS:
            b = create_default_block(bid)
            assert b.block_id == bid
            assert b.name


class TestLoadAndValidate:
    def test_empty_input_gets_required_blocks(self):
        stack = load_stack_from_dicts([])
        ids = {b.block_id for b in stack}
        required = {bid for bid, d in BLOCK_DEFINITIONS.items() if d.get("required")}
        assert required <= ids
        assert len(stack) == len(required)

    def test_non_dict_entries_skipped(self):
        stack = load_stack_from_dicts(["junk", 42, None, {"block_id": "PAUSE"}])
        ids = [b.block_id for b in stack]
        assert "PAUSE" in ids
        assert "junk" not in ids

    def test_legacy_dict_by_id_uses_definition(self):
        stack = load_stack_from_dicts([{"id": "PAUSE"}])
        match = [b for b in stack if b.block_id == "PAUSE"]
        assert len(match) == 1
        assert match[0].id == "PAUSE"
        assert match[0].name == "Custom Pause"

    def test_legacy_unknown_id_falls_to_from_dict(self):
        stack = load_stack_from_dicts([{"id": "custom_1"}])
        match = [b for b in stack if b.id == "custom_1"]
        assert len(match) == 1
        assert match[0].block_id == ""

    def test_broken_entry_skipped_not_fatal(self):
        stack = load_stack_from_dicts(["not a dict", {"block_id": "PAUSE"}])
        assert "PAUSE" in [b.block_id for b in stack]

    def test_missing_required_is_appended(self):
        stack = load_stack_from_dicts([{"block_id": "PAUSE"}])
        ids = {b.block_id for b in stack}
        assert "OBSERVE_BASELINE" in ids
        assert "PAUSE" in ids

    def test_validate_empty(self):
        ok, msg = validate_stack([])
        assert not ok
        assert msg == "Stack empty"

    def test_validate_missing_required(self):
        ok, msg = validate_stack([ActionBlock.from_dict({"block_id": "PAUSE"})])
        assert not ok
        assert "Required block" in msg

    def test_validate_disabled_required(self):
        stack = default_stack()
        for b in stack:
            if b.required:
                b.enabled = False
        ok, msg = validate_stack(stack)
        assert not ok
        assert "disabled" in msg

    def test_validate_ok(self):
        ok, msg = validate_stack(default_stack())
        assert ok
        assert msg == ""


class TestParseStackJson:
    def test_valid_list(self):
        import json
        payload = json.dumps([{"block_id": "PAUSE", "id": "p1"}])
        stack = parse_stack_json(payload)
        assert "PAUSE" in [b.block_id for b in stack]
        assert any(b.id == "p1" for b in stack)

    def test_invalid_json_falls_back_to_default_stack(self):
        assert [b.block_id for b in parse_stack_json("{broken")] == DEFAULT_STACK_ORDER

    def test_empty_payload_loads_required_only(self):
        # "" / None -> "[]" -> load path -> required blocks appended
        required = {bid for bid, d in BLOCK_DEFINITIONS.items() if d.get("required")}
        for payload in (None, ""):
            ids = {b.block_id for b in parse_stack_json(payload)}
            assert required == ids

    def test_non_list_json_falls_back(self):
        assert [b.block_id for b in parse_stack_json("{"
            "\"block_id\": \"PAUSE\"}")] == DEFAULT_STACK_ORDER


class TestPresets:
    def test_upsert_new(self):
        out = upsert_stack_preset(None, "A", ["x"])
        assert out == [{"name": "A", "blocks": ["x"]}]

    def test_upsert_replaces_same_name_and_moves_to_end(self):
        out = upsert_stack_preset([{"name": "A", "blocks": [1]}], "A", [2])
        out = upsert_stack_preset(out, "B", [3])
        out = upsert_stack_preset(out, "A", [4])
        assert [p["name"] for p in out] == ["B", "A"]
        assert out[-1]["blocks"] == [4]

    def test_upsert_ignores_non_dict_presets(self):
        out = upsert_stack_preset(["junk"], "A", [1])
        assert [p for p in out if isinstance(p, dict)] == [{"name": "A", "blocks": [1]}]

    def test_upsert_empty_name_raises(self):
        try:
            upsert_stack_preset([], "   ", [1])
            assert False, "expected ValueError"
        except ValueError:
            pass

    def test_upsert_empty_blocks_raises(self):
        for blocks in ([], None, "nope"):
            try:
                upsert_stack_preset([], "A", blocks)
                assert False, "expected ValueError"
            except ValueError:
                pass

    def test_upsert_deep_copies_blocks(self):
        blocks = [{"k": [1]}]
        upsert_stack_preset([], "A", blocks)
        blocks[0]["k"].append(2)
        # stored copy must not change
        out = upsert_stack_preset([], "B", blocks)
        assert out[-1]["blocks"][0]["k"] == [1, 2]

    def test_remove_existing(self):
        kept, removed = remove_stack_preset([{"name": "A"}, {"name": "B"}], "A")
        assert removed is True
        assert [p["name"] for p in kept] == ["B"]

    def test_remove_missing(self):
        kept, removed = remove_stack_preset([{"name": "A"}], "Z")
        assert removed is False
        assert len(kept) == 1

    def test_remove_none_presets(self):
        kept, removed = remove_stack_preset(None, "A")
        assert kept == []
        assert removed is False

    def test_builtin_blocks_json(self):
        assert isinstance(ab.get_builtin_blocks_json(), str)
        assert ab.get_default_stack_json().startswith("[")


def test_module_import_surface():
    assert isinstance(BUILTIN_BLOCKS, list)
    assert isinstance(copy.deepcopy(DEFAULT_STACK_ORDER), list)
