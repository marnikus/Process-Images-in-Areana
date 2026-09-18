"""Dedicated recording QWebChannel adapter delegates without exposing artifacts."""

import json

import pytest

from app.ui.services.captcha_recordings_bridge import CaptchaRecordingsBridge


class Manager:
    def list_sessions(self, limit):
        return [{"session_id": "s1", "actor_label": "unknown", "limit": limit}]

    def set_label(self, session_id, label):
        if label == "bad":
            raise ValueError("bad label")
        return {"session_id": session_id, "actor_label": label}

    def set_result_label(self, session_id, label):
        if label == "bad":
            raise ValueError("bad result label")
        return {"session_id": session_id, "result_label": label}

    def get_session(self, session_id):
        return {"manifest": {"session_id": session_id}, "events": []}

    def session_folder(self, session_id):
        return f"/records/{session_id}"

    def delete_session(self, session_id):
        if session_id == "missing":
            raise FileNotFoundError("recording not found")


@pytest.mark.unit
def test_recordings_bridge_lists_and_labels():
    bridge = CaptchaRecordingsBridge(Manager())
    listed = json.loads(bridge.list_sessions(25))
    changed = json.loads(bridge.set_label("s1", "manual"))
    details = json.loads(bridge.get_session("s1"))
    assert listed["ok"] is True
    assert listed["total"] == 1
    assert listed["sessions"][0]["session_id"] == "s1"
    assert changed["ok"] and changed["session"]["actor_label"] == "manual"
    assert details["details"]["manifest"]["session_id"] == "s1"


@pytest.mark.unit
def test_recordings_bridge_opens_selected_session_folder():
    opened = []
    bridge = CaptchaRecordingsBridge(Manager(), opener=lambda path: opened.append(path) or True)
    result = json.loads(bridge.open_folder("s1"))
    assert result == {"ok": True, "path": "/records/s1"}
    assert opened == ["/records/s1"]


@pytest.mark.unit
def test_recordings_bridge_returns_error_envelope():
    bridge = CaptchaRecordingsBridge(Manager())
    result = json.loads(bridge.set_label("s1", "bad"))
    assert result["ok"] is False and "bad label" in result["error"]


@pytest.mark.unit
def test_recordings_bridge_delete_session():
    bridge = CaptchaRecordingsBridge(Manager())
    result = json.loads(bridge.delete_session("s1"))
    assert result == {"ok": True}
    error = json.loads(bridge.delete_session("missing"))
    assert error["ok"] is False


@pytest.mark.unit
def test_recordings_bridge_set_result_label():
    bridge = CaptchaRecordingsBridge(Manager())
    result = json.loads(bridge.set_result_label("s1", "passed"))
    assert result["ok"] is True
    assert result["session"]["result_label"] == "passed"
    error = json.loads(bridge.set_result_label("s1", "bad"))
    assert error["ok"] is False