"""Tests for app/persistence/cooldown_store.py — wall-clock timer persistence.

RULE 8: real PagePool + real JSON round-trip in tmp_path; no Qt needed.
Timers must survive app restart with real time counting (no pause).
"""

import json
import time

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.persistence import cooldown_store as store
from app.services import cooldown_service as svc


def cooling_page(tab_id, url, until):
    return PageInfo(tab_id=tab_id, ws_url=f"ws://{tab_id}", title=f"T-{tab_id}",
                     url=url, status=PageStatus.COOLDOWN, is_connected=True,
                     cooldown_until=until, cooldown_total=300,
                     cooldown_reason="job done", captcha_count=1)


def test_save_load_round_trip(tmp_path):
    pool = PagePool()
    page_a = cooling_page("a", "https://arena.ai/x?model=a", 0)
    page_a.status = PageStatus.STEADY  # add_page normalizes to steady
    pool.add_page(page_a)
    svc.start_cooldown(pool, "a", 300, reason="job done")
    idle = PageInfo(tab_id="b", title="B", url="https://arena.ai/y", is_connected=True)
    pool.add_page(idle)
    path = str(tmp_path / "cooldowns.json")
    store.save_pool_snapshot(path, pool)
    entries = store.load_entries(path)
    assert set(entries) == {"a"}
    assert entries["a"]["url"] == "https://arena.ai/x?model=a"
    assert entries["a"]["cooldown_total"] == 300
    assert entries["a"]["captcha_count"] == 1


def test_save_merges_and_prunes(tmp_path):
    path = str(tmp_path / "cooldowns.json")
    now = time.time()
    seed = {"old-tab": {"tab_id": "old-tab", "url": "https://arena.ai/z",
                        "cooldown_until": now + 100, "cooldown_total": 100,
                        "pending_penalty": 0, "captcha_count": 0, "reason": "job done"},
            "dead": {"tab_id": "dead", "url": "https://gone/", "cooldown_until": now - 5,
                     "cooldown_total": 60, "pending_penalty": 0, "captcha_count": 0}}
    store.save_entries(path, seed)
    pool = PagePool()  # empty pool must not erase the live entry
    store.save_pool_snapshot(path, pool)
    entries = store.load_entries(path)
    assert set(entries) == {"old-tab"}


def test_pending_only_entry_survives(tmp_path):
    path = str(tmp_path / "cooldowns.json")
    pool = PagePool()
    page = PageInfo(tab_id="p", title="P", url="https://arena.ai/p", is_connected=True,
                    pending_penalty=900, captcha_count=1)
    pool.add_page(page)
    store.save_pool_snapshot(path, pool)
    entries = store.load_entries(path)
    assert entries["p"]["pending_penalty"] == 900


def test_consume_prefers_tab_then_url(tmp_path):
    entries = {
        "t1": {"tab_id": "t1", "url": "https://arena.ai/x?model=a", "cooldown_until": 1},
        "t2": {"tab_id": "t2", "url": "https://arena.ai/x?model=b", "cooldown_until": 2},
    }
    key, entry = store.consume_entry_for(entries, "t2", "https://other/")
    assert (key, entry["tab_id"]) == ("t2", "t2")
    assert "t2" not in entries  # consumed
    key, entry = store.consume_entry_for(entries, "new-id", "https://arena.ai/x?model=a")
    assert (key, entry["tab_id"]) == ("t1", "t1")
    assert store.consume_entry_for(entries, "zz", "https://nomatch.example/") == (None, None)


def test_consume_strict_no_fuzzy_match():
    # isolation: tab B must never steal tab A's entry via prefix/host
    entries = {"t9": {"tab_id": "t9", "url": "https://arena.ai/image/direct", "cooldown_until": 9}}
    assert store.consume_entry_for(entries, "new", "https://arena.ai/image/direct?model=a1") == (None, None)
    assert "t9" in entries


def test_consume_url_exact_normalized():
    entries = {"t9": {"tab_id": "t9", "url": "https://arena.ai/X?model=A/", "cooldown_until": 9}}
    key, entry = store.consume_entry_for(entries, "new-id", "https://arena.ai/x?model=a")
    assert (key, entry["tab_id"]) == ("t9", "t9")


def test_consume_skips_entry_owned_by_other_tab():
    entries = {"A": {"tab_id": "A", "url": "https://arena.ai/same", "cooldown_until": 9}}
    assert store.consume_entry_for(entries, "B", "https://arena.ai/same", {"A", "B"}) == (None, None)
    assert "A" in entries
    key, _ = store.consume_entry_for(entries, "A2", "https://arena.ai/same", set())
    assert key == "A"  # fresh pool after restart: URL fallback still works


def test_load_missing_or_corrupt_returns_empty(tmp_path):
    assert store.load_entries(str(tmp_path / "nope.json")) == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert store.load_entries(str(bad)) == {}


def test_restore_applies_unexpired_wall_clock():
    pool = PagePool()
    pool.add_page(PageInfo(tab_id="a", title="A", url="https://arena.ai/x", is_connected=True))
    until = time.time() + 200
    entry = {"tab_id": "old", "url": "https://arena.ai/x", "cooldown_until": until,
             "cooldown_total": 300, "pending_penalty": 0, "captcha_count": 2, "reason": "job done"}
    assert svc.restore_cooldown_entry(pool, "a", entry) is True
    page = pool.get_page("a")
    assert page.status == PageStatus.COOLDOWN
    assert page.cooldown_until == until
    assert page.captcha_count == 2
    assert 0 < page.remaining_seconds() <= 200


def test_restore_ignores_expired_and_busy():
    pool = PagePool()
    pool.add_page(PageInfo(tab_id="s", title="S", url="u", is_connected=True))
    pool.add_page(PageInfo(tab_id="b", title="B", url="u", is_connected=True))
    pool.mark_busy("b", "j")
    expired = {"cooldown_until": time.time() - 1, "pending_penalty": 0}
    assert svc.restore_cooldown_entry(pool, "s", expired) is False
    assert pool.get_page("s").status == PageStatus.STEADY
    live = {"cooldown_until": time.time() + 100, "pending_penalty": 0}
    assert svc.restore_cooldown_entry(pool, "b", live) is False
    assert pool.get_page("b").status == PageStatus.BUSY


def test_restore_pending_only_and_never_shortens():
    pool = PagePool()
    pool.add_page(PageInfo(tab_id="p", title="P", url="u", is_connected=True))
    only_pending = {"cooldown_until": 0, "pending_penalty": 900, "captcha_count": 1}
    assert svc.restore_cooldown_entry(pool, "p", only_pending) is True
    assert pool.get_page("p").status == PageStatus.STEADY
    assert pool.get_page("p").pending_penalty == 900
    svc.start_cooldown(pool, "p", 300, reason="job done")
    shorter = {"cooldown_until": time.time() + 10, "pending_penalty": 0}
    assert svc.restore_cooldown_entry(pool, "p", shorter) is False


def test_stats_round_trip_never_pruned(tmp_path):
    path = str(tmp_path / "cooldowns.json")
    pool = PagePool()
    pool.add_page(PageInfo(tab_id="a", title="A", url="https://arena.ai/x?m=1", is_connected=True))
    pool.get_page("a").jobs_completed = 4
    store.save_pool_snapshot(path, pool)
    stats = store.load_stats(path)
    assert stats[store.normalize_url("https://arena.ai/x?m=1")]["jobs_completed"] == 4


def test_stats_merge_keeps_absent_and_entries_intact(tmp_path):
    path = str(tmp_path / "cooldowns.json")
    pool = PagePool()
    pool.add_page(PageInfo(tab_id="a", title="A", url="https://arena.ai/new", is_connected=True))
    pool.get_page("a").jobs_completed = 1
    store.save_pool_snapshot(path, pool)
    stats = store.load_stats(path)
    assert set(stats) == {store.normalize_url("https://arena.ai/new")}
    # entries section unaffected by stats-only pages
    assert store.load_entries(path) == {}


def test_normalize_url():
    assert store.normalize_url("https://Arena.AI/X/") == "https://arena.ai/x"
    assert store.normalize_url(None) == ""
    assert store.normalize_url(42) == ""


def test_describe_missing_file(tmp_path):
    rep = store.describe_cooldown_file(str(tmp_path / "nope.json"))
    assert rep == {"exists": False, "raw": 0, "live": 0, "dropped": []}


def test_describe_empty_and_malformed(tmp_path):
    path = tmp_path / "c.json"
    path.write_text('{"version": 1, "entries": {}}')
    assert store.describe_cooldown_file(str(path))["live"] == 0
    path.write_text('{"version": 1, "entries": [1, 2]}')
    rep = store.describe_cooldown_file(str(path))
    assert (rep["exists"], rep["raw"], rep["live"]) == (True, 0, 0)
    path.write_text('not json {{{')
    rep = store.describe_cooldown_file(str(path))
    assert (rep["exists"], rep["live"]) == (True, 0)


def test_describe_live_and_dropped(tmp_path):
    path = str(tmp_path / "c.json")
    now = time.time()
    doc = {"version": 1, "entries": {
        "live": {"tab_id": "live", "url": "https://arena.ai/x",
                 "cooldown_until": now + 200, "pending_penalty": 0},
        "old": {"tab_id": "old", "url": "https://arena.ai/x",
                "cooldown_until": now - 200, "pending_penalty": 0},
        "junk": [1, 2]}}
    with open(path, "w") as f:
        json.dump(doc, f)
    rep = store.describe_cooldown_file(str(path))
    assert (rep["exists"], rep["raw"], rep["live"]) == (True, 3, 1)
    assert sorted(rep["dropped"]) == ["junk", "old"]


# ── guard paths: junk-tolerant private helpers + alias round-trips ──

def test_save_aliases_merges_caps_and_filters_junk(tmp_path):
    p = tmp_path / "cd.json"
    store.save_aliases(p, {"t1": {"no": 1, "email": "a@b.c", "seen": 5},
                           "": {"no": 2}, "t3": "junk",
                           "t4": {"no": 0, "email": "", "seen": 0}})
    assert store.load_aliases(p) == {"t1": {"no": 1, "email": "a@b.c", "seen": 5}}
    store.save_aliases(p, {"t2": {"no": 2, "email": "a2@b.c", "seen": 1}})
    assert set(store.load_aliases(p)) == {"t1", "t2"}   # merge keeps earlier tabs


def test_load_aliases_non_dict_doc_returns_empty(tmp_path):
    p = tmp_path / "cd.json"
    p.write_text(json.dumps({"aliases": []}), encoding="utf-8")
    assert store.load_aliases(p) == {}


def test_sort_key_guards_junk_values():
    assert store._entry_sort_key(("k", "junk")) == 0
    assert store._entry_sort_key(("k", {"cooldown_until": "not-a-number"})) == 0


def test_saved_jobs_bool_is_zero():
    assert store._saved_jobs(True) == 0


def test_merge_page_stats_skips_blank_url():
    stats = {}
    store._merge_page_stats(stats, {"url": "", "jobs_completed": 3})
    assert stats == {}


def test_save_pool_snapshot_skips_junk_pages(tmp_path):
    p = tmp_path / "cd.json"

    class FakePool:
        def status_snapshot(self):
            return {"pages": ["junk", {},
                              {"tab_id": "t1", "url": "https://arena.ai/c",
                               "cooldown_until": time.time() + 60}]}

    store.save_pool_snapshot(p, FakePool())
    assert "t1" in store.load_entries(p)


def test_consume_entry_for_skips_non_dict_entries():
    entries = {"junk": "nope",
               "k": {"url": "https://arena.ai/c", "cooldown_until": time.time() + 30}}
    key, entry = store.consume_entry_for(entries, "", "https://arena.ai/c")
    assert key == "k" and "junk" in entries   # junk row survived, match consumed
