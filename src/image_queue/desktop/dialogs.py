"""Native dialogs stay on the UI thread, separate from the worker's command bridge."""

from pathlib import Path

from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import QFileDialog

from image_queue.persistence.export import save_library_file


class DialogBridge(QObject):
    @Slot(result=str)
    def choose_folder(self) -> str:
        return QFileDialog.getExistingDirectory(None, "Choose image root folder")

    @Slot(str, result=str)
    def save_library_file(self, text: str) -> str:
        path, _ = QFileDialog.getSaveFileName(
            None, "Save portable library backup", "", "JSON (*.json)"
        )
        if not path:
            return "Export cancelled"
        try:
            save_library_file(Path(path), text)
            return "Backup exported to a new file"
        except (OSError, ValueError):
            return (
                "Export failed; choose a new writable file (existing files are never overwritten)"
            )
