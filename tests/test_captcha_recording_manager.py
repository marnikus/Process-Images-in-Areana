"""Recording history removal keeps active writers safe (catalog surface)."""

from types import SimpleNamespace

import pytest

from app.services.captcha_recording.manager import RecordingManager


def encounter(tab):
    return {"eid": tab, "tab": tab, "source": "test", "url": "https://arena.ai/c/1",
            "kind": "recaptcha_enterprise"}


@pytest.mark.unit
def test_catalog_refuses_active_recording_removal(tmp_path):
    manager = RecordingManager(str(tmp_path))
    manifest = manager.store.create(encounter("active-tab"))
    manager._active["active-tab"] = SimpleNamespace(session_id=manifest["session_id"])

    with pytest.raises(RuntimeError, match="active"):
        manager.catalog.delete_session(manifest["session_id"])

    assert manager.store.list_sessions(limit=None)[0]["session_id"] == manifest["session_id"]
    assert manager.catalog.undo_delete() == 0


@pytest.mark.unit
def test_catalog_removes_and_restores_one_recording(tmp_path):
    manager = RecordingManager(str(tmp_path))
    session_id = manager.store.create(encounter("done"))["session_id"]

    assert manager.catalog.delete_session(session_id) == session_id
    assert manager.catalog.list_sessions(None) == []
    assert manager.catalog.undo_delete() == 1
    assert manager.catalog.list_sessions(None)[0]["session_id"] == session_id


@pytest.mark.unit
def test_catalog_removes_all_inactive_and_reports_active_skip(tmp_path):
    manager = RecordingManager(str(tmp_path))
    active = manager.store.create(encounter("active-tab"))["session_id"]
    manager.store.create(encounter("done-1"))
    manager.store.create(encounter("done-2"))
    manager._active["active-tab"] = SimpleNamespace(session_id=active)

    result = manager.catalog.delete_all_sessions()

    assert result == {"deleted": 2, "skipped_active": 1}
    assert [row["session_id"] for row in manager.catalog.list_sessions(limit=None)] == [active]
    assert manager.catalog.undo_delete() == 2
    assert len(manager.catalog.list_sessions(limit=None)) == 3
