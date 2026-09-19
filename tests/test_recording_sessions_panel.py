"""Session-recordings panel: the 8 WebChannel slots delegate to the payloads.

The slots are thin on purpose (parse -> payloads -> JSON), so these tests pin the
envelope contract and the degrade-to-error-reply rule rather than store internals:
a JS caller must always get JSON back, even when the service or the argument is
broken.
"""

import json

import pytest

from app.ui.panels.recording_sessions import RecordingSessionsMixin


class StubStore:
    root = "/tmp/recordings"

    def __init__(self):
        self.label = ("", "")
        self.deleted = ""

    def list_sessions(self):
        return [{"id": "s1", "label": "unknown"}], ["broken-dir"]

    def load_events(self, session_id, limit):
        return [{"seq": 0, "kind": "state", "session_id": session_id, "limit": limit}]

    def load_snapshot(self, session_id, name):
        return f"<html data-session='{session_id}' data-name='{name}'/>"

    def set_label(self, session_id, label):
        self.label = (session_id, label)
        return (True, label) if label else (False, "empty label")

    def delete(self, session_id):
        self.deleted = session_id
        return session_id == "s1"


class StubService:
    def __init__(self):
        self.store = StubStore()
        self._active = {}
        self._enabled = True

    def enabled(self):
        return self._enabled

    def set_enabled(self, on):
        self._enabled = bool(on)


class Panel(RecordingSessionsMixin):
    def __init__(self, svc=None):
        self.logs = []
        self._recording_service_obj = svc or StubService()

    def _log(self, message, level="info"):
        self.logs.append((level, message))


def test_list_detail_label_delete_round_trip():
    panel = Panel()
    listed = json.loads(panel.get_recordings_list())
    assert listed["ok"] and listed["enabled"] is True
    assert listed["skipped"] == ["broken-dir"]
    detail = json.loads(panel.get_recording_detail(json.dumps({"session_id": "s1",
                                                              "event_limit": 5})))
    assert detail["session"]["id"] == "s1" and detail["events"][0]["limit"] == 5
    assert json.loads(panel.get_recording_detail('{"session_id": "nope"}')) == \
        {"ok": False, "error": "unknown session"}
    labelled = json.loads(panel.set_recording_label('{"session_id": "s1", "label": "manual"}'))
    assert labelled == {"ok": True, "label": "manual"}
    assert panel._recording_service_obj.store.label == ("s1", "manual")
    assert any("recording label set" in message for _, message in panel.logs)
    deleted = json.loads(panel.delete_recording('{"session_id": "s1"}'))
    assert deleted == {"ok": True}
    assert json.loads(panel.delete_recording('{"session_id": "s9"}'))["ok"] is False


def test_snapshots_diff_and_settings():
    panel = Panel()
    store = panel._recording_service_obj.store
    store.load_snapshot = lambda session_id, name: f"<html>{name}</html>\n"
    spec = {"session_a": "s1", "name_a": "a", "session_b": "s1", "name_b": "b"}
    assert json.loads(panel.get_recording_snapshot('{"session_id": "s1", "name": "a"}'))["ok"]
    diff = json.loads(panel.get_recording_diff(json.dumps(spec)))
    assert diff["ok"] and diff["total"] >= 1 and diff["lines"]
    settings = json.loads(panel.get_recording_settings())
    assert settings == {"ok": True, "enabled": True, "root": "/tmp/recordings"}
    assert json.loads(panel.set_recording_settings('{"enabled": false}')) == \
        {"ok": True, "enabled": False}
    assert panel._recording_service_obj.enabled() is False


@pytest.mark.parametrize("call", [
    lambda p: p.get_recording_detail("{not json"),
    lambda p: p.get_recording_snapshot("{not json"),
    lambda p: p.get_recording_diff("{not json"),
    lambda p: p.set_recording_label("{not json"),
    lambda p: p.delete_recording("{not json"),
    lambda p: p.set_recording_settings("{not json"),
])
def test_bad_payload_degrades_to_error_reply(call):
    reply = json.loads(call(Panel()))
    assert reply["ok"] is False and reply["error"]


def test_lazy_service_is_created_once(monkeypatch):
    import app.services.recording.recorder as recorder

    created = []

    def factory(root, log):
        created.append(root)
        return StubService()

    monkeypatch.setattr(recorder, "RecordingService", factory)
    panel = Panel.__new__(Panel)  # no pre-wired service: exercise the lazy getter
    panel.logs = []
    panel._log = lambda message, level="info": panel.logs.append((level, message))
    assert json.loads(panel.get_recording_settings())["ok"]
    assert created == ["logs/recordings"]
    assert panel._recording_service() is panel._recording_service_obj
