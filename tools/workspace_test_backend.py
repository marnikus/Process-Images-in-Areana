"""JSON-lines test harness for the REAL workspace service; never shipped as an app server."""

import json
import sys
from pathlib import Path

from image_queue.operations import Operations
from image_queue.persistence.store import SnapshotStore
from image_queue.workspace.history import initial_state
from image_queue.workspace.schema import default_workspace
from image_queue.workspace.service import WorkspaceService

root = Path(__file__).resolve().parents[1]
tree = json.loads((root / "src/image_queue/ui/default-tree.json").read_text())
store = SnapshotStore(Path(sys.argv[1]))
service = WorkspaceService(store.load(initial_state(default_workspace(tree))), store)
operations = Operations(service)
try:
    for line in sys.stdin:
        try:
            request = json.loads(line)
            response = (
                {"state": service.snapshot()}
                if request == {"kind": "read"}
                else operations.execute(request)
            )
            print(json.dumps({"ok": True, **response}), flush=True)
        except ValueError as exc:
            print(json.dumps({"ok": False, "error": str(exc), "faulted": store.failed}), flush=True)
finally:
    operations.close()
    store.close()
