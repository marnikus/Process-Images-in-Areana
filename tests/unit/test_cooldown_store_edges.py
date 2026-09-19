"""Unit tests for cooldown_store error branches (B7 coverage).

RULE 8: junk on disk must be dropped (RULE 4: empty vs broken distinct),
never crash the save/load path.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app.persistence import cooldown_store as store


@pytest.mark.unit
def test_load_entries_drops_malformed_and_idle_expired(tmp_path: Path):
    path = tmp_path / "cd.json"
    now = time.time()
    path.write_text(json.dumps({"entries": {
        "junk-str": "not-a-dict",
        "bad-until": {"cooldown_until": "nope", "pending_penalty": 0},
        "expired-idle": {"cooldown_until": now - 10, "pending_penalty": 0},
        "expired-pending": {"cooldown_until": now - 10, "pending_penalty": 30},
        "live": {"cooldown_until": now + 60, "pending_penalty": 0},
    }}), encoding="utf-8")
    entries = store.load_entries(path)
    assert set(entries) == {"expired-pending", "live"}


@pytest.mark.unit
def test_load_entries_non_dict_entries_section(tmp_path: Path):
    path = tmp_path / "cd.json"
    path.write_text(json.dumps({"entries": ["a", "b"]}), encoding="utf-8")
    assert store.load_entries(path) == {}


@pytest.mark.unit
def test_save_entries_sorts_junk_first_and_caps(tmp_path: Path):
    path = tmp_path / "cd.json"
    now = time.time()
    entries = {f"t{i}": {"cooldown_until": now + i, "pending_penalty": 0} for i in range(5)}
    entries["junk"] = "not-a-dict"  # sort key 0 -> evicted first by the cap
    store._MAX_ENTRIES  # documented cap exists
    cap = store._MAX_ENTRIES
    # exceed the cap so exactly one (the junk/oldest) is trimmed
    for i in range(cap):
        entries[f"fill{i}"] = {"cooldown_until": now + 100 + i, "pending_penalty": 0}
    store.save_entries(path, entries)
    kept = json.loads(path.read_text(encoding="utf-8"))["entries"]
    assert "junk" not in kept
    assert len(kept) == cap
    # newest survives, oldest of the real ones trimmed
    assert f"fill{cap-1}" in kept


@pytest.mark.unit
def test_load_stats_drops_malformed_and_merges_max(tmp_path: Path):
    path = tmp_path / "cd.json"
    path.write_text(json.dumps({"stats": {
        "not-a-dict": 7,
        "https://arena.ai/": {"jobs_completed": 3},
        "HTTPS://ARENA.AI": {"jobs_completed": 9},     # same normalized URL -> max
        "https://other/": {"jobs_completed": True},     # bool is not a count
        "https://neg/": {"jobs_completed": -2},         # negative refused
        "https://str/": {"jobs_completed": "5"},        # non-int refused
    }}), encoding="utf-8")
    stats = store.load_stats(path)
    assert stats == {"https://arena.ai": {"jobs_completed": 9}}


@pytest.mark.unit
def test_load_stats_non_dict_section(tmp_path: Path):
    path = tmp_path / "cd.json"
    path.write_text(json.dumps({"stats": [1]}), encoding="utf-8")
    assert store.load_stats(path) == {}


@pytest.mark.unit
def test_merge_page_entry_drops_idle_page(tmp_path: Path):
    path = tmp_path / "cd.json"
    now = time.time()
    store.save_entries(path, {"t1": {"tab_id": "t1", "url": "u",
                                     "cooldown_until": now + 50,
                                     "pending_penalty": 0, "captcha_count": 0}})
    page = {"tab_id": "t1", "url": "u", "status": "steady",
            "cooldown_until": 0, "pending_penalty": 0}
    entries = store.load_entries(path)
    store._merge_page_entry(entries, page)  # idle page must release its entry
    assert "t1" not in entries


@pytest.mark.unit
def test_pending_penalty_keeps_non_cooldown_page(tmp_path: Path):
    page = {"tab_id": "t9", "url": "u", "status": "error",
            "pending_penalty": 45, "cooldown_until": 0}
    entry = store._entry_from_page(page)
    assert entry is not None and entry["pending_penalty"] == 45


@pytest.mark.unit
def test_entry_from_page_rejects_past_cooldown_without_pending():
    page = {"tab_id": "t8", "url": "u", "status": "cooldown",
            "cooldown_until": time.time() - 5, "pending_penalty": 0}
    assert store._entry_from_page(page) is None


@pytest.mark.unit
def test_save_pool_snapshot_swallows_pool_errors(tmp_path: Path):
    path = tmp_path / "cd.json"

    class BrokenPool:
        def status_snapshot(self):
            raise RuntimeError("pool gone")

    store.save_pool_snapshot(path, BrokenPool())  # must not raise, must not write
    assert not path.exists()
