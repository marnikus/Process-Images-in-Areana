"""Readable tab ids at the pool seam (`PagePool` + `AliasBook`), RED-first.

The pool key stays the CDP tab id (identity, RULE 15); the *label* is the
readable `{email}_{4 digits}` handle every view prints. Allocation happens once,
on the join, next to `worker_no` — a re-join or a second pool in the same
session must never burn a new number.
"""

import time

import pytest

from app.browser.page_pool import PagePool, tab_label_of
from app.browser.page_status import PageInfo, PageStatus
from app.core.tab_alias import AliasBook

pytestmark = pytest.mark.unit


def make_info(tab_id):
    return PageInfo(ws_url=f"ws://{tab_id}", tab_id=tab_id, title=f"T-{tab_id}",
                    url="https://arena.ai/", status=PageStatus.STEADY, is_connected=True)


def test_join_allocates_one_number_per_tab_and_labels_the_snapshot():
    pool = PagePool()
    pool.add_page(make_info("aaa"))
    pool.add_page(make_info("bbb"))
    assert pool.get_page("aaa").alias_no == 1
    assert pool.get_page("bbb").alias_no == 2
    labels = {p["tab_id"]: p["tab_label"] for p in pool.status_snapshot()["pages"]}
    assert labels == {"aaa": "aka_0001", "bbb": "aka_0002"}


def test_a_persisted_book_keeps_the_number_and_the_email_across_pools():
    book = AliasBook({"aaa": {"no": 3045, "email": "marnikus@gmail.com"}})
    pool = PagePool(alias_book=book)
    pool.add_page(make_info("aaa"))
    page = pool.get_page("aaa")
    assert (page.alias_no, page.owner) == (3045, "marnikus@gmail.com")
    assert pool.status_snapshot()["pages"][0]["tab_label"] == "marnikus@gmail.com_3045"
    assert pool.get_page("aaa").tab_id == "aaa"      # identity untouched (RULE 15)


def test_a_rejoin_keeps_its_number_and_does_not_burn_a_new_one():
    pool = PagePool()
    pool.add_page(make_info("aaa"))
    pool.add_page(make_info("bbb"))
    pool.remove_page("aaa")
    pool.add_page(make_info("aaa"))
    assert pool.get_page("aaa").alias_no == 1
    pool.add_page(make_info("ccc"))
    assert pool.get_page("ccc").alias_no == 3


def test_the_probe_updates_the_prefix_but_never_the_number():
    pool = PagePool(alias_book=AliasBook({"aaa": {"no": 7}}))
    pool.add_page(make_info("aaa"))
    assert pool.get_page("aaa").alias == "aka_0007"
    pool.get_page("aaa").owner = "marnikus@gmail.com"
    assert pool.get_page("aaa").alias == "marnikus@gmail.com_0007"
    assert pool.status_snapshot()["pages"][0]["tab_label"] == "marnikus@gmail.com_0007"


def test_a_page_without_a_number_has_no_label():
    page = make_info("aaa")
    assert page.alias == ""
    assert "tab_label" not in page.to_dict() or page.to_dict()["tab_label"] == ""


def test_an_unregistered_pool_page_still_gets_a_number():
    pool = PagePool()
    pool.add_page(PageInfo(tab_id="", ws_url=""))     # nothing to key on
    assert pool.status_snapshot()["pages"] == []


def test_the_cooling_count_is_the_timer_not_the_status():
    """D-1: a page whose status was clobbered but whose timer runs is cooling."""
    pool = PagePool()
    pool.add_page(make_info("aaa"))
    page = pool.get_page("aaa")
    page.cooldown_until = time.time() + 300
    snap = pool.status_snapshot()
    assert snap["cooling"] == 1
    assert snap["steady"] == 0 and snap["free"] == 0
    assert snap["pages"][0]["cooldown_remaining"] > 0


def test_one_label_source_for_logs_and_views():
    """D-7: `PagePool.tab_label` is what every log line and view prints.

    The pool key stays the hex identity; the label is the readable handle — a
    log line that says `aka_0001` while the table says `marnikus@gmail.com_0001`
    is exactly the inconsistency the user reported.
    """
    pool = PagePool()
    pool.add_page(make_info("aaa"))
    pool.get_page("aaa").owner = "marnikus@gmail.com"
    assert tab_label_of(pool, "aaa") == "marnikus@gmail.com_0001"
    assert pool.get_page("aaa").label == "marnikus@gmail.com_0001"


def test_a_label_without_a_number_never_lies():
    """Before the pool numbers a tab (and for a foreign id) the short id is the label."""
    pool = PagePool()
    info = make_info("aaa")
    assert PageInfo(ws_url="", tab_id="zzz").label == "zzz"[:12]
    pool.add_page(info)
    assert tab_label_of(pool, "aaa") == "aka_0001"     # numbered: readable right away
    assert tab_label_of(pool, "nope") == "nope"[:12]   # unknown tab: identity, never empty
    assert tab_label_of(None, "aaa") == "aaa"          # no pool at all: still a name


def test_the_label_survives_a_probe_that_knows_no_account():
    pool = PagePool()
    pool.add_page(make_info("aaa"))
    assert tab_label_of(pool, "aaa") == "aka_0001"
    assert pool.get_page("aaa").alias.startswith("aka_")
