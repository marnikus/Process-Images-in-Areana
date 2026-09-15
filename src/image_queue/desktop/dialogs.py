"""Native dialogs stay on the UI thread, separate from the worker's command bridge."""

from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import QFileDialog


class DialogBridge(QObject):
    @Slot(result=str)
    def choose_folder(self) -> str:
        return QFileDialog.getExistingDirectory(None, "Choose image root folder")
