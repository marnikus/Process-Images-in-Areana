"""Local captcha recording manifests, labels, and redaction."""

import json

import pytest

from app.services.captcha_recording.reader import EvidenceReader
from app.services.captcha_recording.retention import prune_recordings
from app.services.captcha_recording.sanitize import clean_mapping, redact_text, safe_url, textual_mime
from app.services.captcha_recording.store import RecordingStore


def encounter(tab="tab-a"):
    return {"eid": "e1", "tab": tab, "source": "test", "url": "https://arena.ai/c/1?token=secret#x",
            "kind": "recaptcha_enterprise"}


@pytest.mark.unit
def test_store_create_finish_list_and_label(tmp_path):
    store = RecordingStore(tmp_path)
    manifest = store.create(encounter())
    store.append_event(manifest["session_id"], {"seq": 0, "kind": "state"})
    store.write_snapshot(manifest["session_id"], 0, {"html": "<main/>"})
    store.finish(manifest["session_id"], {"status": "solved", "outcome": "solved", "method": "auto"})

    rows = store.list_sessions()
    assert len(rows) == 1 and rows[0]["url"] == "https://arena.ai/c/1"
    updated = store.set_labels(manifest["session_id"], "mixed", "failed")
    assert updated["actor_label"] == "mixed"
    assert updated["result_label"] == "failed"
    assert (store.root / manifest["session_id"] / "snapshots/000000.json.gz").exists()


@pytest.mark.unit
def test_store_lists_every_retained_session_without_limit(tmp_path):
    store = RecordingStore(tmp_path)
    session_ids = [store.create(encounter(str(index)))["session_id"] for index in range(3)]

    assert {row["session_id"] for row in store.list_sessions(limit=None)} == set(session_ids)
    assert len(store.list_sessions(limit=0)) == 3
    assert len(store.list_sessions(limit=2)) == 2


@pytest.mark.unit
def test_store_rejects_bad_label_and_path(tmp_path):
    store = RecordingStore(tmp_path)
    session_id = store.create(encounter())["session_id"]
    with pytest.raises(ValueError):
        store.set_label(session_id, "robot")
    with pytest.raises(ValueError):
        store.set_labels(session_id, "bot", "maybe")
    with pytest.raises(ValueError):
        store.set_label("../escape", "bot")


@pytest.mark.unit
def test_store_recovers_recording_manifest(tmp_path):
    store = RecordingStore(tmp_path)
    session_id = store.create(encounter())["session_id"]
    recovered = RecordingStore(tmp_path).list_sessions()[0]
    assert recovered["session_id"] == session_id
    assert recovered["status"] == "interrupted"


@pytest.mark.unit
def test_store_ignores_corrupt_manifest(tmp_path):
    folder = tmp_path / "captcha_recordings" / "bad"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text("not-json", encoding="utf-8")
    assert RecordingStore(tmp_path).list_sessions() == []


@pytest.mark.unit
def test_redaction_helpers_remove_secrets():
    token = "A" * 100
    assert safe_url("https://x.test/a?q=secret#f") == "https://x.test/a"
    assert token not in redact_text("Bearer abc.def " + token)
    clean = clean_mapping({"authorization": "secret", "nested": {"token": token}, "ok": token})
    assert clean["authorization"] == "[REDACTED]"
    assert clean["nested"]["token"] == "[REDACTED]"
    assert token not in json.dumps(clean)
    assert textual_mime("application/json") and not textual_mime("image/png")

@pytest.mark.unit
def test_evidence_reader_returns_bounded_comparison_model(tmp_path):
    store = RecordingStore(tmp_path)
    session_id = store.create(encounter())["session_id"]
    store.append_event(session_id, {"kind": "mutation", "at_ms": 1, "payload": {"path": "main"}})
    store.write_snapshot(session_id, 0, {"at_ms": 2, "html": "x" * 21000})

    details = EvidenceReader(store.root).details(session_id)

    assert details["events"][0]["payload"]["path"] == "main"
    assert details["events"][0]["offset_ms"] == 1
    assert details["snapshots"][0]["offset_ms"] == 2
    assert len(details["latest_snapshot"]["html"]) == 20000
    assert details["latest_snapshot"]["truncated_for_view"] is True

@pytest.mark.unit
def test_retention_removes_oldest_folder_by_count(tmp_path):
    root = tmp_path / "records"
    for name in ("20260101-old", "20260102-new", ".delete_undo"):
        folder = root / name
        folder.mkdir(parents=True)
        (folder / "data").write_bytes(b"1234")

    prune_recordings(root, max_sessions=1, max_bytes=100)

    assert not (root / "20260101-old").exists()
    assert (root / "20260102-new").exists()
    assert (root / ".delete_undo").exists()
