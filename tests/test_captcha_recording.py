"""Recording store tests: persistence, caps, and secret redaction (RULE 20)."""

import json

import pytest

from app.services.captcha.recording import RecordingStore


@pytest.mark.unit
def test_recording_round_trip_and_redaction(tmp_path):
    store = RecordingStore(str(tmp_path))
    rec = store.start("eid1", "corr1", "tab1", {"sitekey": "public", "token": "never"})
    rec.snapshot({"url": "https://arena.ai/c/1", "dom": {"node_count": 3}})
    rec.event("network", {"status": 200, "authorization": "secret", "path": "/api/generate"})
    rec.stop("job_terminal", "completed")
    manifest = store.load(rec.rid)
    assert manifest["label"] == "unknown"
    raw = (store.events(rec.rid)).read_text()
    assert "secret" not in raw and "never" not in raw
    assert any(e["kind"] == "snapshot" for e in store.load_events(rec.rid))
    assert store.label(rec.rid, "manual_pass", "human cleared")
    assert store.load(rec.rid)["label"] == "manual_pass"


@pytest.mark.unit
def test_invalid_label_is_rejected(tmp_path):
    store = RecordingStore(str(tmp_path))
    rec = store.start("e", "c", "t", {})
    assert not store.label(rec.rid, "maybe")
    assert store.delete(rec.rid)
    assert store.load(rec.rid) is None
