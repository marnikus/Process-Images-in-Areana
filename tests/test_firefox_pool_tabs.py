"""Firefox pool integration (2026-09-25) — stable ids, listing, join, identity.

Owner brief §2.2/§3.1: a Firefox tab's id is `{profile-dir-basename}_tab{N}`
and must be STABLE across rescans; the listing carries every open tab of every
checked OPEN profile (pattern filtering stays the planner's job — RULE 10);
joining goes through the same PagePool as Chrome with `browser="firefox"` and
the profile attribution on the entry.

RED at base: `ModuleNotFoundError: app.browser.uivision.pool_tabs`.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.uivision import pool_tabs as pt

pytestmark = pytest.mark.unit


def session(dir_, rows, name=""):
    return {"name": name, "dir": str(dir_), "rows": list(rows), "windows": [],
            "source": "sessionstore.jsonlz4", "stamp": 1.0}


def sessions_two_profiles(tmp_path):
    d1 = tmp_path / "9THrgpBc.Profile1"
    d2 = tmp_path / "ab12cd34.default"
    d1.mkdir(exist_ok=True)
    d2.mkdir(exist_ok=True)
    return [
        session(d1, [{"url": "https://arena.ai/c/1", "title": "A"},
                     {"url": "https://arena.ai/c/2", "title": "B"}], name="P1"),
        session(d2, [{"url": "https://arena.ai/c/1", "title": "Same URL elsewhere"}]),
    ]


def test_tab_id_is_dir_basename_plus_flat_index():
    assert pt.tab_id_for("/home/u/.mozilla/firefox/9THrgpBc.Profile1", 6) == "9THrgpBc.Profile1_tab6"
    assert pt.tab_id_for(str(Path("C:/x/ab12cd34.default")), 1) == "ab12cd34.default_tab1"


def _all_open(monkeypatch):
    """The lock probe decides liveness (bug #4) — tests say 'every profile is open'."""
    monkeypatch.setattr(pt.profiles, "open_sessions", lambda sessions, in_use=None: sessions)


def test_tab_ids_are_stable_across_rescans(tmp_path, monkeypatch):
    sessions = sessions_two_profiles(tmp_path)
    monkeypatch.setattr(pt.tabs, "profile_sessions", lambda profiles=None: sessions)
    _all_open(monkeypatch)
    first = [t.id for t in pt.firefox_rows()]
    monkeypatch.setattr(pt.tabs, "profile_sessions", lambda profiles=None: sessions)
    second = [t.id for t in pt.firefox_rows()]
    assert first == second
    assert first == ["9THrgpBc.Profile1_tab1", "9THrgpBc.Profile1_tab2",
                     "ab12cd34.default_tab1"]


def test_same_url_in_two_profiles_gets_two_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(pt.tabs, "profile_sessions",
                        lambda profiles=None: sessions_two_profiles(tmp_path))
    _all_open(monkeypatch)
    ids = {t.id for t in pt.firefox_rows()}
    assert len(ids) == 3
    assert sum(1 for i in ids if i.startswith("9THrgpBc.Profile1_")) == 2


def test_row_shape_carries_the_planner_attributes(tmp_path, monkeypatch):
    monkeypatch.setattr(pt.tabs, "profile_sessions",
                        lambda profiles=None: sessions_two_profiles(tmp_path))
    _all_open(monkeypatch)
    tabs = pt.firefox_rows()
    tab = tabs[0]
    assert tab.url == "https://arena.ai/c/1" and tab.title == "A"
    assert tab.ws_url == f"firefox://{tab.id}"      # plan.connect sentinel
    assert tab.profile == "P1" and tab.profile_dir.endswith("9THrgpBc.Profile1")
    # ALL tabs list — non-matching URLs included (the planner applies url_pattern)
    assert any(t.url == "https://arena.ai/c/2" for t in tabs)


def test_closed_profiles_are_never_listed(tmp_path, monkeypatch):
    monkeypatch.setattr(pt.tabs, "profile_sessions",
                        lambda profiles=None: sessions_two_profiles(tmp_path))
    monkeypatch.setattr(pt.profiles, "open_sessions",
                        lambda sessions, in_use=None: sessions[:1])
    ids = [t.id for t in pt.firefox_rows()]
    assert ids and all(i.startswith("9THrgpBc.Profile1_") for i in ids)


def test_find_tab_returns_none_for_gone_tab(tmp_path, monkeypatch):
    monkeypatch.setattr(pt.tabs, "profile_sessions",
                        lambda profiles=None: sessions_two_profiles(tmp_path))
    _all_open(monkeypatch)
    assert pt.find_tab("9THrgpBc.Profile1_tab1") is not None
    assert pt.find_tab("9THrgpBc.Profile1_tab99") is None


def test_sentinel_roundtrip():
    ws = pt.ws_for("9THrgpBc.Profile1_tab6")
    assert pt.is_firefox_ws(ws) and not pt.is_firefox_ws("ws://127.0.0.1:9222/devtools/page/x")
    assert pt.tab_id_from_ws(ws) == "9THrgpBc.Profile1_tab6"
    assert pt.tab_id_from_ws("ws://x") == ""


def test_firefox_page_info_defaults_and_wire_form():
    tab = pt.FirefoxTab(id="P_tab1", url="https://arena.ai", title="A",
                        profile="P1", profile_dir="/x/P1", ws_url="firefox://P_tab1")
    page = pt.page_for(tab)
    assert page.browser == "firefox" and page.tab_id == "P_tab1"
    assert page.profile == "P1" and page.profile_dir == "/x/P1"
    wire = page.to_dict()
    assert wire["browser"] == "firefox" and wire["profile"] == "P1"
    assert wire["tab_id"] == "P_tab1"


def test_join_numbers_the_tab_like_every_pool_member():
    pool = PagePool(logger=lambda m, l="info": None)
    tab = pt.FirefoxTab(id="P_tab1", url="https://arena.ai", title="A",
                        profile="P", profile_dir="/x/P", ws_url="firefox://P_tab1")
    pool.add_page(pt.page_for(tab))
    pool.add_page(pt.page_for(tab))          # rejoin revives, never double-numbers
    page = pool.get_page("P_tab1")
    assert page is not None and page.alias_no == 1
    assert page.is_free()                    # steady + connected + no timer
    total, free = pool.get_counts()
    assert (total, free) == (1, 1)
    # no CDP client — every client consumer must see (None, None)
    assert pool.get_clients("P_tab1") == (None, None)


def test_pattern_filter_is_the_planners_job_not_the_listing(tmp_path, monkeypatch):
    """A blank/foreign URL still appears in the listing (D1: one filter, RULE 10)."""
    monkeypatch.setattr(pt.tabs, "profile_sessions", lambda profiles=None: [
        session(tmp_path / "d.default", [{"url": "https://other.example/x", "title": "X"}])])
    monkeypatch.setattr(pt.profiles, "open_sessions", lambda sessions, in_use=None: sessions)
    rows = pt.firefox_rows()
    assert [t.url for t in rows] == ["https://other.example/x"]
