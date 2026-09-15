"""Retained named-library semantics: preserve every block parameter, never execute imports."""

import json
import re
from copy import deepcopy
from typing import Any

from image_queue.domain.validation import ContractError, require_fields
from image_queue.workspace.layout import validate_layout

FAMILIES = (
    "stacks",
    "blocks",
    "templates",
    "prompts",
    "variables",
    "connections",
    "windows",
    "archives",
)
MAX_LIBRARY_BYTES = 1_000_000


def empty_libraries() -> dict[str, Any]:
    return {family: {} for family in FAMILIES}


def bounded_json(value: Any) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(text.encode("utf-8")) > MAX_LIBRARY_BYTES:
            raise ValueError("oversized")
        _wire_values(value)
        return text
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ContractError("Library must be finite JSON within 1 MB") from exc


def name_check(name: Any) -> None:
    if not isinstance(name, str) or not name.strip() or len(name) > 80 or "\x00" in name:
        raise ContractError("Library name must contain 1–80 characters without NUL")


def validate_variables(value: Any) -> None:
    if not isinstance(value, dict) or len(value) > 200:
        raise ContractError("Variables must be a map with at most 200 entries")
    for name, text in value.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", name):
            raise ContractError("Variable names use lowercase letters, numbers and underscores")
        if not isinstance(text, str) or len(text) > 64000:
            raise ContractError("Variable values must be text up to 64000 characters")
    bounded_json(value)


def validate_entry(family: str, value: Any) -> None:
    if family not in FAMILIES:
        raise ContractError("Unknown library family")
    if not isinstance(value, dict):
        raise ContractError("Library entry must be an object")
    if family in ("templates", "prompts") and not isinstance(value.get("body"), str):
        raise ContractError("Template/prompt requires a body string")
    if family == "stacks":
        _validate_blocks(value.get("blocks"))
    if family == "variables":
        validate_variables(value)
    if family == "windows":
        validate_layout(value.get("layout", value))
    bounded_json(value)


def _validate_blocks(blocks: Any) -> None:
    if not isinstance(blocks, list) or len(blocks) > 200:
        raise ContractError("Stack requires at most 200 blocks")
    if any(not isinstance(block, dict) for block in blocks):
        raise ContractError("Every stack block must be an object")


def validate_libraries(value: Any) -> None:
    data = require_fields(value, set(FAMILIES), "libraries")
    bounded_json(value)
    for family, entries in data.items():
        if not isinstance(entries, dict) or len(entries) > 100:
            raise ContractError("Library family supports at most 100 entries")
        for name, entry in entries.items():
            name_check(name)
            validate_entry(family, entry)


def change_library(libraries: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    require_fields(request, {"family", "name", "value", "operation"}, "library change")
    family, name = request["family"], request["name"]
    if family not in FAMILIES:
        raise ContractError("Unknown library family")
    name_check(name)
    result = deepcopy(libraries)
    operation = request["operation"]
    if operation == "delete" and name in result[family]:
        del result[family][name]
    elif operation in ("create", "update"):
        if (name in result[family]) != (operation == "update"):
            raise ContractError("Create/update conflict; choose an explicit operation")
        result[family][name] = deepcopy(request["value"])
    else:
        raise ContractError("Unknown operation or missing library entry")
    validate_libraries(result)
    return result


def _wire_values(value: Any) -> None:
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 50:
            raise ContractError("Library nesting exceeds 50 levels")
        _wire_scalar(item)
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ContractError("JSON object keys must be text")
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)


def _wire_scalar(item: Any) -> None:
    if type(item) in (int, float) and abs(item) > 2**53 - 1:
        raise ContractError("Library numbers must fit the JavaScript safe range; use text IDs")
    if item is not None and not isinstance(item, dict | list | str | bool | int | float):
        raise ContractError("Library value is not a JSON primitive/container")
