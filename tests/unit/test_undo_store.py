"""Unit tests for UndoStore — global undo timeline persistence (B7 coverage).

RULE 8: each test fails if the store's contract breaks (clamp to
MAX_HISTORY, branch-on-undo truncation, duplicate suppression, corrupt
fallback).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.persistence.undo_store import MAX_HISTORY, UndoStore


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "undo.json"


@pytest.mark.unit
def test_fresh_store_is_empty(store_path: Path):
    store = UndoStore(store_path)
    assert store.get() == ([], -1)


@pytest.mark.unit
def test_push_save_load_round_trip(store_path: Path):
    store = UndoStore(store_path)
    store.push("urls", ["a"])
    store.push("folder", "/x")
    reloaded = UndoStore(store_path)
    hist, idx = reloaded.get()
    assert [e["kind"] for e in hist] == ["urls", "folder"]
    assert idx == 1


@pytest.mark.unit
def test_push_after_undo_truncates_branch(store_path: Path):
    store = UndoStore(store_path)
    store.push("urls", ["a"])
    store.push("urls", ["a", "b"])
    # user undoes one step -> index 0, then edits again -> branch dropped
    assert store.set([{"kind": "urls", "value": ["a"]}], 0) is True
    hist, idx = store.push("folder", "/x")
    assert [e["value"] for e in hist] == [["a"], "/x"]
    assert idx == 1


@pytest.mark.unit
def test_push_suppresses_duplicate_consecutive_entry(store_path: Path):
    store = UndoStore(store_path)
    store.push("urls", ["a"])
    hist, idx = store.push("urls", ["a"])
    assert len(hist) == 1 and idx == 0


@pytest.mark.unit
def test_push_clamps_to_max_history(store_path: Path):
    store = UndoStore(store_path)
    for i in range(MAX_HISTORY + 7):
        store.push("urls", [i])
    hist, idx = store.get()
    assert len(hist) == MAX_HISTORY
    assert idx == MAX_HISTORY - 1
    assert hist[0]["value"] == [7]  # oldest trimmed, not newest


@pytest.mark.unit
def test_set_rejects_non_list_history_and_non_int_index(store_path: Path):
    store = UndoStore(store_path)
    assert store.set("not-a-list", "not-an-int") is True  # coerced, saved
    hist, idx = store.get()
    assert hist == [] and idx == -1


@pytest.mark.unit
def test_corrupt_file_falls_back_to_defaults(store_path: Path):
    store_path.write_text("{oops", encoding="utf-8")
    assert UndoStore(store_path).get() == ([], -1)


@pytest.mark.unit
def test_non_dict_history_coerced_and_index_reset(store_path: Path):
    store_path.write_text(json.dumps({"history": "junk", "index": 3}), encoding="utf-8")
    # clamp on load: non-list history -> [], index into empty history -> -1
    assert UndoStore(store_path).get() == ([], -1)


@pytest.mark.unit
def test_oversized_history_clamped_on_load(store_path: Path):
    big = [{"kind": "urls", "value": [i]} for i in range(MAX_HISTORY + 20)]
    store_path.write_text(json.dumps({"history": big, "index": MAX_HISTORY + 19}), encoding="utf-8")
    hist, idx = UndoStore(store_path).get()
    assert len(hist) == MAX_HISTORY
    assert idx == MAX_HISTORY - 1
    assert hist[0]["value"] == [20]  # oldest trimmed


@pytest.mark.unit
def test_load_repairs_out_of_range_index(store_path: Path):
    hist = [{"kind": "urls", "value": [i]} for i in range(3)]
    for bad_idx, expected in [(99, 2), (-5, -1), ("junk", 2)]:
        store_path.write_text(json.dumps({"history": hist, "index": bad_idx}), encoding="utf-8")
        assert UndoStore(store_path).get() == (hist, expected), bad_idx


@pytest.mark.unit
def test_save_failure_returns_false(tmp_path: Path):
    store = UndoStore(tmp_path / "undo.json")
    store.push("urls", ["a"])
    store.path = tmp_path / "no-such-dir" / "sub" / "undo.json"
    # parent dir missing AND mkdir is only done by save_json_atomic -> actually creates dirs;
    # force a real failure by pointing at a directory path instead
    store.path = tmp_path  # a directory: replace() must fail
    assert store.save() is False
