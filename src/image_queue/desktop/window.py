"""Retained QWebEngineView/QWebChannel shell with awaited close checkpoint and local-only page."""

import json
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, QUrl
from PySide6.QtGui import QCloseEvent
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMainWindow, QMessageBox

from image_queue.desktop.bridge import WorkspaceBridge
from image_queue.desktop.dialogs import DialogBridge

UI_PATH = Path(__file__).resolve().parents[1] / "ui" / "index.html"


class LocalPage(QWebEnginePage):
    """The privileged bridge must never be exposed to a remote or arbitrary local page."""

    def acceptNavigationRequest(
        self, url: QUrl | str, kind: QWebEnginePage.NavigationType, main: bool
    ) -> bool:
        target = QUrl(url)
        return main and target.isLocalFile() and Path(target.toLocalFile()).resolve() == UI_PATH


class WorkspaceWindow(QMainWindow):
    def __init__(self, bridge: WorkspaceBridge, geometry: list[int]) -> None:
        super().__init__()
        self.bridge = bridge
        self.loaded = False
        self.allow_close = False
        self.closing_pending = False
        self.close_timer = QTimer(self)
        self.close_timer.setSingleShot(True)
        self.close_timer.timeout.connect(self._close_timeout)
        self.setWindowTitle("Image Queue — Dark workspace")
        self.setMinimumSize(800, 600)
        self.resize(geometry[2], geometry[3])
        self.move(geometry[0], geometry[1])
        self.view = QWebEngineView(self)
        self.setCentralWidget(self.view)
        self._configure_page()
        bridge.loaded.connect(self._loaded)
        bridge.closing.connect(self._finish_close)
        self.view.load(QUrl.fromLocalFile(str(UI_PATH)))

    def _configure_page(self) -> None:
        self.profile = QWebEngineProfile(self)  # off-the-record: no second persistence authority
        page = LocalPage(self.profile, self.view)
        page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, False)
        page.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False
        )
        self.channel = QWebChannel(page)
        self.dialogs = DialogBridge(self)
        self.channel.registerObject("workspaceBridge", self.bridge)
        self.channel.registerObject("dialogBridge", self.dialogs)
        page.setWebChannel(self.channel)
        self.view.setPage(page)

    def _loaded(self) -> None:
        self.loaded = True

    def _finish_close(self) -> None:
        self.close_timer.stop()
        self.allow_close = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.allow_close or not self.loaded:
            event.accept()
            return
        event.ignore()
        if self.closing_pending:
            return
        if self.bridge.faulted:
            answer = QMessageBox.question(
                self,
                "Persistence fault",
                "Close and reopen to inspect saved state? Unacknowledged edits may be lost.",
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._finish_close()
            return
        self.closing_pending = True
        self.close_timer.start(8000)
        geometry = [self.x(), self.y(), self.width(), self.height()]
        self.view.page().runJavaScript(f"Workspace.close({json.dumps(geometry)})")

    def _close_timeout(self) -> None:
        self.closing_pending = False
        answer = QMessageBox.question(
            self,
            "No save acknowledgement",
            "Close anyway and inspect saved state on restart? "
            "Unacknowledged edits may be lost. Choose No to continue waiting/editing.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._finish_close()


def start_worker(bridge: WorkspaceBridge) -> QThread:
    thread = QThread()
    bridge.worker.moveToThread(thread)
    thread.finished.connect(bridge.worker.deleteLater)
    thread.start()
    return thread
