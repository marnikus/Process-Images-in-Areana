"""Adapt legacy global before/after timeline semantics; immutable snapshots, no DB-world undo."""

from copy import deepcopy
from typing import Any

from image_queue.domain.validation import ContractError, require_fields, require_integer
from image_queue.workspace.schema import validate_workspace

MAX_HISTORY = 100


def initial_state(workspace: dict[str, Any]) -> dict[str, Any]:
    validate_workspace(workspace)
    return {
        "version": 1,
        "revision": 0,
        "workspace": deepcopy(workspace),
        "history": [],
        "cursor": -1,
        "jobs": {},
    }


def validate_state(state: Any) -> None:
    data = require_fields(
        state, {"version", "revision", "workspace", "history", "cursor", "jobs"}, "state"
    )
    require_integer(data["version"], (1, 1), "state version")
    require_integer(data["revision"], (0, 2**53 - 1), "revision")
    validate_workspace(data["workspace"])
    if not isinstance(data["jobs"], dict):
        raise ContractError("jobs: expected object")
    entries = data["history"]
    if not isinstance(entries, list) or len(entries) > MAX_HISTORY:
        raise ContractError("history: invalid or oversized timeline")
    cursor = require_integer(data["cursor"], (-1, len(entries) - 1), "cursor")
    _validate_chain(entries)
    if entries:
        expected = entries[cursor]["after"] if cursor >= 0 else entries[0]["before"]
        if expected != data["workspace"]:
            raise ContractError("history: cursor and editable workspace disagree")


def _validate_chain(entries: list[Any]) -> None:
    previous = None
    for entry in entries:
        data = require_fields(entry, {"label", "before", "after"}, "history entry")
        label = data["label"]
        if not isinstance(label, str) or not label.strip() or len(label) > 100:
            raise ContractError("history: invalid label")
        validate_workspace(data["before"])
        validate_workspace(data["after"])
        if previous is not None and previous != data["before"]:
            raise ContractError("history: discontinuous timeline")
        previous = data["after"]


def edit_state(state: dict[str, Any], workspace: dict[str, Any], label: str) -> dict[str, Any]:
    validate_state(state)
    validate_workspace(workspace)
    result = deepcopy(state)
    if workspace == state["workspace"]:
        return result
    entry = {"label": label, "before": deepcopy(state["workspace"]), "after": deepcopy(workspace)}
    history = [*result["history"][: result["cursor"] + 1], entry][-MAX_HISTORY:]
    result.update(workspace=deepcopy(workspace), history=history, cursor=len(history) - 1)
    result["revision"] += 1
    validate_state(result)
    return result


def travel(state: dict[str, Any], direction: str) -> dict[str, Any]:
    validate_state(state)
    if direction not in ("undo", "redo"):
        raise ContractError("history: unknown direction")
    result = deepcopy(state)
    cursor = state["cursor"]
    index = cursor if direction == "undo" else cursor + 1
    if not 0 <= index < len(state["history"]):
        return result
    key = "before" if direction == "undo" else "after"
    result["workspace"] = deepcopy(state["history"][index][key])
    result["cursor"] += -1 if direction == "undo" else 1
    result["revision"] += 1
    validate_state(result)
    return result
