"""Worker-owned application commands join libraries, scanner and CDP to one state writer."""

from copy import deepcopy
from typing import Any

from image_queue.browser.controller import ChromeController
from image_queue.domain.validation import ContractError, require_fields
from image_queue.scanning.scanner import FolderScanner, reconcile
from image_queue.workspace.libraries import change_library
from image_queue.workspace.library_io import (
    export_workspace_libraries,
    merge_import,
    preview_import,
)
from image_queue.workspace.queue import queue_rows, select_sources
from image_queue.workspace.service import WorkspaceService
from image_queue.workspace.variables import render_prompt


class Operations:
    def __init__(self, service: WorkspaceService) -> None:
        self.service = service
        self.chrome: ChromeController | None = None

    def execute(self, command: dict[str, Any]) -> dict[str, Any]:
        validate_command(command)
        state = self.service.snapshot()
        if command.get("kind") in ("edit", "undo", "redo"):
            return {"state": self.service.execute(command)}
        if (
            self.service.busy
            or type(command.get("revision")) is not int
            or command["revision"] != state["revision"]
        ):
            raise ContractError("Active job or stale revision; command refused")
        result = self._operation(command, state)
        return {"state": self.service.snapshot(), "result": result}

    def _operation(self, command: dict[str, Any], state: dict[str, Any]) -> Any:
        kind = command.get("kind")
        workspace = deepcopy(state["workspace"])
        if isinstance(kind, str) and kind.startswith("chrome_"):
            return self._chrome(command, workspace["connection"])
        if kind == "scan":
            require_fields(command, {"kind", "revision"}, "scan request")
            scanned = FolderScanner().scan(workspace["folder"], workspace["scan_options"])
            sources = reconcile(state["jobs"].get("sources", {}), scanned)
            return self.service.record_sources(sources, state["revision"])["revision"]
        if kind == "queue":
            return queue_rows(state["jobs"].get("sources", {}), workspace["selection"])
        if kind in ("library_preview", "library_export", "prompt_preview"):
            return self._preview(command, workspace)
        workspace = self._edit(command, workspace, state)
        self.service.execute(
            {
                "kind": "edit",
                "revision": state["revision"],
                "workspace": workspace,
                "label": "Library / selection change",
            }
        )
        return None

    def _edit(
        self, command: dict[str, Any], workspace: dict[str, Any], state: dict[str, Any]
    ) -> dict[str, Any]:
        kind = command.get("kind")
        if kind == "library_change":
            workspace["libraries"] = change_library(workspace["libraries"], command["change"])
        elif kind == "library_import":
            preview = preview_import(command["text"])
            if command.get("sha256") != preview["sha256"]:
                raise ContractError("Import differs from the reviewed preview")
            workspace["libraries"] = merge_import(workspace["libraries"], preview["libraries"])
        elif kind == "select":
            workspace = select_sources(workspace, state["jobs"].get("sources", {}), command)
        else:
            raise ContractError("Unknown application command")
        return workspace

    def _preview(self, command: dict[str, Any], workspace: dict[str, Any]) -> Any:
        kind = command["kind"]
        if kind == "library_preview":
            return preview_import(command["text"])
        if kind == "library_export":
            return export_workspace_libraries(workspace)
        return render_prompt(workspace["prompt"], workspace["variables"], workspace["prompt_mode"])

    def _chrome(self, command: dict[str, Any], connection: str) -> Any:
        fields = {"kind", "revision"}
        if command["kind"] == "chrome_check":
            fields |= {"row_id", "target_id"}
        require_fields(command, fields, "Chrome request")
        if self.chrome is None:
            self.chrome = ChromeController()
        return self.chrome.execute(command, connection)

    def close(self) -> None:
        if self.chrome is not None:
            self.chrome.close()


def validate_command(command: dict[str, Any]) -> None:
    fields = {
        "edit": {"workspace", "label"},
        "undo": set(),
        "redo": set(),
        "scan": set(),
        "queue": set(),
        "prompt_preview": set(),
        "library_preview": {"text"},
        "library_export": set(),
        "library_import": {"text", "sha256"},
        "library_change": {"change"},
        "select": {"ids", "decision"},
        "chrome_discover": set(),
        "chrome_status": set(),
        "chrome_disconnect": set(),
        "chrome_check": {"row_id", "target_id"},
    }
    kind = command.get("kind")
    if not isinstance(kind, str) or kind not in fields:
        raise ContractError("Unknown application command")
    require_fields(command, {"kind", "revision"} | fields[kind], "application command")
