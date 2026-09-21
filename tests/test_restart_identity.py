"""Both halves of a tab's identity survive a restart (RED-first).

User decision: the 4-digit number is persisted per tab (next to the already
persisted cooldowns), so `marnikus@gmail.com_3045` still means that tab
tomorrow. The same file must also stop losing a *live timer* that sits on a
page whose status was clobbered — today `_persistable` keys on
`status == "cooldown"`, so such a timer is never written (F-4).
"""

import json
import time

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.core.tab_alias import AliasBook
from app.persistence import cooldown_store as store

pytestmark = pytest.mark.integration


def write_doc(path, entries=None, stats=None, aliases=None):
    doc = {"version": 1, "entries": entries or {}, "stats": stats or {}}
    if aliases is not None:
        doc["aliases"] = aliases
    path.write_text(json.dumps(doc), encoding="utf-8")


def make_pool(tab_id="t1", owner="", no=0, book=None):
    pool = PagePool(alias_book=book or (AliasBook({tab_id: {"no": no}}) if no else AliasBook()))
    pool.add_page(PageInfo(tab_id=tab_id, ws_url=f"ws://x/{tab_id}", is_connected=True,
                           url="https://arena.ai/", status=PageStatus.STEADY))
    if owner:
        pool.get_page(tab_id).owner = owner
    return pool


# ---- aliases section ------------------------------------------------------

def test_save_pool_snapshot_writes_the_alias_section(tmp_path):
    path = tmp_path / "cooldowns.json"
    pool = make_pool("t1", owner="marnikus@gmail.com", no=3045)
    store.save_pool_snapshot(path, pool)
    aliases = store.load_aliases(path)
    assert aliases["t1"]["no"] == 3045
    assert aliases["t1"]["email"] == "marnikus@gmail.com"


def test_aliases_survive_an_idle_pool(tmp_path):
    """F-7: the number must not be evicted with the timer (entries are pruned)."""
    path = tmp_path / "cooldowns.json"
    store.save_pool_snapshot(path, make_pool("t1", owner="m@gmail.com", no=3045))
    later = make_pool("t1", owner="m@gmail.com", no=3045)   # new session, no timer at all
    store.save_pool_snapshot(path, later)
    assert store.load_entries(path) == {}                  # no timer: nothing persisted there
    assert store.load_aliases(path)["t1"]["no"] == 3045     # the id is still known


def test_a_known_number_is_reused_and_the_next_one_continues(tmp_path):
    path = tmp_path / "cooldowns.json"
    write_doc(path, aliases={"t1": {"no": 3045, "email": "m@gmail.com"}})
    pool = make_pool("t2", book=AliasBook(store.load_aliases(path)))   # startup: read once
    store.save_pool_snapshot(path, pool)
    aliases = store.load_aliases(path)
    assert aliases["t1"]["no"] == 3045          # untouched, although the tab is gone
    assert aliases["t2"]["no"] == 3046          # continues above the persisted maximum


def test_save_entries_preserves_the_alias_section(tmp_path):
    path = tmp_path / "cooldowns.json"
    write_doc(path, aliases={"t1": {"no": 7, "email": "m@gmail.com"}},
              stats={"https://arena.ai": {"jobs_completed": 2}})
    store.save_entries(path, {"t2": {"tab_id": "t2", "cooldown_until": time.time() + 60}})
    assert store.load_aliases(path)["t1"]["no"] == 7
    assert store.load_stats(path)["https://arena.ai"]["jobs_completed"] == 2


def test_the_alias_section_is_capped_and_sorted_by_recency(tmp_path):
    path = tmp_path / "cooldowns.json"
    aliases = {f"t{i}": {"no": i + 1, "email": "m@gmail.com", "seen": i} for i in range(store.MAX_ALIASES + 25)}
    write_doc(path, aliases=aliases)
    pool = make_pool("fresh", owner="m@gmail.com")
    store.save_pool_snapshot(path, pool)
    kept = store.load_aliases(path)
    assert len(kept) == store.MAX_ALIASES
    assert "fresh" in kept
    assert "t0" not in kept            # the oldest number is the one that goes


def test_loading_junk_aliases_yields_nothing(tmp_path):
    path = tmp_path / "cooldowns.json"
    write_doc(path, aliases={"t1": {"no": "x"}, "t2": 5, "t3": {"no": 99999}, "t4": {"no": 3}})
    assert store.load_aliases(path) == {"t4": {"no": 3, "email": "", "seen": 0.0}}


def test_a_corrupt_file_never_breaks_the_pool(tmp_path):
    path = tmp_path / "cooldowns.json"
    path.write_text("{not json", encoding="utf-8")
    assert store.load_aliases(path) == {}
    assert store.load_entries(path) == {}


# ---- the live timer on a clobbered status (F-4) ---------------------------

def test_a_live_timer_is_persisted_whatever_the_status_says(tmp_path):
    path = tmp_path / "cooldowns.json"
    pool = make_pool("t1")
    page = pool.get_page("t1")
    page.cooldown_until = time.time() + 300     # live timer, status steady (clobbered)
    store.save_pool_snapshot(path, pool)
    entries = store.load_entries(path)
    assert entries["t1"]["cooldown_until"] > time.time()
    assert entries["t1"]["reason"] == ""


def test_an_expired_timer_without_a_debt_is_still_pruned(tmp_path):
    path = tmp_path / "cooldowns.json"
    pool = make_pool("t1")
    pool.get_page("t1").cooldown_until = time.time() - 1
    store.save_pool_snapshot(path, pool)
    assert store.load_entries(path) == {}
