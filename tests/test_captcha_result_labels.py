"""D3/F-C: independent ground-truth labels — store, manager, bridge, cohort (RULE 8).

Ported onto the unified label model that this branch uses: the ACTOR axis is
`unknown|bot|manual|mixed` (who solved it — `mixed` = the bot's token was
finished by hand) and the RESULT axis is `unknown|passed|failed` (what actually
happened). The two are set independently through `set_labels()`, and the store
keeps a bounded timestamped history of every change.
"""

import json

import pytest

from app.services.captcha_recording.cohort import cohort
from app.services.captcha_recording.manager import RecordingManager
from app.services.captcha_recording.models import VALID_ACTOR_LABELS, VALID_RESULT_LABELS
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
def test_set_labels_round_trips_and_rejects_invalid(tmp_path):
    store, session_id = _started_store(tmp_path)
    for result in sorted(VALID_RESULT_LABELS):
        assert store.set_labels(session_id, "bot", result)["result_label"] == result
    for actor in sorted(VALID_ACTOR_LABELS):
        assert store.set_labels(session_id, actor, "passed")["actor_label"] == actor
    with pytest.raises(ValueError):
        store.set_labels(session_id, "solved", "passed")  # not an actor label
    with pytest.raises(ValueError):
        store.set_labels(session_id, "bot", "solved")  # not a result label
    # actor-only update through the schema-v1 entry point leaves the result alone
    assert store.set_label(session_id, "manual")["actor_label"] == "manual"
    assert read_manifest(store.session_folder(session_id))["result_label"] == "passed"


@pytest.mark.unit
def test_actor_and_result_labels_are_independent(tmp_path):
    store, session_id = _started_store(tmp_path)
    store.set_labels(session_id, "bot", "passed")
    store.set_labels(session_id, "manual", "failed")
    manifest = read_manifest(store.session_folder(session_id))
    assert manifest["actor_label"] == "manual" and manifest["result_label"] == "failed"
    store.set_label(session_id, "mixed")
    manifest = read_manifest(store.session_folder(session_id))
    assert manifest["actor_label"] == "mixed" and manifest["result_label"] == "failed"


@pytest.mark.unit
def test_label_history_has_timestamps_and_is_bounded(tmp_path):
    store, session_id = _started_store(tmp_path)
    for i in range(13):
        store.set_labels(session_id, "bot" if i % 2 else "manual",
                         "passed" if i % 2 else "failed")
    history = read_manifest(store.session_folder(session_id))["label_history"]
    assert len(history) == 10  # bounded
    assert all(entry.get("at") for entry in history)
    assert all({"actor", "result", "at"} <= set(entry) for entry in history)


@pytest.mark.unit
def test_old_manifest_without_labels_stays_readable(tmp_path):
    """Backwards compatibility: recordings from before area D have no label fields."""
    store, session_id = _started_store(tmp_path)
    folder = store.session_folder(session_id)
    legacy = read_manifest(folder)
    legacy.pop("result_label")
    legacy.pop("label_history")
    write_manifest(folder, legacy)
    out = store.set_labels(session_id, "manual", "failed")
    assert out["result_label"] == "failed" and out["actor_label"] == "manual"
    assert len(read_manifest(folder)["label_history"]) == 1


@pytest.mark.unit
def test_manager_and_bridge_expose_labels_and_cohort(tmp_path):
    manager = RecordingManager(tmp_path)
    session_id = manager.store.create({"eid": "e", "tab": "t", "url": "u",
                                       "source": "s", "kind": "k"})["session_id"]
    assert manager.set_labels(session_id, "bot", "passed")["result_label"] == "passed"
    with pytest.raises(ValueError):
        manager.set_labels(session_id, "nope", "passed")

    bridge = CaptchaRecordingsBridge(manager)
    reply = json.loads(bridge.set_labels(session_id, "mixed", "failed"))
    assert reply["ok"] is True
    assert reply["session"]["actor_label"] == "mixed"
    assert reply["session"]["result_label"] == "failed"
    bad = json.loads(bridge.set_labels(session_id, "solved", "failed"))
    assert bad["ok"] is False and "actor label" in bad["error"]
    reply = json.loads(bridge.cohort())
    assert reply["ok"] is True and "success_rate" in reply["cohort"]


# --- cohort: unknown rows are excluded from pure statistics (F-C) ---

def _row(actor="unknown", result="unknown", **kw):
    row = {"session_id": kw.get("id", "s"), "actor_label": actor, "result_label": result}
    row.update(kw)
    return row


@pytest.mark.unit
def test_cohort_pure_rate_uses_definite_rows_only():
    rows = [_row("bot", "passed", id="1"), _row("bot", "failed", id="2"),
            _row("manual", "passed", id="3"), _row("mixed", "passed", id="4"),
            _row("bot", "unknown", id="5"), _row("manual", "unknown", id="6"),
            _row("manual", "passed", id="7")]
    out = cohort(rows)
    assert out["total"] == 7
    assert out["definite"] == 5  # unknown rows excluded
    assert out["unknown"] == 2
    assert out["success_rate"] == pytest.approx(4 / 5)  # 4 passed of 5 definite
    assert out["matrix"]["bot"] == {"passed": 1, "failed": 1, "unknown": 1}
    assert out["matrix"]["manual"] == {"passed": 2, "failed": 0, "unknown": 1}
    assert out["matrix"]["mixed"] == {"passed": 1, "failed": 0, "unknown": 0}


@pytest.mark.unit
def test_cohort_empty_and_garbage_inputs():
    assert cohort([])["success_rate"] is None
    out = cohort([_row("alien", "banana"), _row()])  # garbage folds to unknown
    assert out["success_rate"] is None  # no definite rows
    assert out["matrix"]["unknown"]["unknown"] == 2  # garbage actor -> unknown bucket
    assert out["total"] == 2
