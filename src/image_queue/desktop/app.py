"""Bootstrap the retained desktop workspace; native recovery choices precede any editing."""

import json
from pathlib import Path
from typing import cast

from platformdirs import user_data_path
from PySide6.QtWidgets import QApplication, QMessageBox

from image_queue.desktop.bridge import WorkspaceBridge
from image_queue.desktop.window import UI_PATH, WorkspaceWindow, start_worker
from image_queue.domain.validation import ContractError
from image_queue.persistence.store import SnapshotStore
from image_queue.workspace.history import initial_state
from image_queue.workspace.schema import default_workspace
from image_queue.workspace.service import WorkspaceService


def open_service(store: SnapshotStore) -> WorkspaceService:
    tree = json.loads((UI_PATH.parent / "default-tree.json").read_text(encoding="utf-8"))
    default = initial_state(default_workspace(tree))
    state = store.load(default)
    if not store.path.exists():
        store.save(state)
    return WorkspaceService(state, store)


def _recover(store: SnapshotStore) -> WorkspaceService:
    dialog = QMessageBox()
    dialog.setWindowTitle("Workspace recovery required")
    dialog.setText(
        "State could not be loaded. Restore the last valid backup? "
        "The current file will be preserved. No exits without changing files."
    )
    dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if dialog.exec() != QMessageBox.StandardButton.Yes:
        raise ContractError("Recovery declined; existing state left untouched")
    return WorkspaceService(store.recover_backup(), store)


def _show_error(message: str) -> None:
    dialog = QMessageBox()
    dialog.setWindowTitle("Cannot open workspace")
    dialog.setIcon(QMessageBox.Icon.Critical)
    dialog.setText(message)
    dialog.exec()


def launch(directory: Path | None = None) -> int:
    app = cast(QApplication, QApplication.instance() or QApplication([]))
    store = None
    try:
        store = SnapshotStore(directory or user_data_path("ImageQueue", appauthor=False))
        try:
            service = open_service(store)
        except (OSError, ContractError):
            service = _recover(store)
        return _run(app, service)
    except (OSError, ContractError) as exc:
        _show_error(str(exc))
        return 2
    finally:
        if store is not None:
            store.close()


def _run(app: QApplication, service: WorkspaceService) -> int:
    bridge = WorkspaceBridge(service)
    thread = start_worker(bridge)
    window = WorkspaceWindow(bridge, service.snapshot()["workspace"]["geometry"])
    window.show()
    try:
        return app.exec()
    finally:
        thread.quit()
        thread.wait()
