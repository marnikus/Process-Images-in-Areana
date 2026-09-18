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
    updated = store.set_label(manifest["session_id"], "bot")
    assert updated["actor_label"] == "bot"
    assert (store.root / manifest["session_id"] / "snapshots/000000.json.gz").exists()


@pytest.mark.unit
def test_store_rejects_bad_label_and_path(tmp_path):
    store = RecordingStore(tmp_path)
    session_id = store.create(encounter())["session_id"]
    with pytest.raises(ValueError):
        store.set_label(session_id, "robot")
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
    clean = clean_mapping({"authorization": "Bearer " + token,
                           "nested": {"token": token}, "ok": token})
    assert clean["authorization"] == "[REDACTED]"
    assert clean["nested"]["token"] == "[REDACTED]"
    assert token not in json.dumps(clean)
    assert textual_mime("application/json") and not textual_mime("image/png")


@pytest.mark.unit
def test_redaction_keeps_timing_and_status_evidence():
    """S-1: evidence fields with secret-shaped names must survive redaction."""
    clean = clean_mapping({
        "token_at_ms": 1726550340000,
        "token_sec": 55.8,
        "dialog_at_token": "visible",
        "token_fp": "len=512 head=03AGdB25 tail=xQ12",
        "response": "03AGdB25" + "y" * 500,  # real recaptcha response token
        "cookie": "sid=" + "b" * 60,
    })
    assert clean["token_at_ms"] == 1726550340000
    assert clean["token_sec"] == 55.8
    assert clean["dialog_at_token"] == "visible"
    assert clean["token_fp"].startswith("len=512")
    assert clean["response"] == "[REDACTED]"
    assert clean["cookie"] == "[REDACTED]"

@pytest.mark.unit
def test_evidence_reader_returns_bounded_comparison_model(tmp_path):
    store = RecordingStore(tmp_path)
    session_id = store.create(encounter())["session_id"]
    store.append_event(session_id, {"seq": 0, "kind": "mutation",
                                    "at": "2026-09-18T10:00:00Z", "offset_ms": 12,
                                    "changes": [{"op": "add", "path": "main"}]})
    store.write_snapshot(session_id, 0, {"at": "2026-09-18T10:00:05Z", "html": "x" * 21000})

    details = EvidenceReader(store.root).details(session_id)

    event = details["events"][0]
    assert event["kind"] == "mutation" and event["offset_ms"] == 12
    assert event["changes"][0]["path"] == "main"  # flat fields must reach the viewer
    snapshot = details["latest_snapshot"]
    assert snapshot["at"] == "2026-09-18T10:00:05Z"  # persisted timestamp, not a fake ms field
    assert len(snapshot["html"]) == 20000
    assert snapshot["truncated_for_view"] is True


@pytest.mark.unit
def test_session_folders_empty_for_missing_root(tmp_path):
    from app.services.captcha_recording.store import session_folders
    assert session_folders(tmp_path / "does-not-exist") == []


@pytest.mark.unit
def test_store_count_and_delete_session(tmp_path):
    store = RecordingStore(tmp_path)
    first = store.create(encounter())["session_id"]
    second = store.create(encounter(tab="tab-b"))["session_id"]
    store.append_event(first, {"seq": 0, "kind": "state"})

    assert store.count_sessions() == 2
    assert store.delete_session(first) == {"session_id": first, "deleted": True}
    assert store.count_sessions() == 1
    assert [row["session_id"] for row in store.list_sessions()] == [second]
    with pytest.raises(FileNotFoundError):
        store.delete_session(first)
    with pytest.raises(ValueError):
        store.delete_session("../escape")


@pytest.mark.unit
def test_retention_prunes_only_by_byte_safety(tmp_path):
    root = tmp_path / "records"
    for name in ("20260101-old", "20260102-new"):
        folder = root / name
        folder.mkdir(parents=True)
        (folder / "data").write_bytes(b"x" * 400)

    prune_recordings(root, max_bytes=500)  # 800 total > 500 -> oldest removed, 400 left

    assert not (root / "20260101-old").exists()
    assert (root / "20260102-new").exists()


@pytest.mark.unit
def test_retention_keeps_every_session_by_count(tmp_path):
    root = tmp_path / "records"
    for index in range(40):
        folder = root / f"20260101T000000-{index:02d}-x"
        folder.mkdir(parents=True)
        (folder / "data").write_bytes(b"12")

    prune_recordings(root)

    assert len([path for path in root.iterdir() if path.is_dir()]) == 40