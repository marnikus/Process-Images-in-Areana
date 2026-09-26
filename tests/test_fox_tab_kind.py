"""I-64 · Pool-key shape → browser / lane, the Firefox alias head, the wire keys.

A Firefox tab id is `{profileDirName}_tab{N}`, anything else is a Chrome CDP id.
The browser and the lane (`cdp` / `uivision`) are DERIVED from the key and
never stored twice (UrlRow keeps no browser field, RULE 13). A tab whose
account cannot be probed is named by its profile (`Profile1_0007`).
"""

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo
from app.core import tab_alias as ta
from app.ui.services.arena_serialize import link_kind, urls_to_js

pytestmark = pytest.mark.unit


def test_firefox_ids_round_trip_and_every_other_shape_is_chrome():
    tab_id = ta.firefox_tab_id("9THrgpBc.Profile1", 6)
    assert tab_id == "9THrgpBc.Profile1_tab6"
    assert ta.split_firefox_id(tab_id) == ("9THrgpBc.Profile1", 6)
    assert ta.tab_browser(tab_id) == ta.FIREFOX
    for other in ("A1B2C3D4E5F6A7B8C9D0E1F2A3B4C5D6", "t1", "", None, 42, "x_tab0", "_tab3", "p_tab"):
        assert ta.tab_browser(other) == ta.CHROME, other
        assert ta.split_firefox_id(other) == ("", 0), other


def test_the_lane_follows_the_recorded_browser_else_the_key():
    assert (ta.conn_of("firefox"), ta.conn_of("chrome"), ta.conn_of("")) == ("uivision", "cdp", "cdp")
    assert ta.page_conn("", "P.x_tab2") == "uivision"
    assert ta.page_conn("chrome", "P.x_tab2") == "cdp"        # a recorded browser wins over the shape
    assert ta.page_conn("", "ABCDEF0123") == "cdp"


def test_the_alias_head_is_the_account_then_the_profile_then_aka():
    assert ta.format_alias("m@gmail.com", 7, "Profile1") == "m@gmail.com_0007"
    assert ta.format_alias("", 7, "Profile1") == "Profile1_0007"
    assert ta.format_alias("", 7, "  Work   Profile 2 ") == "Work-Profile-2_0007"
    assert ta.format_alias("", 7) == "aka_0007"
    assert ta.format_alias("", 0, "Profile1") == ""           # not numbered yet
    assert ta.clean_hint(None) == "" and len(ta.clean_hint("x" * 80)) == ta.HINT_MAX


def test_a_firefox_page_says_who_it_is_on_the_wire():
    page = PageInfo(tab_id="P.Profile1_tab3", browser="firefox", profile="Profile1", alias_no=7, worker_no=2)
    wire = page.to_dict()
    assert (wire["browser"], wire["conn"], wire["profile"], wire["browser_mark"]) == \
        ("firefox", "uivision", "Profile1", "🦊 ")
    assert page.alias == "Profile1_0007" and page.label == "Profile1_0007"
    chrome = PageInfo(tab_id="ABC", browser="chrome", owner="m@gmail.com", alias_no=3).to_dict()
    assert (chrome["conn"], chrome["browser_mark"], chrome["profile"]) == ("cdp", "", "")
    assert {"worker_no", "alias_no", "owner", "ws_url", "cooldown_until"} <= set(chrome)


def test_the_pool_snapshot_labels_a_firefox_worker_by_its_profile():
    pool = PagePool()
    pool.add_page(PageInfo(tab_id="P.Profile1_tab3", title="LMArena", url="https://arena.ai/",
                           browser="firefox", profile="Profile1"))
    entry = pool.status_snapshot()["pages"][0]
    assert entry["tab_label"].startswith("Profile1_") and entry["browser_mark"] == "🦊 "
    assert entry["conn"] == "uivision" and entry["worker_no"] == 1


def test_url_rows_carry_the_derived_lane_and_the_typed_flag():
    assert link_kind("") == {"browser": "", "conn": ""}
    rows = urls_to_js({"urls": [
        {"id": "a", "url": "u", "tab_id": "P.x_tab1", "typed": True},
        {"id": "b", "url": "v", "tab_id": "ABCDEF"},
        {"id": "c", "url": "w"}]})
    assert [(r["browser"], r["conn"], r["typed"]) for r in rows] == [
        ("firefox", "uivision", True), ("chrome", "cdp", False), ("", "", False)]
