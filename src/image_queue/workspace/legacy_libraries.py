"""Explicit compatibility mapping; the complete original document remains in each backup."""

from copy import deepcopy
from typing import Any

from image_queue.domain.validation import ContractError
from image_queue.workspace.libraries import empty_libraries, name_check

SECTIONS = {
    "stack_presets": "stacks",
    "template_presets": "templates",
    "ai_connections": "connections",
    "prompt_presets": "prompts",
}


def map_legacy(data: dict[str, Any]) -> dict[str, Any]:
    result = empty_libraries()
    if not data.get("format"):
        return _stored_library(data, result)
    name = data.get("name")
    name_check(name)
    if data.get("format") == "chat-v-bot.window-preset":
        return _window(data, result)
    if type(data.get("format_version")) is not int or data["format_version"] != 1:
        raise ContractError("Unsupported legacy version; retain the original backup")
    if data.get("format") == "chat-v-bot/stack-preset":
        result["stacks"][name] = {
            "blocks": deepcopy(data.get("stack")),
            "legacy_source": deepcopy(data),
        }
        _custom_blocks(data.get("custom_blocks"), result)
    elif data.get("format") == "chat-v-bot/action-block" and isinstance(data.get("block"), dict):
        result["blocks"][name] = {"block": deepcopy(data["block"]), "legacy_source": deepcopy(data)}
    else:
        raise ContractError("Unsupported legacy shape; original file is unchanged")
    return result


def _custom_blocks(blocks: Any, result: dict[str, Any]) -> None:
    if not isinstance(blocks, list) or any(not isinstance(block, dict) for block in blocks):
        raise ContractError("Legacy custom_blocks must be a list of objects")
    for index, block in enumerate(blocks):
        result["blocks"][f"Imported block {index + 1}"] = deepcopy(block)


def _sections(data: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    for section, family in SECTIONS.items():
        entries = data.get(section, {})
        if not isinstance(entries, dict):
            raise ContractError("Legacy library sections must be objects")
        for name, entry in entries.items():
            if not isinstance(entry, dict):
                raise ContractError("Legacy entry must be an object")
            result[family][name] = deepcopy(entry)
            if family == "prompts":
                result[family][name] = {"body": entry.get("text"), "legacy_source": deepcopy(entry)}
    result["archives"]["Original legacy preset library"] = deepcopy(data)
    return result


def _window(data: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ContractError("Unsupported legacy window version")
    grid, states = data.get("grid"), data.get("window_states")
    if not isinstance(grid, dict) or not isinstance(states, dict):
        raise ContractError("Missing legacy window tree/states")
    layout = {
        "tree": deepcopy(grid.get("tree")),
        "closed": deepcopy(states.get("closed")),
        "minimized": deepcopy(states.get("minimized")),
    }
    result["windows"][data["name"]] = {"layout": layout, "legacy_source": deepcopy(data)}
    return result


def _window_library(data: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    entries = data["window_presets"]
    if not isinstance(entries, dict):
        raise ContractError("Legacy window library must be an object")
    for name, document in entries.items():
        name_check(name)
        if not isinstance(document, dict) or document.get("name") != name:
            raise ContractError("Legacy window name mismatch; review the original document")
        _window(document, result)
    result["archives"]["Original legacy window library"] = deepcopy(data)
    return result


def _stored_library(data: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    if "window_presets" in data:
        return _window_library(data, result)
    if set(data) & set(SECTIONS):
        return _sections(data, result)
    raise ContractError("Unsupported legacy library; original file is unchanged")
