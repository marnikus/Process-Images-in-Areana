"""D5 mutation triage: captcha_recording store + models, branch-complete.

Targets new_manifest (80), write_manifest (10), list_sessions (9),
write_snapshot (8), append_event (8), recover_interrupted (7), finish (7),
session_folder (6), __init__ (5), recording_enabled (5) + models.
"""

import gzip
import json
from pathlib import Path

from app.services.captcha_recording import store as rec_store
from app.services.captcha_recording.models import (
    FINAL_OUTCOMES,
    RecordingLimits,
    VALID_LABELS,
    VALID_RESULT_LABELS,
    day_folder_for,
    new_session_id,
    utc_now,
)
from app.services.captcha_recording.store import (
    SCHEMA_VERSION,
    RecordingStore,
    new_manifest,
    read_manifest,
    recording_enabled,
    save_recording_enabled,
    summary,
    write_manifest,
)


class TestRecordingEnabled:
    def test_missing_defaults_on(self, tmp_path):
        assert recording_enabled(tmp_path) is True

    def test_corrupt_defaults_on(self, tmp_path):
        (tmp_path / rec_store.SETTINGS_NAME).write_text("{bad", encoding="utf-8")
        assert recording_enabled(tmp_path) is True

    def test_off(self, tmp_path):
        (tmp_path / rec_store.SETTINGS_NAME).write_text(
            json.dumps({"recording_enabled": False}), encoding="utf-8")
        assert recording_enabled(tmp_path) is False

    def test_falsy_value(self, tmp_path):
        (tmp_path / rec_store.SETTINGS_NAME).write_text(
            json.dumps({"recording_enabled": 0}), encoding="utf-8")
        assert recording_enabled(tmp_path) is False

    def test_round_trip(self, tmp_path):
        save_recording_enabled(tmp_path, False)
        assert recording_enabled(tmp_path) is False
        save_recording_enabled(tmp_path, True)
        assert recording_enabled(tmp_path) is True


class TestNewManifest:
    def test_empty_encounter_defaults(self):
        m = new_manifest("s-1", {})
        assert m["schema_version"] == SCHEMA_VERSION
        assert m["session_id"] == "s-1"
        assert m["eid"] == ""
        assert m["tab"] == ""
        assert m["source"] == ""
        assert m["url"] == ""
        assert m["kind"] == "unknown"
        assert m["ended_at"] == ""
        assert m["status"] == "recording"
        assert m["outcome"] == ""
        assert m["reason"] == ""
        assert m["method"] == ""
        assert m["actor_label"] == "unknown"
        assert m["result_label"] == "unknown"
        assert m["label_history"] == []
        assert m["elapsed_ms"] == 0
        assert m["event_count"] == 0
        assert m["mutation_count"] == 0
        assert m["network_count"] == 0
        assert m["snapshot_count"] == 0
        assert m["dropped_events"] == 0
        assert m["truncated"] == []
        assert m["started_at"]  # non-empty utc

    def test_full_encounter_coerced_to_str(self):
        m = new_manifest("s-2", {
            "eid": 123,
            "tab": "TAB-9",
            "source": "arena",
            "url": "https://x.test/page?api_key=SECRET",
            "kind": "recaptcha_v2",
        })
        assert m["eid"] == "123"
        assert m["tab"] == "TAB-9"
        assert m["source"] == "arena"
        assert m["kind"] == "recaptcha_v2"
        assert "SECRET" not in m["url"]  # safe_url redacts tokens

    def test_none_values_coerced(self):
        m = new_manifest("s-3", {"eid": None, "tab": None, "kind": None})
        assert m["eid"] == "None"
        assert m["tab"] == "None"
        assert m["kind"] == "None"


class TestManifestIO:
    def test_write_read_round_trip(self, tmp_path):
        m = new_manifest("s-1", {})
        write_manifest(tmp_path, m)
        assert read_manifest(tmp_path) == m
        assert not (tmp_path / "manifest.json.tmp").exists()

    def test_read_not_object(self, tmp_path):
        (tmp_path / "manifest.json").write_text("[1,2]", encoding="utf-8")
        assert read_manifest(tmp_path, tolerate=True) == {}
        try:
            read_manifest(tmp_path)
            assert False, "expected exception"
        except ValueError:
            pass

    def test_read_missing(self, tmp_path):
        assert read_manifest(tmp_path, tolerate=True) == {}
        try:
            read_manifest(tmp_path)
            assert False, "expected exception"
        except FileNotFoundError:
            pass

    def test_summary_keys(self, tmp_path):
        m = new_manifest("s-1", {"eid": "e9"})
        write_manifest(tmp_path, m)
        s = summary(tmp_path)
        assert s["session_id"] == "s-1"
        assert s["eid"] == "e9"
        assert "url" in s and "truncated" in s

    def test_summary_missing_tolerated(self, tmp_path):
        assert summary(tmp_path) == {}


class TestRecordingStore:
    def make(self, tmp_path, name="a"):
        return RecordingStore(tmp_path / name)

    def test_init_creates_root(self, tmp_path):
        s = self.make(tmp_path)
        assert s.root.is_dir()

    def test_create(self, tmp_path):
        s = self.make(tmp_path)
        m = s.create({"eid": "e1", "url": "https://x.test"})
        assert m["status"] == "recording"
        folder = s.session_folder(m["session_id"])
        assert (folder / "snapshots").is_dir()
        assert (folder / "manifest.json").exists()

    def test_session_folder_invalid_ids(self, tmp_path):
        s = self.make(tmp_path)
        for bad in ("", "../evil", "a/b"):
            try:
                s.session_folder(bad)
                assert False, f"expected ValueError for {bad}"
            except ValueError:
                pass
        # D5: "."/".." must be rejected (traversal — Path("..").name == "..")
        for bad in (".", ".."):
            try:
                s.session_folder(bad)
                assert False, f"expected ValueError for {bad}"
            except ValueError:
                pass

    def test_session_folder_missing(self, tmp_path):
        s = self.make(tmp_path)
        try:
            s.session_folder("20200101T000000-0000")
            assert False, "expected FileNotFoundError"
        except FileNotFoundError:
            pass

    def test_append_event(self, tmp_path):
        s = self.make(tmp_path)
        m = s.create({})
        s.append_event(m["session_id"], {"t": "a"})
        s.append_event(m["session_id"], {"t": "b", "x": 1})
        lines = (s.session_folder(m["session_id"]) / "events.jsonl").read_text("utf-8").splitlines()
        assert lines == ['{"t":"a"}', '{"t":"b","x":1}']

    def test_write_snapshot_gzip(self, tmp_path):
        s = self.make(tmp_path)
        m = s.create({})
        rel = s.write_snapshot(m["session_id"], 7, {"k": "v"})
        assert rel == "snapshots/000007.json.gz"
        target = s.session_folder(m["session_id"]) / rel
        with gzip.open(target, "rt", encoding="utf-8") as handle:
            assert json.load(handle) == {"k": "v"}

    def test_finish(self, tmp_path):
        s = self.make(tmp_path)
        m = s.create({})
        out = s.finish(m["session_id"], {"status": "done", "outcome": "solved"})
        assert out["status"] == "done"
        assert out["outcome"] == "solved"
        assert out["ended_at"]

    def test_finish_keeps_existing_ended_at(self, tmp_path):
        s = self.make(tmp_path)
        m = s.create({})
        folder = s.session_folder(m["session_id"])
        data = read_manifest(folder)
        data["ended_at"] = "fixed-time"
        write_manifest(folder, data)
        out = s.finish(m["session_id"], {})
        assert out["ended_at"] == "fixed-time"

    def test_list_sessions_sorted_and_limited(self, tmp_path):
        s = self.make(tmp_path)
        created = [s.create({"eid": f"e{i}"}) for i in range(3)]
        for i, m in enumerate(created):
            folder = s.session_folder(m["session_id"])
            data = read_manifest(folder)
            data["started_at"] = f"2026-01-0{i + 1}T00:00:00Z"
            write_manifest(folder, data)
        rows = s.list_sessions()
        assert [r["eid"] for r in rows] == ["e2", "e1", "e0"]
        assert len(s.list_sessions(limit=1)) == 1
        assert len(s.list_sessions(limit=0)) == 1
        assert len(s.list_sessions(limit=99999)) == 3
        assert s.count_sessions() == 3

    def test_delete_session(self, tmp_path):
        s = self.make(tmp_path)
        m = s.create({})
        out = s.delete_session(m["session_id"])
        assert out == {"session_id": m["session_id"], "deleted": True}
        assert s.count_sessions() == 0

    def test_set_label(self, tmp_path):
        s = self.make(tmp_path)
        m = s.create({})
        row = s.set_label(m["session_id"], "bot")
        assert row["actor_label"] == "bot"
        hist = read_manifest(s.session_folder(m["session_id"]))["label_history"]
        assert hist[0]["actor"] == "bot"
        try:
            s.set_label(m["session_id"], "weird")
            assert False, "expected ValueError"
        except ValueError:
            pass

    def test_set_result_label(self, tmp_path):
        s = self.make(tmp_path)
        m = s.create({})
        row = s.set_result_label(m["session_id"], "passed")
        assert row["result_label"] == "passed"
        try:
            s.set_result_label(m["session_id"], "nope")
            assert False, "expected ValueError"
        except ValueError:
            pass

    def test_label_history_bounded(self, tmp_path):
        s = self.make(tmp_path)
        m = s.create({})
        for i, label in enumerate(("bot", "manual", "unknown")):
            for _ in range(5):
                s.set_label(m["session_id"], label)
        folder = s.session_folder(m["session_id"])
        hist = read_manifest(folder)["label_history"]
        assert len(hist) == 10
        assert "label_updated_at" in read_manifest(folder)

    def test_recover_interrupted(self, tmp_path):
        s1 = self.make(tmp_path)
        m = s1.create({})
        assert read_manifest(s1.session_folder(m["session_id"]))["status"] == "recording"
        s2 = RecordingStore(tmp_path / "a")  # second init triggers recovery
        assert read_manifest(s2.session_folder(m["session_id"]))["status"] == "interrupted"


class TestModels:
    def test_utc_now_format(self):
        s = utc_now()
        assert s.endswith("Z")
        assert "T" in s

    def test_session_id_and_day(self):
        sid = new_session_id()
        assert len(sid) > 8
        assert day_folder_for(sid) == f"{sid[0:4]}-{sid[4:6]}-{sid[6:8]}"

    def test_day_folder_padded(self):
        assert day_folder_for("20260919T123456-abc") == "2026-09-19"

    def test_labels(self):
        assert VALID_LABELS == {"unknown", "bot", "manual"}
        assert VALID_RESULT_LABELS == {"unknown", "passed", "failed", "mixed"}
        assert "solved" in FINAL_OUTCOMES
        assert "interrupted" in FINAL_OUTCOMES

    def test_limits(self):
        l = RecordingLimits()
        assert l.max_events == 2000
        assert l.max_snapshots == 25
        assert l.poll_interval_sec == 0.5
