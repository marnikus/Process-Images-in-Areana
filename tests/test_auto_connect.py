"""Tests for app/services/auto_connect.py — auto-connect planning.

RULE 8: real TabInfo + real PagePool; no Qt, no network.
Planner is pure: (tabs, pattern, rows, pooled) -> add/claim/connect/stale.
"""

import pytest

from app.browser.cdp_protocol import TabInfo
from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.services import auto_connect as ac


def tab(tid, url, ws=None, title="T"):
    return TabInfo(id=tid, title=f"{title}-{tid}", url=url,
                   ws_url=ws or f"ws://127.0.0.1:9223/devtools/page/{tid}")


def row(rid, url, tab_id=""):
    return {"id": rid, "url": url, "tab_id": tab_id}


A1 = "https://arena.ai/image/direct?model=a"
A2 = "https://arena.ai/image/direct?model=b"
A1_DUP = "https://arena.ai/image/direct?model=a"


@pytest.mark.unit
def test_matches_pattern():
    assert ac.matches_pattern(A1, "arena.ai") is True
    assert ac.matches_pattern(A1, "ARENA.AI") is True
    assert ac.matches_pattern("https://other.example/", "arena.ai") is False
    assert ac.matches_pattern(A1, "") is True  # blank filter = match all
    assert ac.matches_pattern(A1, "   ") is True
    assert ac.matches_pattern("", "arena.ai") is False


@pytest.mark.unit
def test_plan_adds_unknown_and_connects():
    plan = ac.plan_auto_connect([tab("t1", A1)], "arena.ai", [], set())
    assert plan.add == [(A1, "t1")]
    assert plan.claim == []
    assert len(plan.connect) == 1 and "t1" in plan.connect[0]
    assert plan.stale == []


@pytest.mark.unit
def test_plan_claims_unlinked_same_url_row():
    rows = [row("r1", A1)]
    plan = ac.plan_auto_connect([tab("t1", A1)], "arena.ai", rows, set())
    assert plan.add == []
    assert plan.claim == [("r1", "t1")]
    assert len(plan.connect) == 1


@pytest.mark.unit
def test_plan_linked_and_pooled_is_noop():
    rows = [row("r1", A1, "t1")]
    plan = ac.plan_auto_connect([tab("t1", A1)], "arena.ai", rows, {"t1"})
    assert plan.add == [] and plan.claim == []
    assert plan.connect == [] and plan.stale == []


@pytest.mark.unit
def test_plan_duplicate_urls_distinguished_by_tab_id():
    rows = [row("r1", A1_DUP, "t1")]
    tabs = [tab("t1", A1_DUP), tab("t2", A1_DUP)]
    plan = ac.plan_auto_connect(tabs, "arena.ai", rows, {"t1"})
    assert plan.add == [(A1_DUP, "t2")]  # second tab, same URL -> own row
    assert plan.claim == []
    assert len(plan.connect) == 1 and "t2" in plan.connect[0]


@pytest.mark.unit
def test_plan_skips_devtools_pattern_mismatch_and_keyless():
    tabs = [tab("t1", "devtools://x"), tab("t2", "https://other.example/"),
            TabInfo(id="", title="", url=A1, ws_url="")]
    plan = ac.plan_auto_connect(tabs, "arena.ai", [], set())
    assert plan.add == [] and plan.connect == []


@pytest.mark.unit
def test_plan_stale_is_pattern_independent():
    rows = [row("r1", A1, "t1"), row("r9", "https://other.example/", "t9")]
    tabs = [tab("t1", A1), tab("t9", "https://other.example/")]
    plan = ac.plan_auto_connect(tabs, "arena.ai", rows, {"t1", "t9", "gone"})
    assert plan.stale == ["gone"]  # navigated-away t9 still live, only closed tab stale


@pytest.mark.unit
def test_sync_pool_presence_flags_and_revives():
    pool = PagePool()
    pool.add_page(PageInfo(tab_id="a", title="A", url=A1, is_connected=True))
    pool.add_page(PageInfo(tab_id="b", title="B", url=A2, is_connected=True))
    revived, stale = ac.sync_pool_presence(pool, {"a"})
    assert revived == 0 and stale == ["b"]
    assert pool.get_page("b").is_connected is False
    assert pool.get_page("b").is_free() is False  # stale tab excluded from dispatch
    revived, stale = ac.sync_pool_presence(pool, {"a", "b"})
    assert revived == 1 and stale == []
    assert pool.get_page("b").is_connected is True


@pytest.mark.unit
def test_sync_pool_presence_tolerates_garbage():
    assert ac.sync_pool_presence(None, {"a"}) == (0, [])
    pool = PagePool()
    assert ac.sync_pool_presence(pool, None) == (0, [])


@pytest.mark.unit
def test_live_tab_keys_skips_devtools_and_keyless():
    tabs = [tab("t1", A1), tab("t2", "devtools://x"),
            TabInfo(id="", title="", url=A2, ws_url="")]
    assert ac.live_tab_keys(tabs) == {"t1"}
    assert ac.live_tab_keys(None) == set()


@pytest.mark.unit
def test_prunable_row_ids_only_linked_gone():
    rows = [row("r1", A1, "t1"), row("r2", A2, "gone"),
            row("r3", A2), row("r4", "https://other.example/", "t9")]
    assert ac.prunable_row_ids(rows, {"t1", "t9"}) == ["r2"]
    assert ac.prunable_row_ids(rows, None) == ["r1", "r2", "r4"]
    assert ac.prunable_row_ids(None, {"t1"}) == []


@pytest.mark.unit
def test_plan_remove_defaults_empty():
    plan = ac.plan_auto_connect([tab("t1", A1)], "arena.ai", [row("r9", A1, "gone")], set())
    assert plan.remove == []  # bridge fills it only when pruning is safe


@pytest.mark.unit
def test_pick_primary_ws():
    from types import SimpleNamespace
    assert ac.pick_primary_ws(None) == ""
    assert ac.pick_primary_ws([]) == ""
    pages = [SimpleNamespace(ws_url="", is_connected=True),
             SimpleNamespace(ws_url="ws://dead", is_connected=False),
             SimpleNamespace(ws_url="ws://live1", is_connected=True),
             SimpleNamespace(ws_url="ws://live2", is_connected=True)]
    assert ac.pick_primary_ws(pages) == "ws://live1"
    assert ac.pick_primary_ws([SimpleNamespace(ws_url="ws://x")]) == ""
