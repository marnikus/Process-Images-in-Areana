"""Single-writer commands: compute -> validate -> persist -> publish, never UI-owned history."""

from copy import deepcopy
from typing import Any, Protocol

from image_queue.domain.validation import ContractError
from image_queue.workspace.history import edit_state, travel, validate_state


class StateWriter(Protocol):
    def save(self, state: dict[str, Any]) -> None: ...


class WorkspaceService:
    def __init__(self, state: dict[str, Any], writer: StateWriter) -> None:
        validate_state(state)
        self._state = deepcopy(state)
        self._writer = writer
        self.busy = False

    def snapshot(self) -> dict[str, Any]:
        return deepcopy(self._state)

    def execute(self, command: dict[str, Any]) -> dict[str, Any]:
        if self.busy:
            raise ContractError("Active job owns configuration; editing and undo are locked")
        if (
            type(command.get("revision")) is not int
            or command["revision"] != self._state["revision"]
        ):
            raise ContractError("Stale workspace revision; reload before editing")
        candidate = self._candidate(command)
        if candidate != self._state:
            self._writer.save(candidate)
            self._state = candidate
        return self.snapshot()

    def _candidate(self, command: dict[str, Any]) -> dict[str, Any]:
        kind = command.get("kind")
        if kind in ("undo", "redo") and set(command) == {"kind", "revision"}:
            return travel(self._state, kind)
        if kind == "edit" and set(command) == {"kind", "revision", "workspace", "label"}:
            return edit_state(self._state, command["workspace"], command["label"])
        raise ContractError("Unknown workspace command; jobs cannot be edited or undone")
