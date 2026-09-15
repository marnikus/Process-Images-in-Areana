import json

import pytest

from image_queue.domain.validation import ContractError
from image_queue.operations import Operations
from image_queue.persistence.store import SnapshotStore
from image_queue.workspace.libraries import empty_libraries
from image_queue.workspace.library_io import export_libraries
from image_queue.workspace.service import WorkspaceService


def test_library_operations_preview_import_failure_undo(tmp_path, state):
    store = SnapshotStore(tmp_path)
    service = WorkspaceService(state, store)
    ops = Operations(service)

    def execute(kind, **kwargs):
        return ops.execute({"kind": kind, "revision": service.snapshot()["revision"], **kwargs})

    try:
        libraries = empty_libraries()
        libraries["templates"]["Imported"] = {"body": "raw\r\n{x}"}
        text = export_libraries(libraries)
        preview = execute("library_preview", text=text)["result"]
        assert service.snapshot() == state
        with pytest.raises(ContractError):
            execute("library_import", text=text, sha256="wrong")
        assert service.snapshot() == state
        execute("library_import", text=text, sha256=preview["sha256"])
        imported = service.snapshot()
        assert json.loads(execute("library_export")["result"])["libraries"] == libraries
        with pytest.raises(ContractError):
            execute("library_import", text=text, sha256=preview["sha256"])
        assert service.snapshot() == imported
        execute("undo")
        assert service.snapshot()["workspace"]["libraries"] == empty_libraries()
        execute("redo")
        assert service.snapshot()["workspace"]["libraries"] == libraries
        execute(
            "library_change",
            change={
                "family": "templates",
                "name": "Imported",
                "value": {"body": "edited"},
                "operation": "update",
            },
        )
        assert (
            service.snapshot()["workspace"]["libraries"]["templates"]["Imported"]["body"]
            == "edited"
        )
        assert execute("prompt_preview")["result"]["text"] == ""
        for command in [
            {"kind": "invalid", "revision": service.snapshot()["revision"]},
            {"kind": "queue", "revision": -1},
            {"kind": "queue", "revision": False},
        ]:
            with pytest.raises(ContractError):
                ops.execute(command)
        assert "libraries" in service.snapshot()["history"][-1]["after"]
    finally:
        ops.close()
        store.close()
