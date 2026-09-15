"""UI-thread WebChannel facade; request-ID signals avoid queued-slot return-value deadlocks."""

import json
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from image_queue.domain.validation import ContractError, PersistenceFault
from image_queue.operations import Operations
from image_queue.workspace.library_io import unique_keys
from image_queue.workspace.service import WorkspaceService


class CommandWorker(QObject):
    completed = Signal(str, str)

    def __init__(self, service: WorkspaceService) -> None:
        super().__init__()
        self.service = service
        self.operations = Operations(service)
        self.faulted = False

    @Slot(str, str)
    def execute(self, request_id: str, raw: str) -> None:
        try:
            if len(raw) > 2_000_000 or self.faulted:
                raise ContractError("Request too large or persistence locked; reopen workspace")
            command: Any = json.loads(raw, object_pairs_hook=unique_keys)
            if not isinstance(command, dict):
                raise ContractError("Workspace command must be an object")
            response = {"ok": True, **self.operations.execute(command)}
        except (ValueError, OSError, RecursionError, KeyError, TypeError) as exc:
            message = str(exc) if isinstance(exc, ContractError) else "Workspace command failed"
            self.faulted = isinstance(exc, PersistenceFault) or self.faulted
            response = {"ok": False, "error": message, "faulted": self.faulted}
        self.completed.emit(request_id, json.dumps(response))


class WorkspaceBridge(QObject):
    loaded = Signal()
    closing = Signal()
    requested = Signal(str, str)
    completed = Signal(str, str)

    def __init__(self, service: WorkspaceService) -> None:
        super().__init__()
        self.worker = CommandWorker(service)
        self.cache = service.snapshot()
        self.faulted = False
        self.requested.connect(self.worker.execute)
        self.worker.completed.connect(self._complete)

    @Slot(result=str)
    def read(self) -> str:
        return json.dumps({"ok": True, "state": self.cache})

    @Slot(str, str)
    def command(self, request_id: str, raw: str) -> None:
        self.requested.emit(request_id, raw)

    @Slot(str, str)
    def _complete(self, request_id: str, raw: str) -> None:
        response = json.loads(raw)
        if response["ok"]:
            self.cache = response["state"]
        self.faulted = response.get("faulted", False) or self.faulted
        self.completed.emit(request_id, raw)

    @Slot()
    def ready(self) -> None:
        self.loaded.emit()

    @Slot()
    def ready_to_close(self) -> None:
        self.closing.emit()
