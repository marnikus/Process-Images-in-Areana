"""D3/F-C: independent ground-truth labels — store, manager, bridge, cohort (RULE 8)."""

import json

import pytest

from app.services.captcha_recording.cohort import cohort
from app.services.captcha_recording.manager import RecordingManager
from app.services.captcha_recording.models import VALID_RESULT_LABELS
from app.services.captcha_recording.store import (RecordingStore, read_manifest,
                                                  summary, write_manifest)
from app.ui.services.captcha_recordings_bridge import CaptchaRecordingsBridge


def _started_store(tmp_path) -> tuple[RecordingStore, str]:
    store = RecordingStore(tmp_path)
    manifest = store.create({"eid": "e1", "tab": "t1", "url": "https://arena.ai/c/1",
                             "source": "test", "kind": "recaptcha_enterprise"})
    return store, manifest["session_id"]


@pytest.mark.unit
def test_manifest_defaults_result_label_unknown(tmp_path):
    store, session_id = _started_store(tmp_path)
    row = summary(store.session_folder(session_id))
    assert row["result_label"] == "unknown"
    assert row["actor_label"] == "unknown"


@pytest.mark.unit
def test_set_result_label_round_trips_and_rejects_invalid(tmp_path):
    store, session_id = _started_store(tmp_path)
    for label in sorted(VALID_RESULT_LABELS):
        summary = store.set_result_label(session_id, label)
        assert summary["result_label"] == label
    with pytest.raises(ValueError):
        store.set_result_label(session_id, "solved")  # not a result label
    assert store.set_result_label(session_id, "passed")["result_label"] == "passed"


@pytest.mark.unit
def test_actor_and_result_labels_are_independent(tmp_path):
    store, session_id = _started_store(tmp_path)
    store.set_label(session_id, "bot")
    store.set_result_label(session_id, "failed")
    manifest = read_manifest(store.session_folder(session_id))
    assert manifest["actor_label"] == "bot" and manifest["result_label"] == "failed"


@pytest.mark.unit
def test_label_history_has_timestamps_and_is_bounded(tmp_path):
    store, session_id = _started_store(tmp_path)
    for i in range(13):
        store.set_label(session_id, "bot" if i % 2 else "manual")
        store.set_result_label(session_id, "passed" if i % 2 else "failed")
    manifest = read_manifest(store.session_folder(session_id))
    history = manifest["label_history"]
    assert len(history) == 10  # bounded
    assert all(entry.get("at") for entry in history)
    kinds = {tuple(sorted(entry.keys())) for entry in history}
    assert kinds == {("actor", "at"), ("at", "result")}  # sorted key order


@pytest.mark.unit
def test_old_manifest_without_result_label_stays_readable(tmp_path):
    """Backwards compatibility: recordings from before D3 have no result_label."""
    store, session_id = _started_store(tmp_path)
    folder = store.session_folder(session_id)
    legacy = read_manifest(folder)
    legacy.pop("result_label")
    legacy.pop("label_history")
    write_manifest(folder, legacy)
    out = store.set_result_label(session_id, "mixed")
    assert out["result_label"] == "mixed"
    manifest = read_manifest(folder)
    assert len(manifest["label_history"]) == 1


@pytest.mark.unit
def test_manager_and_bridge_expose_result_labels(tmp_path):
    manager = RecordingManager(tmp_path)
    store = manager.store
    session_id = store.create({"eid": "e", "tab": "t", "url": "u",
                               "source": "s", "kind": "k"})["session_id"]
    assert manager.set_result_label(session_id, "passed")["result_label"] == "passed"
    with pytest.raises(ValueError):
        manager.set_result_label(session_id, "nope")

    bridge = CaptchaRecordingsBridge(manager)
    reply = json.loads(bridge.set_result_label(session_id, "mixed"))
    assert reply["ok"] is True and reply["session"]["result_label"] == "mixed"
    bad = json.loads(bridge.set_result_label(session_id, "solved"))
    assert bad["ok"] is False and "result label" in bad["error"]
    reply = json.loads(bridge.cohort())
    assert reply["ok"] is True and "success_rate" in reply["cohort"]


# --- cohort: unknown/mixed are excluded from pure statistics (F-C) ---

def _row(actor="unknown", result="unknown", **kw):
    row = {"session_id": kw.get("id", "s"), "actor_label": actor, "result_label": result}
    row.update(kw)
    return row


@pytest.mark.unit
def test_cohort_pure_rate_uses_definite_rows_only():
    rows = [_row("bot", "passed", id="1"), _row("bot", "failed", id="2"),
            _row("manual", "passed", id="3"), _row("manual", "passed", id="4"),
            _row("bot", "mixed", id="5"), _row("bot", "unknown", id="6"),
            _row("manual", "unknown", id="7")]
    out = cohort(rows)
    assert out["total"] == 7
    assert out["definite"] == 4  # mixed + unknown excluded
    assert out["mixed"] == 1 and out["unknown"] == 2
    assert out["success_rate"] == pytest.approx(3 / 4)  # 3 passed of 4 definite
    assert out["matrix"]["bot"] == {"passed": 1, "failed": 1, "mixed": 1, "unknown": 1}
    assert out["matrix"]["manual"] == {"passed": 2, "failed": 0, "mixed": 0, "unknown": 1}


@pytest.mark.unit
def test_cohort_empty_and_garbage_inputs():
    assert cohort([])["success_rate"] is None
    out = cohort([_row("alien", "banana"), _row()])  # garbage folds to unknown
    assert out["success_rate"] is None  # no definite rows
    assert out["matrix"]["unknown"]["unknown"] == 2  # garbage actor -> unknown bucket
    assert out["total"] == 2
