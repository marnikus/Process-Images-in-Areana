"""Recording history removal keeps active writers safe."""

from types import SimpleNamespace

import pytest

from app.services.captcha_recording.manager import RecordingManager


def encounter(tab):
    return {"eid": tab, "tab": tab, "source": "test", "url": "https://arena.ai/c/1",
            "kind": "recaptcha_enterprise"}


@pytest.mark.unit
def test_manager_refuses_active_recording_removal(tmp_path):
    manager = RecordingManager(tmp_path)
    manifest = manager.store.create(encounter("active-tab"))
    manager._active["active-tab"] = SimpleNamespace(session_id=manifest["session_id"])

    with pytest.raises(RuntimeError, match="active"):
        manager.delete_session(manifest["session_id"])

    assert manager.store.list_sessions(limit=None)[0]["session_id"] == manifest["session_id"]


@pytest.mark.unit
def test_manager_removes_all_inactive_and_reports_active_skip(tmp_path):
    manager = RecordingManager(tmp_path)
    active = manager.store.create(encounter("active-tab"))["session_id"]
    manager.store.create(encounter("done-1"))
    manager.store.create(encounter("done-2"))
    manager._active["active-tab"] = SimpleNamespace(session_id=active)

    result = manager.delete_all_sessions()

    assert result == {"deleted": 2, "skipped_active": 1}
    assert [row["session_id"] for row in manager.list_sessions(limit=None)] == [active]
