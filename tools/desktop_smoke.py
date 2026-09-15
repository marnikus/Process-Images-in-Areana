"""Real Qt/WebEngine smoke checks. Requires desktop dependencies; never substitutes fake Qt."""

import tempfile
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from image_queue.desktop.app import _recover, _show_error, launch, open_service
from image_queue.desktop.bridge import WorkspaceBridge
from image_queue.desktop.dialogs import DialogBridge
from image_queue.desktop.window import WorkspaceWindow, start_worker
from image_queue.domain.validation import ContractError
from image_queue.persistence.store import SnapshotStore


def wait_signal(signal, action, timeout=20000):
    loop = QEventLoop()
    timed_out = []
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(lambda: (timed_out.append(True), loop.quit()))
    signal.connect(loop.quit)
    timer.start(timeout)
    action()
    loop.exec()
    timer.stop()
    signal.disconnect(loop.quit)
    assert not timed_out, "Desktop signal timeout: real page/channel did not complete"


def evaluate(window, script):
    loop = QEventLoop()
    result = []
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(20000)
    window.view.page().runJavaScript(script, lambda value: (result.append(value), loop.quit()))
    loop.exec()
    timer.stop()
    assert result, "JavaScript callback timeout"
    return result[0]


def action(window, bridge, expression):
    script = (
        f"Promise.resolve({expression}).then(()=>Workspace.bridge.ready(), "
        "e=>{window.smokeError=String(e);Workspace.bridge.ready();})"
    )
    wait_signal(bridge.loaded, lambda: window.view.page().runJavaScript(script))
    assert not evaluate(window, "window.smokeError || ''")


def auto_dialog(button):
    def accept():
        widget = QApplication.activeModalWidget()
        if isinstance(widget, QMessageBox):
            widget.done(button)
        elif isinstance(widget, QFileDialog):
            widget.reject()

    QTimer.singleShot(100, accept)


def exercise(directory):
    store = SnapshotStore(directory)
    service = open_service(store)
    bridge = WorkspaceBridge(service)
    thread = start_worker(bridge)
    window = WorkspaceWindow(bridge, service.snapshot()["workspace"]["geometry"])
    window.show()
    try:
        if not window.loaded:
            wait_signal(bridge.loaded, lambda: None)
        assert evaluate(window, "document.querySelectorAll('.panel').length") == 14
        assert evaluate(window, "SashCore.validate(SashGrid.root)") is None
        assert evaluate(window, "document.getElementById('startBtn').disabled") is True
        assert not window.view.page().acceptNavigationRequest(
            QUrl("https://example.org"), QWebEnginePage.NavigationType.NavigationTypeOther, True
        )
        evaluate(
            window,
            "document.getElementById('prompt').value='Qt persisted prompt';"
            "Workspace.dirty=true;Workspace.label='Prompt edit'",
        )
        action(window, bridge, "Workspace.flush()")
        action(
            window, bridge, "(SashGrid.simulateDrop('composer','people','right'),Workspace.flush())"
        )
        assert evaluate(window, "Workspace.state.history.length") == 2
        action(window, bridge, "Workspace.travel('undo')")
        action(window, bridge, "Workspace.travel('undo')")
        assert evaluate(window, "document.getElementById('prompt').value") == ""
        action(window, bridge, "Workspace.travel('redo')")
        action(
            window,
            bridge,
            "(document.getElementById('chromePort').value='0',Workspace.dirty=true,Workspace.flush())",
        )
        assert evaluate(window, "document.getElementById('chromePort').value") == "9222"
        assert (
            evaluate(window, "document.getElementById('saveStatus').classList.contains('error')")
            is True
        )
        action(
            window,
            bridge,
            "(document.getElementById('layoutName').value='Qt desk',Workspace.saveLayout())",
        )
        assert evaluate(window, "Object.keys(Workspace.state.workspace.layouts).length") == 1
        Path("coverage").mkdir(exist_ok=True)
        assert window.grab().save("coverage/workspace.png")
        # Native close requests an awaited JS flush then emits readiness from the worker.
        wait_signal(bridge.closing, window.close)
        assert window.allow_close
    finally:
        window.allow_close = True
        window.close()
        thread.quit()
        thread.wait()
        store.close()
    reopened = SnapshotStore(directory)
    try:
        restored = open_service(reopened).snapshot()
        assert restored["workspace"]["prompt"] == "Qt persisted prompt"
        assert "Qt desk" in restored["workspace"]["layouts"]
        # Worker and malformed-command behavior is covered by the real Qt channel tests.
        auto_dialog(QMessageBox.StandardButton.Ok)
        _show_error("Test error: intentionally dismissed")
        auto_dialog(QMessageBox.StandardButton.No)
        try:
            _recover(reopened)
        except ContractError:
            pass
        else:
            raise AssertionError("Declined recovery must not continue")
        auto_dialog(QMessageBox.StandardButton.Yes)
        assert _recover(reopened).snapshot()["version"] == 1
        auto_dialog(QMessageBox.StandardButton.Cancel)
        assert DialogBridge().choose_folder() == ""
    finally:
        reopened.close()


def launch_smoke(app, directory):
    app.setQuitOnLastWindowClosed(True)

    def close_when_ready():
        for widget in app.topLevelWidgets():
            if isinstance(widget, WorkspaceWindow) and widget.isVisible() and widget.loaded:
                widget.close()
                return
        QTimer.singleShot(50, close_when_ready)

    QTimer.singleShot(50, close_when_ready)
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(lambda: app.exit(9))
    timeout.start(20000)
    assert launch(directory) == 0
    timeout.stop()
    locked = SnapshotStore(directory)
    try:
        auto_dialog(QMessageBox.StandardButton.Ok)
        assert launch(directory) == 2
    finally:
        locked.close()


if __name__ == "__main__":
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    with tempfile.TemporaryDirectory(prefix="image-queue-qt-") as temporary:
        exercise(Path(temporary))
        launch_smoke(app, Path(temporary))
    print("PASS: real Qt/WebEngine + WebChannel + durable workspace and native recovery dialogs")
