"""Dedicated recording QWebChannel adapter delegates without exposing artifacts."""

import json

import pytest

from app.ui.services.captcha_recordings_bridge import CaptchaRecordingsBridge


class Manager:
    def __init__(self):
        self.enabled = True

    def list_sessions(self, limit):
        return [{"session_id": "s1", "actor_label": "unknown", "limit": limit}]

    def count_sessions(self):
        return 1

    def set_labels(self, session_id, actor, result):
        if actor == "bad":
            raise ValueError("bad label")
        return {"session_id": session_id, "actor_label": actor, "result_label": result}

    def get_session(self, session_id):
        return {"manifest": {"session_id": session_id}, "events": []}

    def delete_session(self, session_id):
        if session_id != "s1":
            raise FileNotFoundError("recording not found")
        return {"session_id": session_id, "deleted": True}

    def compare_sessions(self, left_id, right_id):
        return {"left": left_id, "right": right_id, "events": []}

    def session_folder(self, session_id):
        return f"/records/{session_id}"

    def is_enabled(self):
        return self.enabled

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        return self.enabled


@pytest.mark.unit
def test_recordings_bridge_lists_all_with_total_and_labels():
    bridge = CaptchaRecordingsBridge(Manager())
    listed = json.loads(bridge.list_sessions(25))
    labels = json.loads(bridge.set_labels("s1", "mixed", "passed"))
    details = json.loads(bridge.get_session("s1"))
    comparison = json.loads(bridge.compare_sessions("s1", "s2"))
    assert listed == {"ok": True, "total": 1,
                      "sessions": [{"session_id": "s1", "actor_label": "unknown", "limit": 25}]}
    assert labels["ok"] and labels["session"]["actor_label"] == "mixed"
    assert labels["session"]["result_label"] == "passed"
    assert comparison["comparison"]["right"] == "s2"
    assert details["details"]["manifest"]["session_id"] == "s1"


@pytest.mark.unit
def test_recordings_bridge_opens_selected_session_folder():
    opened = []
    bridge = CaptchaRecordingsBridge(Manager(), opener=lambda path: opened.append(path) or True)
    result = json.loads(bridge.open_folder("s1"))
    assert result == {"ok": True, "path": "/records/s1"}
    assert opened == ["/records/s1"]


@pytest.mark.unit
def test_recordings_bridge_delete_session():
    bridge = CaptchaRecordingsBridge(Manager())
    deleted = json.loads(bridge.delete_session("s1"))
    assert deleted == {"ok": True, "session": {"session_id": "s1", "deleted": True}}
    missing = json.loads(bridge.delete_session("nope"))
    assert missing["ok"] is False and "not found" in missing["error"]


@pytest.mark.unit
def test_recordings_bridge_returns_error_envelope():
    bridge = CaptchaRecordingsBridge(Manager())
    result = json.loads(bridge.set_labels("s1", "bad", "passed"))
    assert result["ok"] is False and "bad label" in result["error"]


@pytest.mark.unit
def test_recordings_bridge_toggle_roundtrip():
    manager = Manager()
    bridge = CaptchaRecordingsBridge(manager)
    assert json.loads(bridge.recording_enabled()) == {"ok": True, "enabled": True}
    assert json.loads(bridge.set_recording_enabled(False)) == {"ok": True, "enabled": False}
    assert manager.enabled is False
    assert json.loads(bridge.recording_enabled()) == {"ok": True, "enabled": False}


@pytest.mark.unit
def test_recordings_bridge_reports_opener_failure():
    """A refused folder open is an error envelope, not a silent ok."""
    bridge = CaptchaRecordingsBridge(Manager(), opener=lambda path: False)
    assert json.loads(bridge.open_folder("s1")) == {
        "ok": False, "error": "operating system did not open the folder"}


@pytest.mark.unit
def test_recordings_bridge_degrades_to_error_envelope():
    class Broken(Manager):
        def list_sessions(self, limit):
            raise RuntimeError("store gone")

    assert json.loads(CaptchaRecordingsBridge(Broken()).list_sessions(5)) == {
        "ok": False, "error": "store gone"}


@pytest.mark.unit
def test_open_local_folder_needs_a_desktop(monkeypatch):
    import app.ui.services.captcha_recordings_bridge as bridge_mod
    monkeypatch.setattr(bridge_mod, "QDesktopServices", None)
    monkeypatch.setattr(bridge_mod, "QUrl", None)
    with pytest.raises(RuntimeError):
        bridge_mod._open_local_folder("/records/s1")
