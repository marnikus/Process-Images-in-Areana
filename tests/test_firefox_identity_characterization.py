"""Characterization — identity + Chrome behaviour pinned BEFORE the Firefox name work.

Written first (RULE 16.5: lock legacy behaviour before touching it). These
pins must stay green through the Firefox account-name / overlay change:

* the pool key of a Firefox tab is the stable `{profileDir}_tab{N}` id and a
  rejoin never burns a new worker number or alias number (identity ≠ display);
* two profiles on the same URL stay two workers;
* the Chrome label keeps its `{email}_{4 digits}` / `aka_{4 digits}` shape;
* the Chrome worker badge JS is byte-identical (golden digests captured at
  f5cb06e, before `worker_badge` was refactored to share its body).
"""

import hashlib

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo
from app.browser.uivision import pool_tabs as pt
from app.browser.worker_badge import (
    WorkerBadgeSpec,
    build_worker_badge_clear_js,
    build_worker_badge_js,
)

pytestmark = pytest.mark.unit


def _pool():
    return PagePool(logger=lambda m, l="info": None)


def _ff(tab_id="9THrgpBc.Profile1_tab6", profile="Profile1", url="https://arena.ai/c/1"):
    return pt.FirefoxTab(id=tab_id, url=url, title="Arena", profile=profile,
                         profile_dir=f"/p/{tab_id.split('_tab')[0]}", ws_url=pt.ws_for(tab_id))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_firefox_pool_key_is_the_stable_profile_tab_id():
    pool = _pool()
    pool.add_page(pt.page_for(_ff()))
    assert list(pool._pages) == ["9THrgpBc.Profile1_tab6"]


def test_firefox_rejoin_keeps_worker_and_alias_numbers():
    pool = _pool()
    pool.add_page(pt.page_for(_ff()))
    page = pool.get_page("9THrgpBc.Profile1_tab6")
    before = (page.worker_no, page.alias_no)
    pool.add_page(pt.page_for(_ff(url="https://arena.ai/c/2")))
    assert (page.worker_no, page.alias_no) == before
    assert len(pool._pages) == 1


def test_same_url_in_two_profiles_stays_two_workers():
    pool = _pool()
    pool.add_page(pt.page_for(_ff("A.P1_tab1", "P1")))
    pool.add_page(pt.page_for(_ff("B.P2_tab1", "P2")))
    numbers = {p.worker_no for p in pool._pages.values()}
    assert len(pool._pages) == 2 and numbers == {1, 2}


def test_chrome_label_shape_is_unchanged():
    pool = _pool()
    pool.add_page(PageInfo(tab_id="c1", ws_url="ws://x/c1"))
    page = pool.get_page("c1")
    assert page.alias == "aka_0001" and page.label == "aka_0001"
    page.owner = "marnikus@gmail.com"
    assert page.alias == "marnikus@gmail.com_0001"


def test_chrome_badge_js_is_byte_identical():
    assert _sha(build_worker_badge_js(WorkerBadgeSpec(3, "marnikus@gmail.com_0003"))) == \
        "6b6c826c6af8abab4f426b790b2e26f3fd2cb0ca8fc8314a0a8a41b5fde487e9"
    assert _sha(build_worker_badge_js(WorkerBadgeSpec(1, "abc", "Title <x>"))) == \
        "03c9af7a25c996992d6178eb2e34e87fd6d79a3669af26f251eeb3b26ecd1cab"
    assert _sha(build_worker_badge_clear_js()) == \
        "98f0d49ef71456c499791bd23a94424873b69926d71d5c30b8ce809d329f2277"
