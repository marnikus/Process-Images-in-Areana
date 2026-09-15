"""Additive workspace v1 fields; older snapshots and every undo entry migrate together."""

from copy import deepcopy
from typing import Any

from image_queue.domain.validation import ContractError, require_fields, require_integer
from image_queue.workspace.libraries import (
    empty_libraries,
    validate_entry,
    validate_libraries,
    validate_variables,
)


def defaults() -> dict[str, Any]:
    return {
        "workflow": [],
        "libraries": empty_libraries(),
        "variables": {},
        "prompt_mode": "literal",
        "selection": {},
        "scan_options": {"recursive": True, "max_bytes": 32 * 1024 * 1024, "output_folder": ""},
    }


def validate_extensions(data: dict[str, Any]) -> None:
    validate_entry("stacks", {"blocks": data["workflow"]})
    validate_libraries(data["libraries"])
    validate_variables(data["variables"])
    if data["prompt_mode"] not in ("literal", "template"):
        raise ContractError("Prompt mode must be literal or template")
    _scan_options(data["scan_options"])
    _selection(data["selection"])


def _scan_options(value: Any) -> None:
    scan = require_fields(value, {"recursive", "max_bytes", "output_folder"}, "scan")
    require_integer(scan["max_bytes"], (1, 64 * 1024 * 1024), "source size limit")
    if type(scan["recursive"]) is not bool or not isinstance(scan["output_folder"], str):
        raise ContractError("Invalid scan options")
    if "\x00" in scan["output_folder"] or len(scan["output_folder"]) > 64000:
        raise ContractError("Invalid output folder text")


def _selection(selection: Any) -> None:
    if not isinstance(selection, dict) or len(selection) > 10000:
        raise ContractError("Invalid or oversized selection")
    for key, item in selection.items():
        require_fields(item, {"sha256", "decision"}, "selection item")
        if not isinstance(key, str) or not isinstance(item["sha256"], str):
            raise ContractError("Invalid source identity")
        if item["decision"] not in ("selected", "skipped", "review"):
            raise ContractError("Manual decisions cannot fabricate completion")


def upgrade_state(state: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(state)
    workspaces = [result["workspace"]]
    for entry in result["history"]:
        workspaces.extend((entry["before"], entry["after"]))
    for workspace in workspaces:
        for key, value in defaults().items():
            workspace.setdefault(key, value)
    return result
