"""Worker sequential number — pool join order, stable for the session (D-3).

`PagePool.add_page` assigns `PageInfo.worker_no` 1, 2, 3 … on a tab's FIRST
join; a revived tab keeps its number; a removed tab's number is never reused.
The number rides `to_dict()` → `status_snapshot()` → `page_pool_updated`, so
the JS only displays it.

RED at base: `AttributeError: 'PageInfo' object has no attribute 'worker_no'`.
"""

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo

pytestmark = pytest.mark.unit


def pool_with(*tabs):
    pool = PagePool(logger=lambda m, l="info": None)
    for tid in tabs:
        pool.add_page(PageInfo(tab_id=tid, ws_url=f"ws://x/{tid}", title="T", url="https://arena.ai"))
    return pool


def test_join_order_numbers_workers_from_one():
    pool = pool_with("a", "b", "c")
    assert [pool.get_page(t).worker_no for t in ("a", "b", "c")] == [1, 2, 3]


def test_a_revived_tab_keeps_its_number():
    pool = pool_with("a", "b")
    pool.get_page("a").is_connected = False
    pool.add_page(PageInfo(tab_id="a", ws_url="ws://x/a", title="T2", url="https://arena.ai/2"))  # revive
    assert pool.get_page("a").worker_no == 1 and pool.get_page("a").is_connected
    assert pool.get_page("a").title == "T2"  # the revive still refreshes identity


def test_numbers_are_never_reused_after_removal():
    pool = pool_with("a", "b")
    assert pool.remove_page("a") is True
    pool.add_page(PageInfo(tab_id="c", ws_url="ws://x/c"))
    assert pool.get_page("c").worker_no == 3
    pool.add_page(PageInfo(tab_id="a", ws_url="ws://x/a"))  # comes back after removal: a new worker
    assert pool.get_page("a").worker_no == 4


def test_default_is_zero_until_the_pool_assigns():
    info = PageInfo(tab_id="x")
    assert info.worker_no == 0
    assert PageInfo(tab_id="y", worker_no=7).to_dict()["worker_no"] == 7


def test_the_number_rides_the_snapshot():
    pool = pool_with("a", "b")
    pages = {p["tab_id"]: p for p in pool.status_snapshot()["pages"]}
    assert (pages["a"]["worker_no"], pages["b"]["worker_no"]) == (1, 2)
    assert "cooldown_remaining" in pages["a"]  # the snapshot entry is still the full one
