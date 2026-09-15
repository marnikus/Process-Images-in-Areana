"""Portable full-library backups and lossless retained stack/block import previews."""

import hashlib
import json
from copy import deepcopy
from typing import Any

from image_queue.domain.validation import ContractError, require_fields
from image_queue.workspace.legacy_libraries import map_legacy
from image_queue.workspace.libraries import (
    MAX_LIBRARY_BYTES,
    bounded_json,
    validate_libraries,
)

FORMAT = "image-queue/libraries"


def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("Duplicate JSON key in library import")
        result[key] = value
    return result


def parse_json(text: str) -> Any:
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_LIBRARY_BYTES:
        raise ContractError("Library import exceeds 1 MB")
    try:
        data = json.loads(text, object_pairs_hook=unique_keys)
        bounded_json(data)
        return data
    except (ValueError, RecursionError) as exc:
        raise ContractError("Invalid library JSON; nothing imported") from exc


def export_libraries(libraries: dict[str, Any]) -> str:
    validate_libraries(libraries)
    return bounded_json({"format": FORMAT, "version": 1, "libraries": libraries})


def preview_import(text: str) -> dict[str, Any]:
    data = parse_json(text)
    if not isinstance(data, dict):
        raise ContractError("Library import must be an object")
    if data.get("format") == FORMAT:
        require_fields(data, {"format", "version", "libraries"}, "library envelope")
        if type(data["version"]) is not int or data["version"] != 1:
            raise ContractError("Unsupported library version")
        libraries = data["libraries"]
        warnings: list[str] = []
    else:
        libraries = map_legacy(data)
        warnings = ["Legacy data preserved, not executable. Review every parameter."]
    validate_libraries(libraries)
    return {
        "libraries": deepcopy(libraries),
        "warnings": warnings,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def merge_import(current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    validate_libraries(incoming)
    result = deepcopy(current)
    for family, entries in incoming.items():
        if set(entries) & set(result[family]):
            raise ContractError("Import name collision; rename or delete explicitly first")
        result[family].update(deepcopy(entries))
    validate_libraries(result)
    return result


def export_workspace_libraries(workspace: dict[str, Any]) -> str:
    libraries = deepcopy(workspace["libraries"])
    for name, layout in workspace["layouts"].items():
        entry = libraries["windows"].get(name)
        if entry is not None and entry.get("layout", entry) != layout:
            raise ContractError("Conflicting quick/portable layout names; rename before backup")
        libraries["windows"].setdefault(name, deepcopy(layout))
    return export_libraries(libraries)
