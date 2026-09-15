"""Durable intent/evidence writes use the existing authoritative snapshot writer."""

from typing import Any

from image_queue.domain.validation import ContractError
from image_queue.workspace.execution import RELEASED, append_phase, empty_execution, phase
from image_queue.workspace.service import WorkspaceService


class AttemptLedger:
    def __init__(self, service: WorkspaceService) -> None:
        self.service = service

    def read(self) -> dict[str, Any]:
        return dict(self.service.snapshot()["jobs"].get("execution", empty_execution()))

    def attempt(self, identifier: str) -> dict[str, Any]:
        try:
            return dict(self.read()["attempts"][identifier])
        except KeyError as exc:
            raise ContractError("Unknown attempt") from exc

    def add(self, inputs: dict[str, Any], cursor: int) -> str:
        data = self.read()
        if data["stop_after"] or data["paused"] or self.unresolved():
            raise ContractError("Execution is stopped, paused or has unresolved work")
        identifier = inputs["id"]
        data["attempts"][identifier] = {
            "inputs": inputs,
            "events": [{"phase": "prepared", "code": "prepared", "evidence": {}}],
        }
        data["cursor"] = cursor
        self.service.record_execution(data)
        return str(identifier)

    def move(self, identifier: str, status: str, evidence: dict[str, str] | None = None) -> None:
        self.service.record_execution(append_phase(self.read(), identifier, status, evidence))

    def controls(self, paused: bool, stop_after: bool) -> None:
        data = self.read()
        data.update(paused=paused, stop_after=stop_after)
        self.service.record_execution(data)

    def unresolved(self) -> bool:
        return any(phase(item) not in RELEASED for item in self.read()["attempts"].values())

    def recover(self) -> None:
        """Explicit startup recovery: never calls an adapter or resumes a side effect."""
        uncertain = {"upload_intent", "prompt_intent", "submit_intent", "submitted", "save_intent"}
        for identifier, attempt in self.read()["attempts"].items():
            status = phase(attempt)
            if status in uncertain:
                self.move(identifier, "needs_review")
            elif status in ("prepared", "uploaded", "ready_to_submit"):
                self.move(identifier, "interrupted")
        self.service.busy = self.unresolved()
