"""D5 mutation triage: cohort + retention + reader, branch-complete.

Targets cohort (136), reader (118), retention (63), models (28),
probes (16), manager (75) — pure/FS logic with no browser.
"""

import gzip
import json
from pathlib import Path

from app.services.captcha_recording.cohort import (
    DEFINITE_RESULTS,
    _label,
    _result,
    _tally,
    cohort,
)
from app.services.captcha_recording.retention import (
    MAX_STORAGE_BYTES,
    _folder_size,
    day_dirs,
    drop_empty_day,
    find_session_folder,
    prune_recordings,
    session_folders,
)
from app.services.captcha_recording import reader as reader_mod
from app.services.captcha_recording.reader import EvidenceReader
from app.services.captcha_recording.models import day_folder_for, new_session_id


class TestCohortLabels:
    def test_label(self):
        assert _label({"actor_label": "bot"}, "actor_label") == "bot"
        assert _label({"actor_label": "manual"}, "actor_label") == "manual"
        assert _label({"actor_label": "weird"}, "actor_label") == "unknown"
        assert _label({}, "actor_label") == "unknown"
        assert _label({"actor_label": None}, "actor_label") == "unknown"

    def test_result(self):
        assert _result({"result_label": "passed"}) == "passed"
        assert _result({"result_label": "failed"}) == "failed"
        assert _result({"result_label": "mixed"}) == "unknown"  # mixed is an ACTOR label now
        assert _label({"actor_label": "mixed"}, "actor_label") == "mixed"
        assert _result({"result_label": "nope"}) == "unknown"
        assert _result({}) == "unknown"


class TestCohort:
    def test_empty(self):
        c = cohort([])
        assert c["total"] == 0
        assert c["definite"] == 0
        assert c["success_rate"] is None
        assert c["matrix"]["bot"] == {"passed": 0, "failed": 0, "unknown": 0}
        assert c["matrix"]["manual"] == {"passed": 0, "failed": 0, "unknown": 0}

    def test_none_sessions(self):
        assert cohort(None)["total"] == 0

    def test_matrix_and_rate(self):
        sessions = [
            {"actor_label": "bot", "result_label": "passed"},
            {"actor_label": "bot", "result_label": "failed"},
            {"actor_label": "manual", "result_label": "passed"},
            {"actor_label": "manual", "result_label": "passed"},
            {"actor_label": "mixed", "result_label": "passed"},   # bot->manual actor
            {"actor_label": "manual", "result_label": "unknown"},
        ]
        c = cohort(sessions)
        assert c["total"] == 6
        # definite = passed + failed = 5 (unknown rows stay out of the rate)
        assert c["definite"] == 5
        assert c["passed"] == 4
        assert c["failed"] == 1
        assert c["unknown"] == 1
        assert c["success_rate"] == 4 / 5
        assert c["matrix"]["bot"]["passed"] == 1
        assert c["matrix"]["bot"]["failed"] == 1
        assert c["matrix"]["mixed"]["passed"] == 1
        assert c["matrix"]["manual"]["passed"] == 2
        assert c["matrix"]["manual"]["unknown"] == 1

    def test_rate_none_without_definite(self):
        c = cohort([{"actor_label": "mixed", "result_label": "unknown"},
                    {"actor_label": "bot", "result_label": "unknown"}])
        assert c["definite"] == 0
        assert c["success_rate"] is None

    def test_all_passed(self):
        c = cohort([{"actor_label": "bot", "result_label": "passed"}])
        assert c["success_rate"] == 1.0

    def test_all_failed(self):
        c = cohort([{"actor_label": "manual", "result_label": "failed"}])
        assert c["success_rate"] == 0.0

    def test_definite_results_set(self):
        assert DEFINITE_RESULTS == {"passed", "failed"}


class TestTally:
    def test_tally_counts(self):
        matrix, totals = _tally([
            {"actor_label": "bot", "result_label": "passed"},
            {"actor_label": "bot", "result_label": "passed"},
            {"actor_label": "manual", "result_label": "failed"},
            {"actor_label": "mixed", "result_label": "passed"},   # bot->manual actor
            {"actor_label": "manual", "result_label": "unknown"},
        ])
        assert totals == {"failed": 1, "passed": 3, "unknown": 1}
        assert matrix["bot"]["passed"] == 2
        assert matrix["manual"]["failed"] == 1
        assert matrix["mixed"]["passed"] == 1

    def test_tally_none(self):
        matrix, totals = _tally(None)
        assert totals == {"failed": 0, "passed": 0, "unknown": 0}
        assert matrix == {}


def make_session(root: Path, session_id: str, nbytes: int = 10) -> Path:
    day = day_folder_for(session_id)
    folder = root / day / session_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text("x" * nbytes, encoding="utf-8")
    return folder


class TestRetention:
    def test_day_dirs_missing_root(self, tmp_path):
        assert day_dirs(tmp_path / "nope") == []

    def test_day_dirs_filters(self, tmp_path):
        (tmp_path / "2026-01-02").mkdir()
        (tmp_path / "2026-01-01").mkdir()
        (tmp_path / "not-a-day").mkdir()
        (tmp_path / "2026-01-03").write_text("file", encoding="utf-8")  # file, not dir
        days = [p.name for p in day_dirs(tmp_path)]
        assert days == ["2026-01-01", "2026-01-02"]

    def test_session_folders_both_layouts(self, tmp_path):
        (tmp_path / "2026-01-01" / "sid-a").mkdir(parents=True)
        (tmp_path / "2026-01-01" / "sid-b").mkdir(parents=True)
        (tmp_path / "legacy-c").mkdir()
        (tmp_path / "2026-01-01" / "afile").write_text("x", encoding="utf-8")
        names = [p.name for p in session_folders(tmp_path)]
        assert names == ["legacy-c", "sid-a", "sid-b"]

    def test_session_folders_missing_root(self, tmp_path):
        assert session_folders(tmp_path / "nope") == []

    def test_find_session_flat(self, tmp_path):
        f = make_session(tmp_path, "20260101T000000-0001")
        assert find_session_folder(tmp_path, "20260101T000000-0001") == f

    def test_find_session_per_day(self, tmp_path):
        f = make_session(tmp_path, "20260102T000000-0002")
        found = find_session_folder(tmp_path, "20260102T000000-0002")
        assert found == f

    def test_find_session_missing(self, tmp_path):
        make_session(tmp_path, "20260101T000000-0001")
        assert find_session_folder(tmp_path, "20260103T000000-9999") is None

    def test_folder_size(self, tmp_path):
        f = tmp_path / "x"
        f.mkdir()
        (f / "a").write_bytes(b"1" * 5)
        sub = f / "sub"
        sub.mkdir()
        (sub / "b").write_bytes(b"2" * 3)
        assert _folder_size(f) == 8

    def test_folder_size_missing(self, tmp_path):
        assert _folder_size(tmp_path / "nope") == 0

    def test_prune_removes_oldest_first(self, tmp_path):
        root = tmp_path / "rec"
        root.mkdir()
        s1 = make_session(root, "20260101T000000-0001", nbytes=200)
        s2 = make_session(root, "20260101T000001-0002", nbytes=200)
        s3 = make_session(root, "20260101T000002-0003", nbytes=200)
        # total 600 > 450 -> drop oldest (s1), then 400 <= 450 stops
        prune_recordings(root, max_bytes=450)
        assert not s1.exists()
        assert s2.exists() and s3.exists()

    def test_prune_under_cap_noop(self, tmp_path):
        root = tmp_path / "rec"
        root.mkdir()
        s1 = make_session(root, "20260101T000000-0001", nbytes=10)
        prune_recordings(root, max_bytes=MAX_STORAGE_BYTES)
        assert s1.exists()

    def test_drop_empty_day(self, tmp_path):
        day = tmp_path / "2026-01-01"
        day.mkdir()
        drop_empty_day(tmp_path, day)
        assert not day.exists()

    def test_drop_nonempty_day_kept(self, tmp_path):
        day = tmp_path / "2026-01-01"
        day.mkdir()
        (day / "keep").mkdir()
        drop_empty_day(tmp_path, day)
        assert day.exists()

    def test_drop_root_noop(self, tmp_path):
        tmp_path.mkdir(exist_ok=True)
        drop_empty_day(tmp_path, tmp_path)
        assert tmp_path.exists()

    def test_drop_missing_day_noop(self, tmp_path):
        drop_empty_day(tmp_path, tmp_path / "nope")


class TestReader:
    def _seed(self, root: Path, session_id: str, events, snapshots, manifest):
        folder = make_session(root, session_id, nbytes=0)
        (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        if events is not None:
            lines = []
            for e in events:
                lines.append(e if isinstance(e, str) else json.dumps(e))
            (folder / "events.jsonl").write_text("\n".join(lines), encoding="utf-8")
        snap_dir = folder / "snapshots"
        snap_dir.mkdir(exist_ok=True)
        for i, payload in enumerate(snapshots):
            with gzip.open(snap_dir / f"{i:06d}.json.gz", "wt", encoding="utf-8") as h:
                json.dump(payload, h)
        return folder

    def test_details(self, tmp_path):
        events = [{"kind": "state", "i": i} for i in range(300)]
        events.append({"kind": "milestone", "phase": "final"})
        events.append({"kind": "milestone", "phase": "token_ready"})
        events.append("not json{")
        events.append("[1,2,3]")  # non-dict json
        folder = self._seed(tmp_path, "20260101T000000-0001",
                            events,
                            [{"at": "t0", "html": "a"}, {"at": "t1", "html": "b"}],
                            {"session_id": "s1"})
        reader = EvidenceReader(tmp_path)
        d = reader.details("20260101T000000-0001")
        assert d["manifest"]["session_id"] == "s1"
        # last 200 lines (196 state + 2 milestones), invalid lines skipped
        assert d["events"][-1] == {"kind": "milestone", "phase": "token_ready"}
        assert len(d["events"]) == 198
        # all milestones regardless of window
        assert len(d["milestones"]) == 2
        assert d["latest_snapshot"]["html"] == "b"
        assert d["latest_snapshot"]["truncated_for_view"] is False

    def test_folder_invalid_id(self, tmp_path):
        reader = EvidenceReader(tmp_path)
        for bad in ("", "../x", "a/b", ".", ".."):
            try:
                reader.folder(bad)
                assert False, f"expected ValueError for {bad}"
            except ValueError:
                pass

    def test_is_valid_session_id(self):
        from app.services.captcha_recording.retention import is_valid_session_id
        assert is_valid_session_id("20260101T000000-0001") is True
        assert is_valid_session_id("") is False
        assert is_valid_session_id(".") is False
        assert is_valid_session_id("..") is False
        assert is_valid_session_id("../x") is False
        assert is_valid_session_id("a/b") is False

    def test_folder_missing(self, tmp_path):
        reader = EvidenceReader(tmp_path)
        try:
            reader.folder("20200101T000000-0000")
            assert False, "expected FileNotFoundError"
        except FileNotFoundError:
            pass

    def test_json_non_object(self, tmp_path):
        (tmp_path / "x.json").write_text("[1,2]", encoding="utf-8")
        try:
            EvidenceReader._json(tmp_path / "x.json")
            assert False, "expected ValueError"
        except ValueError:
            pass

    def test_events_missing(self, tmp_path):
        assert reader_mod._events(tmp_path / "nope.jsonl") == []

    def test_snapshot_truncated_flag(self, tmp_path):
        folder = make_session(tmp_path, "20260101T000000-0001", nbytes=0)
        snap = folder / "snapshots"
        snap.mkdir()
        with gzip.open(snap / "000001.json.gz", "wt", encoding="utf-8") as h:
            json.dump({"at": "t", "html": "y" * 30000}, h)
        out = reader_mod._snapshot(snap)
        assert len(out["html"]) == 20000
        assert out["truncated_for_view"] is True

    def test_snapshot_empty(self, tmp_path):
        folder = make_session(tmp_path, "20260101T000000-0001", nbytes=0)
        assert reader_mod._snapshot(folder / "snapshots") == {}

    def test_snapshot_missing_dir(self, tmp_path):
        assert reader_mod._snapshot(tmp_path / "nope") == {}

    def test_snapshot_non_dict(self, tmp_path):
        folder = make_session(tmp_path, "20260101T000000-0001", nbytes=0)
        snap = folder / "snapshots"
        snap.mkdir()
        with gzip.open(snap / "000001.json.gz", "wt", encoding="utf-8") as h:
            json.dump([1, 2], h)
        assert reader_mod._snapshot(snap) == {}


class TestModelsDay:
    def test_session_and_day_round(self):
        sid = new_session_id()
        assert day_folder_for(sid) == f"{sid[0:4]}-{sid[4:6]}-{sid[6:8]}"

    def test_day_padded(self):
        assert day_folder_for("20260919T123456-abcdef12") == "2026-09-19"
