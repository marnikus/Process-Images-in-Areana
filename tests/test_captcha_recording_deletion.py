"""Recording deletion stages one reversible operation on disk."""

import pytest

from app.services.captcha_recording.deletion import RecordingDeletionUndo
from app.services.captcha_recording.store import RecordingStore


def encounter(tab):
    return {"eid": tab, "tab": tab, "source": "test", "url": "https://arena.ai/c/1",
            "kind": "recaptcha_enterprise"}


@pytest.mark.unit
def test_single_delete_and_undo_survive_service_reconstruction(tmp_path):
    store = RecordingStore(tmp_path)
    session_id = store.create(encounter("one"))["session_id"]
    deletion = RecordingDeletionUndo(store.root)

    assert deletion.stage([session_id]) == 1
    assert store.list_sessions(None) == []
    assert RecordingDeletionUndo(store.root).undo() == 1
    assert store.list_sessions(None)[0]["session_id"] == session_id


@pytest.mark.unit
def test_new_delete_permanently_replaces_previous_undo(tmp_path):
    store = RecordingStore(tmp_path)
    first = store.create(encounter("first"))["session_id"]
    second = store.create(encounter("second"))["session_id"]
    deletion = RecordingDeletionUndo(store.root)

    deletion.stage([first])
    deletion.stage([second])

    assert deletion.undo() == 1
    assert {row["session_id"] for row in store.list_sessions(None)} == {second}


@pytest.mark.unit
def test_delete_validates_every_source_before_moving(tmp_path):
    store = RecordingStore(tmp_path)
    session_id = store.create(encounter("one"))["session_id"]
    deletion = RecordingDeletionUndo(store.root)

    with pytest.raises(FileNotFoundError):
        deletion.stage([session_id, "missing"])

    assert store.list_sessions(None)[0]["session_id"] == session_id


@pytest.mark.unit
def test_undo_without_deletion_is_noop(tmp_path):
    store = RecordingStore(tmp_path)
    assert RecordingDeletionUndo(store.root).undo() == 0
