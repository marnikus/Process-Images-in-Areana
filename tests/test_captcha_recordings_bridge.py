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

    def set_labels(self, session_id, actor, result):
        return {"session_id": session_id, "actor_label": actor, "result_label": result}

    def get_session(self, session_id):
        return {"manifest": {"session_id": session_id}, "events": []}

    def compare_sessions(self, left, right):
        return {"left": left, "right": right, "first_divergence": {}}

    def session_folder(self, session_id):
        return f"/records/{session_id}"

    def delete_session(self, session_id):
        if session_id == "active":
            raise RuntimeError("recording is active")
        return session_id

    def delete_all_sessions(self):
        return {"deleted": 4, "skipped_active": 1}

    def undo_delete(self):
        return 4


@pytest.mark.unit
def test_recordings_bridge_lists_and_labels():
    bridge = CaptchaRecordingsBridge(Manager())
    listed = json.loads(bridge.list_sessions(25))
    all_sessions = json.loads(bridge.list_all_sessions())
    changed = json.loads(bridge.set_label("s1", "manual"))
    labels = json.loads(bridge.set_labels("s1", "mixed", "passed"))
    details = json.loads(bridge.get_session("s1"))
    comparison = json.loads(bridge.compare_sessions("s1", "s2"))
    assert listed == {"ok": True, "sessions": [{"session_id": "s1", "actor_label": "unknown", "limit": 25}]}
    assert all_sessions["sessions"][0]["limit"] is None
    assert changed["ok"] and changed["session"]["actor_label"] == "manual"
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
def test_recordings_bridge_removes_one_or_all_sessions():
    bridge = CaptchaRecordingsBridge(Manager())

    one = json.loads(bridge.delete_session("s1"))
    all_rows = json.loads(bridge.delete_all_sessions())
    undone = json.loads(bridge.undo_delete())
    active = json.loads(bridge.delete_session("active"))

    assert one == {"ok": True, "deleted": "s1"}
    assert all_rows == {"ok": True, "deleted": 4, "skipped_active": 1}
    assert undone == {"ok": True, "restored": 4}
    assert active["ok"] is False and "active" in active["error"]


@pytest.mark.unit
def test_recordings_bridge_returns_error_envelope():
    bridge = CaptchaRecordingsBridge(Manager())
    result = json.loads(bridge.set_label("s1", "bad"))
    assert result["ok"] is False and "bad label" in result["error"]
