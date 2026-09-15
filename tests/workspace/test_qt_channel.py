"""REAL Qt/WebChannel invocation across a worker thread; no fake QObject or success stubs.

A transport test double replaces WebEngine's JS wire, not Qt/service/storage behavior.
This does not claim native widget rendering has been validated on this machine.
"""

import json
from copy import deepcopy

from PySide6.QtCore import QCoreApplication, QEventLoop, QThread, QTimer
from PySide6.QtWebChannel import QWebChannel, QWebChannelAbstractTransport

from image_queue.desktop.bridge import WorkspaceBridge
from image_queue.domain.validation import PersistenceFault
from image_queue.persistence.store import SnapshotStore
from image_queue.workspace.service import WorkspaceService


class Transport(QWebChannelAbstractTransport):
    def __init__(self):
        super().__init__()
        self.messages = []

    def sendMessage(self, message):
        self.messages.append(message)


def exchange(transport, message):
    loop = QEventLoop()
    timer = QTimer()
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    timer.timeout.connect(
        lambda: loop.quit()
        if any(item.get("id") == message["id"] for item in transport.messages)
        else None
    )
    timer.start(5)
    timeout.start(5000)
    transport.messageReceived.emit(message, transport)
    loop.exec()
    timer.stop()
    timeout.stop()
    replies = [item for item in transport.messages if item.get("id") == message["id"]]
    assert replies, "Real Qt channel timed out"
    return replies[-1]["data"]


def invoke(transport, raw, identifier):
    loop = QEventLoop()
    timer = QTimer()
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)

    def matching():
        return [
            item
            for item in transport.messages
            if item.get("type") == 1 and item.get("args", [None])[0] == str(identifier)
        ]

    timer.timeout.connect(lambda: loop.quit() if matching() else None)
    timer.start(5)
    deadline.start(5000)
    transport.messageReceived.emit(
        {
            "type": 6,
            "id": identifier,
            "object": "workspaceBridge",
            "method": "command",
            "args": [str(identifier), raw],
        },
        transport,
    )
    loop.exec()
    timer.stop()
    deadline.stop()
    assert matching(), "Worker completion signal not received"
    return json.loads(matching()[-1]["args"][1])


def test_real_channel_worker_persists_and_reports_failures(tmp_path, state, monkeypatch):
    app = QCoreApplication.instance() or QCoreApplication([])
    store = SnapshotStore(tmp_path)
    service = WorkspaceService(state, store)
    bridge = WorkspaceBridge(service)
    thread = QThread()
    bridge.worker.moveToThread(thread)
    thread.finished.connect(bridge.worker.deleteLater)
    thread.start()
    channel = QWebChannel()
    channel.registerObject("workspaceBridge", bridge)
    transport = Transport()
    channel.connectTo(transport)
    try:
        init = exchange(transport, {"type": 3, "id": 1})
        assert "workspaceBridge" in init
        read = exchange(
            transport,
            {"type": 6, "id": 2, "object": "workspaceBridge", "method": "read", "args": []},
        )
        assert json.loads(read)["state"] == state
        signal_id = next(
            index for name, index in init["workspaceBridge"]["signals"] if name == "completed"
        )
        transport.messageReceived.emit(
            {"type": 7, "object": "workspaceBridge", "signal": signal_id}, transport
        )
        workspace = deepcopy(state["workspace"])
        workspace["prompt"] = "Qt worker saved this"
        command = {"kind": "edit", "revision": 0, "workspace": workspace, "label": "Prompt"}
        result = invoke(transport, json.dumps(command), 3)
        assert result["ok"] is True
        assert store.load(state)["workspace"]["prompt"] == "Qt worker saved this"
        result = invoke(transport, json.dumps(command), 4)
        assert result["ok"] is False and not result["faulted"]
        for index, raw in enumerate(["[]", "bad json", "x" * 2_000_001], start=5):
            assert not invoke(transport, raw, index)["ok"]

        def failed_save(_state):
            raise PersistenceFault("Saving failed; simulated disk unavailable")

        monkeypatch.setattr(store, "save", failed_save)
        result = invoke(transport, json.dumps({"kind": "undo", "revision": 1}), 8)
        assert not result["ok"] and result["faulted"]
        assert service.snapshot()["revision"] == 1
        assert not invoke(transport, json.dumps(command), 9)["ok"]
    finally:
        channel.disconnectFrom(transport)
        thread.quit()
        assert thread.wait(5000)
        store.close()
        app.processEvents()
