import json
from copy import deepcopy

import pytest

from image_queue.domain.validation import ContractError
from image_queue.persistence.export import save_library_file
from image_queue.workspace.extensions import defaults, upgrade_state, validate_extensions
from image_queue.workspace.libraries import (
    FAMILIES,
    bounded_json,
    change_library,
    empty_libraries,
    name_check,
    validate_entry,
    validate_libraries,
    validate_variables,
)
from image_queue.workspace.library_io import (
    export_libraries,
    merge_import,
    parse_json,
    preview_import,
)
from image_queue.workspace.variables import render_prompt


def entries(workspace):
    return {
        "stacks": {
            "blocks": [
                {
                    "block_id": "CUSTOM_FIND",
                    "script": "<script>inert</script>",
                    "unknown": {"x": [1, True]},
                }
            ]
        },
        "blocks": {"block_id": "CUSTOM_FIND", "selector": "do-not-execute"},
        "templates": {"body": "literal {x}\r\n"},
        "prompts": {"body": "{x}", "mode": "template", "variables": {"x": "č"}},
        "variables": {"x": "{y}", "y": "one pass"},
        "connections": json.loads(workspace["connection"]),
        "windows": workspace["layout"],
        "archives": {"unrecognized": [1, 2, 3]},
    }


def test_all_family_crud_backup_and_immutable_input(workspace):
    original = empty_libraries()
    libraries = original
    for family, value in entries(workspace).items():
        change = dict(family=family, name="<safe>&č", value=value, operation="create")
        libraries = change_library(libraries, change)
        with pytest.raises(ContractError):
            change_library(libraries, change)
        libraries = change_library(libraries, {**change, "operation": "update"})
    assert original == empty_libraries()
    assert set(libraries) == set(FAMILIES)
    restored = preview_import(export_libraries(libraries))["libraries"]
    assert restored == libraries
    with pytest.raises(ContractError, match="collision"):
        merge_import(libraries, restored)
    assert merge_import(original, restored) == libraries
    for family in FAMILIES:
        libraries = change_library(
            libraries, dict(family=family, name="<safe>&č", value=None, operation="delete")
        )
    assert libraries == original


@pytest.mark.parametrize(
    "family,value",
    [
        ("other", {}),
        ("stacks", {}),
        ("stacks", {"blocks": [None]}),
        ("stacks", {"blocks": [{}] * 201}),
        ("blocks", []),
        ("connections", 1),
        ("templates", {}),
        ("prompts", {"body": 0}),
        ("variables", {"Upper": "bad"}),
        ("windows", {}),
    ],
)
def test_invalid_entries(family, value):
    with pytest.raises(ContractError):
        validate_entry(family, value)


@pytest.mark.parametrize(
    "value",
    [
        [],
        {"x": 1},
        {"x": "a" * 64001},
        {"Bad": ""},
        {1: ""},
        {"x" + str(i): "" for i in range(201)},
    ],
)
def test_invalid_variables(value):
    with pytest.raises(ContractError):
        validate_variables(value)


@pytest.mark.parametrize("name", ["", " ", "x" * 81, "\x00", None, 7])
def test_bad_names(name):
    with pytest.raises(ContractError):
        name_check(name)


def test_invalid_library_commands_and_limits():
    for request in [
        dict(family="wrong", name="a", value={}, operation="create"),
        dict(family="blocks", name="a", value={}, operation="update"),
        dict(family="blocks", name="a", value={}, operation="delete"),
        dict(family="blocks", name="a", value={}, operation="other"),
    ]:
        with pytest.raises(ContractError):
            change_library(empty_libraries(), request)
    for value in [float("nan"), object(), "x" * 1_000_001]:
        with pytest.raises(ContractError):
            bounded_json(value)
    value = empty_libraries()
    value["blocks"] = {"x" + str(i): {} for i in range(101)}
    with pytest.raises(ContractError):
        validate_libraries(value)
    value["blocks"] = []
    with pytest.raises(ContractError):
        validate_libraries(value)


@pytest.mark.parametrize(
    "text",
    [
        "{",
        "[]",
        '{"x":1,"x":2}',
        "NaN",
        '"' + "x" * 1_000_000 + '"',
        '{"format":"future"}',
        '{"format":"image-queue/libraries","version":2,"libraries":{}}',
    ],
)
def test_invalid_import(text):
    with pytest.raises(ContractError):
        preview_import(text)


def test_lossless_legacy_stack_and_block():
    raw = {
        "format": "chat-v-bot/stack-preset",
        "format_version": 1,
        "name": "Legacy",
        "stack": [{"block_id": "old", "anything": "keep"}],
        "custom_blocks": [{"custom_name": "b", "js": "never run"}],
        "unknown": {"private": "retained locally"},
    }
    libraries = preview_import(json.dumps(raw))["libraries"]
    assert libraries["stacks"]["Legacy"]["legacy_source"] == raw
    assert libraries["blocks"]["Imported block 1"] == raw["custom_blocks"][0]
    for bad in [2, True, None]:
        with pytest.raises(ContractError):
            preview_import(json.dumps({**raw, "format_version": bad}))
    with pytest.raises(ContractError):
        preview_import(json.dumps({**raw, "custom_blocks": [None]}))
    block = {**raw, "format": "chat-v-bot/action-block", "block": {"x": 1}}
    assert (
        preview_import(json.dumps(block))["libraries"]["blocks"]["Legacy"]["legacy_source"] == block
    )
    with pytest.raises(ContractError):
        preview_import(json.dumps({**block, "block": []}))


def test_legacy_library_and_window_mapping(workspace):
    raw = {
        "stack_presets": {"s": {"blocks": []}},
        "template_presets": {"t": {"body": "text"}},
        "prompt_presets": {"p": {"text": "{nick}", "title": "old"}},
        "ai_connections": {"c": {"provider": "old"}},
        "unknown": {"keep": True},
    }
    mapped = preview_import(json.dumps(raw))["libraries"]
    assert mapped["archives"]["Original legacy preset library"] == raw
    assert mapped["prompts"]["p"]["body"] == "{nick}"
    for bad in [{**raw, "stack_presets": []}, {**raw, "stack_presets": {"x": 1}}]:
        with pytest.raises(ContractError):
            preview_import(json.dumps(bad))
    doc = {
        "format": "chat-v-bot.window-preset",
        "schema_version": 1,
        "name": "desk",
        "grid": {"tree": workspace["layout"]["tree"]},
        "window_states": {k: workspace["layout"][k] for k in ("closed", "minimized")},
        "windows": [{"legacy_bounds": "preserved"}],
    }
    entry = preview_import(json.dumps(doc))["libraries"]["windows"]["desk"]
    assert entry["layout"] == workspace["layout"]
    assert entry["legacy_source"] == doc
    for bad in [{**doc, "schema_version": 9}, {**doc, "grid": []}]:
        with pytest.raises(ContractError):
            preview_import(json.dumps(bad))


def test_literal_render_and_no_recursive_substitution():
    text = " preserve\r\n{x} {unknown} {unknown} {Bad-Name} {unclosed"
    assert render_prompt(text, {"x": "{y}"}, "literal")["text"] == text
    result = render_prompt(text, {"x": "{y}", "y": "NEVER"}, "template")
    assert "{y}" in result["text"] and "NEVER" not in result["text"]
    assert result["unknown"] == ["unknown"]
    assert result["malformed"] == ["{Bad-Name}", "unbalanced braces"]
    assert not result["ok"]
    assert render_prompt("{x}", {"x": "✅"}, "template")["text"] == "✅"
    for text, mode in [("a", "bad"), ("a" * 64001, "literal"), ("{x}" * 100, "template")]:
        with pytest.raises(ContractError):
            render_prompt(text, {"x": "b" * 64000}, mode)
    assert parse_json("{}") == {}


def test_additive_migration_preserves_all_undo_entries(state):
    old = deepcopy(state)
    for key in defaults():
        old["workspace"].pop(key)
    old["history"] = [
        {
            "label": "legacy",
            "before": deepcopy(old["workspace"]),
            "after": deepcopy(old["workspace"]),
        }
    ]
    old["cursor"] = 0
    migrated = upgrade_state(old)
    assert (
        migrated["workspace"] == migrated["history"][0]["before"] == migrated["history"][0]["after"]
    )
    assert "libraries" not in old["workspace"]
    assert upgrade_state(migrated) == migrated


@pytest.mark.parametrize(
    "key,value",
    [
        ("prompt_mode", "bad"),
        ("scan_options", {"recursive": 1, "max_bytes": 2, "output_folder": ""}),
        ("selection", []),
        ("selection", {"a": {"sha256": 1, "decision": "selected"}}),
        ("selection", {"a": {"sha256": "", "decision": "completed"}}),
    ],
)
def test_invalid_extensions(key, value):
    with pytest.raises(ContractError):
        validate_extensions({**defaults(), key: value})


def test_export_new_file_only(tmp_path):
    text = export_libraries(empty_libraries())
    target = tmp_path / "presets.json"
    save_library_file(target, text)
    assert target.read_text() == text
    with pytest.raises(FileExistsError):
        save_library_file(target, text)
    with pytest.raises(ContractError):
        save_library_file(tmp_path / "bad.json", "{")
    assert not (tmp_path / "bad.json").exists()


def test_quick_layouts_included_in_backup_and_collisions_refused(workspace):
    from image_queue.workspace.library_io import export_workspace_libraries

    workspace["layouts"]["quick"] = deepcopy(workspace["layout"])
    backup = preview_import(export_workspace_libraries(workspace))["libraries"]
    assert backup["windows"]["quick"] == workspace["layout"]
    workspace["libraries"]["windows"]["quick"] = deepcopy(workspace["layout"])
    export_workspace_libraries(workspace)
    workspace["libraries"]["windows"]["quick"]["closed"] = []
    with pytest.raises(ContractError, match="Conflicting"):
        export_workspace_libraries(workspace)


def test_legacy_window_library_preserved(workspace):
    document = {
        "format": "chat-v-bot.window-preset",
        "schema_version": 1,
        "name": "desk",
        "grid": {"tree": workspace["layout"]["tree"]},
        "window_states": {key: workspace["layout"][key] for key in ("closed", "minimized")},
    }
    raw = {"window_presets": {"desk": document}, "unknown": [1, 2, 3]}
    preview = preview_import(json.dumps(raw))["libraries"]
    assert preview["windows"]["desk"]["layout"] == workspace["layout"]
    assert preview["archives"]["Original legacy window library"] == raw
    for bad in [{"window_presets": []}, {"window_presets": {"wrong": document}}]:
        with pytest.raises(ContractError):
            preview_import(json.dumps(bad))


def test_json_wire_range_and_depth_prevent_lossy_roundtrips():
    nested = {}
    for _ in range(52):
        nested = {"child": nested}
    for value in [2**53, -(2**53), 1e30, {1: "not a string key"}, (1, 2), nested]:
        with pytest.raises(ContractError):
            bounded_json(value)
    assert parse_json(bounded_json({"n": 2**53 - 1})) == {"n": 2**53 - 1}
    with pytest.raises(ContractError):
        parse_json('{"n":9007199254740993}')


def test_boolean_to_number_is_a_real_edit_and_history_must_agree(state):
    from image_queue.domain.validation import same_json
    from image_queue.workspace.history import edit_state, validate_state

    initial = deepcopy(state["workspace"])
    initial["workflow"] = [{"flag": True}]
    first = edit_state(state, initial, "Boolean")
    changed = deepcopy(first["workspace"])
    changed["workflow"][0]["flag"] = 1
    second = edit_state(first, changed, "Numeric parameter")
    assert second["revision"] == first["revision"] + 1
    assert type(second["workspace"]["workflow"][0]["flag"]) is int
    broken = deepcopy(second)
    broken["workspace"]["workflow"][0]["flag"] = True
    with pytest.raises(ContractError):
        validate_state(broken)
    assert not same_json([True], [1])
    assert not same_json({}, [])
    assert not same_json([], {})
    assert same_json(1.0, 1)
