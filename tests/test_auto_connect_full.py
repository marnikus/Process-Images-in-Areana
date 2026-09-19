"""D5 mutation triage: auto_connect internals, branch-complete.

Targets _live_tabs (14), _tab_key (10), _row_action (9), plan_auto_connect (8),
prunable_row_ids (6), _wins_over (6), pick_primary_ws (4), matches_pattern (3),
_row_index (3), _best_per_tab (3) + ownership/run-gate helpers.
"""

import threading
from types import SimpleNamespace

from app.services.auto_connect import (
    _best_per_tab,
    _claim_matches,
    _claimable_tid,
    _live_tabs,
    _row_index,
    _row_action,
    _tab_key,
    _wins_over,
    claim_unlinked_from_pool,
    counts_in,
    dedupe_linked_rows,
    enabled_tab_ids,
    live_tab_keys,
    matches_pattern,
    pick_primary_ws,
    pick_url_for_tab,
    plan_auto_connect,
    prunable_row_ids,
    row_for_tab,
    sync_pool_presence,
)


def tab(id="", url="", title="", ws=""):
    return SimpleNamespace(id=id, url=url, title=title, ws_url=ws)


class TestMatchesPattern:
    def test_blank_pattern_matches_all_urls(self):
        assert matches_pattern("https://x.test", "") is True
        assert matches_pattern("https://x.test", "   ") is True
        assert matches_pattern("https://x.test", None) is True
        assert matches_pattern("https://x.test", 5) is True

    def test_substring_case_insensitive(self):
        assert matches_pattern("https://Arena.AI/x", "arena") is True
        assert matches_pattern("https://x.test", "y.test") is False

    def test_bad_urls(self):
        assert matches_pattern("", "x") is False
        assert matches_pattern(None, "x") is False
        assert matches_pattern(42, "x") is False


class TestTabKeyAndLiveTabs:
    def test_tab_key(self):
        assert _tab_key(tab(id="A")) == "A"
        assert _tab_key(tab(id="", ws="ws1")) == "ws1"
        assert _tab_key(tab()) == ""
        assert _tab_key(SimpleNamespace(url="x")) == ""

    def test_live_tabs(self):
        t1, t2, t3, t4 = (
            tab(id="A", url="https://a.test"),
            tab(id="A", url="https://a.test"),        # duplicate key
            tab(id="", url="https://b.test"),          # keyless
            tab(id="C", url="devtools://x"),           # devtools
        )
        live = _live_tabs([t1, t2, t3, t4])
        assert live == [t1]

    def test_live_tabs_none(self):
        assert _live_tabs(None) == []

    def test_live_tabs_by_ws_fallback(self):
        live = _live_tabs([tab(id="", ws="w1", url="https://a.test"),
                           tab(id="", ws="w1", url="https://a.test")])
        assert len(live) == 1

    def test_live_tab_keys(self):
        # key = id, else ws_url; empty-URL tabs count as devtools (skipped)
        assert live_tab_keys([
            tab(id="A", url="https://a.test"),
            tab(id="", ws="w", url="https://b.test"),
            tab(id="A", url="https://a.test"),
            tab(id="D", url="devtools://x"),
        ]) == {"A", "w"}
        assert live_tab_keys([tab(id="A")]) == set()


class TestRowIndexAndAction:
    def test_row_index(self):
        rows = [
            {"id": "r1", "url": "https://a.test", "tab_id": "T1"},
            {"id": "r2", "url": "https://b.test"},
            {"id": "r3", "url": "https://b.test"},   # dup unlinked: first wins
            {"id": "r4", "url": ""},
        ]
        by_tab, unlinked = _row_index(rows)
        assert by_tab == {"T1": rows[0]}
        assert unlinked["https://b.test"] is rows[1]
        assert unlinked[""] is rows[3]

    def test_row_index_none(self):
        by_tab, unlinked = _row_index(None)
        assert by_tab == {} and unlinked == {}

    def test_row_action_linked_is_none(self):
        action = _row_action({"T1": {"id": "r"}}, {}, tab(id="T1", url="u"), "T1")
        assert action is None

    def test_row_action_claim(self):
        action = _row_action({}, {"u": {"id": "r9"}}, tab(id="T2", url="u"), "T2")
        assert action == ("claim", "r9")

    def test_row_action_add(self):
        action = _row_action({}, {}, tab(id="T3", url="u"), "T3")
        assert action == ("add",)


class TestPlan:
    def test_mixed(self):
        tabs_ = [
            tab(id="T1", url="https://a.test", ws="ws1"),
            tab(id="T2", url="https://b.test", ws="ws2"),
            tab(id="T3", url="https://c.test", ws="ws3"),
            tab(id="T4", url="https://d.test", ws="ws4"),
        ]
        rows = [
            {"id": "r1", "url": "https://a.test", "tab_id": "T1"},   # linked
            {"id": "r2", "url": "https://b.test"},                    # claimable
        ]
        plan = plan_auto_connect(tabs_, ".test", rows, pooled=["T1", "GONE"])
        assert plan.add == [("https://c.test", "T3"), ("https://d.test", "T4")]
        assert plan.claim == [("r2", "T2")]
        assert plan.connect == ["ws2", "ws3", "ws4"]
        assert plan.stale == ["GONE"]

    def test_pattern_mismatch_skips_action_and_connect(self):
        tabs_ = [tab(id="T1", url="https://zzz.test", ws="ws1")]
        plan = plan_auto_connect(tabs_, "a.test", [], pooled=[])
        assert plan.add == [] and plan.claim == [] and plan.connect == []

    def test_duplicate_urls_different_tabs(self):
        tabs_ = [tab(id="T1", url="https://a.test", ws="ws1"),
                 tab(id="T2", url="https://a.test", ws="ws2")]
        rows = [{"id": "r1", "url": "https://a.test"}]
        plan = plan_auto_connect(tabs_, "", rows, pooled=[])
        assert plan.claim == [("r1", "T1")]
        assert plan.add == [("https://a.test", "T2")]

    def test_pooled_tab_not_connected_again(self):
        tabs_ = [tab(id="T1", url="https://a.test", ws="ws1")]
        plan = plan_auto_connect(tabs_, "", [], pooled=["T1"])
        assert plan.connect == []
        assert plan.stale == []


class TestPresence:
    def make_pool(self, pages):
        return SimpleNamespace(_pages=pages, _lock=threading.Lock())

    def test_flags_and_revives(self):
        p1, p2, p3 = (
            SimpleNamespace(is_connected=True),
            SimpleNamespace(is_connected=True),
            SimpleNamespace(is_connected=False),
        )
        pool = self.make_pool({"A": p1, "B": p2, "C": p3})
        revived, stale = sync_pool_presence(pool, {"A", "C"})
        assert revived == 1
        assert stale == ["B"]
        assert p1.is_connected is True
        assert p2.is_connected is False
        assert p3.is_connected is True

    def test_garbage_pool(self):
        assert sync_pool_presence(object(), {"A"}) == (0, [])
        assert sync_pool_presence(None, {"A"}) == (0, [])

    def test_none_live_ids(self):
        p1 = SimpleNamespace(is_connected=True)
        revived, stale = sync_pool_presence(self.make_pool({"A": p1}), None)
        assert (revived, stale) == (0, ["A"])
        assert p1.is_connected is False


class TestOwnership:
    def test_wins_over(self):
        assert _wins_over({"enabled": True}, {"enabled": False}) is True
        assert _wins_over({"enabled": False}, {"enabled": True}) is False
        assert _wins_over({"enabled": True}, {"enabled": True}) is False
        assert _wins_over({}, {"enabled": False}) is False
        assert _wins_over({"enabled": True}, {}) is True

    def test_best_per_tab(self):
        rows = [
            {"id": "a", "tab_id": "T1", "enabled": False},
            {"id": "b", "tab_id": "T1", "enabled": True},
            {"id": "c", "tab_id": "T2", "enabled": False},
            {"id": "d", "tab_id": "", "enabled": True},
        ]
        best = _best_per_tab(rows)
        assert best["T1"] is rows[1]
        assert best["T2"] is rows[2]
        assert "" not in best

    def test_dedupe(self):
        rows = [
            {"id": "a", "tab_id": "T1", "enabled": False},
            {"id": "b", "tab_id": "T1", "enabled": True},
            {"id": "c", "tab_id": "T2", "enabled": True},
            {"id": "d"},
            "junk",
            42,
        ]
        kept, dropped = dedupe_linked_rows(rows)
        assert [r["id"] for r in kept] == ["b", "c", "d"]
        assert [r["id"] for r in dropped] == ["a"]

    def test_dedupe_none_rows(self):
        assert dedupe_linked_rows(None) == ([], [])

    def test_enabled_tab_ids(self):
        urls = [SimpleNamespace(enabled=True, tab_id="T1"),
                SimpleNamespace(enabled=False, tab_id="T2"),
                SimpleNamespace(enabled=True, tab_id="")]
        assert enabled_tab_ids(urls) == {"T1"}
        assert enabled_tab_ids(None) == set()

    def test_row_for_tab(self):
        u1 = SimpleNamespace(enabled=True, tab_id="T1")
        u2 = SimpleNamespace(enabled=False, tab_id="T1")
        assert row_for_tab([u2, u1], "T1") is u1
        assert row_for_tab([u2], "T1") is None
        assert row_for_tab([u1], "") is None
        assert row_for_tab(None, "T1") is None

    def test_pick_url_for_tab(self):
        owner = SimpleNamespace(enabled=True, tab_id="T1")
        other = SimpleNamespace(enabled=True, tab_id="T2")
        assert pick_url_for_tab([other, owner], "T1") is owner
        assert pick_url_for_tab([other], "T9") is other
        assert pick_url_for_tab([SimpleNamespace(enabled=False)], "T9") is None
        assert pick_url_for_tab(None, "T9") is None


class FakePage:
    def __init__(self, tab_id="", is_connected=True, free=True, url=""):
        self.tab_id = tab_id
        self.is_connected = is_connected
        self._free = free
        self.url = url
        self.expired = 0

    def try_expire(self):
        self.expired += 1

    def is_free(self):
        return self._free


class TestCountsAndClaim:
    def make_pool(self, pages):
        return SimpleNamespace(_pages={p.tab_id: p for p in pages},
                               _lock=threading.Lock())

    def test_counts_in(self):
        pages = [FakePage("A", free=True), FakePage("B", free=False),
                 FakePage("C", free=True)]
        total, free = counts_in(self.make_pool(pages), {"A", "B"})
        assert (total, free) == (2, 1)
        assert all(p.expired == 1 for p in pages)

    def test_counts_in_garbage(self):
        assert counts_in(object(), {"A"}) == (0, 0)
        assert counts_in(None, set()) == (0, 0)

    def test_counts_in_empty_allowed(self):
        total, free = counts_in(self.make_pool([FakePage("A")]), set())
        assert (total, free) == (0, 0)

    def test_claimable_tid(self):
        assert _claimable_tid(None, set()) == ""
        assert _claimable_tid({}, set()) == ""
        assert _claimable_tid({"tab_id": ""}, set()) == ""
        assert _claimable_tid({"tab_id": "A", "is_connected": True}, set()) == "A"
        assert _claimable_tid({"tab_id": "A", "is_connected": True}, {"A"}) == ""
        assert _claimable_tid({"tab_id": "A", "is_connected": False}, set()) == ""
        # missing is_connected defaults to claimable
        assert _claimable_tid({"tab_id": "B"}, set()) == "B"

    def test_claim_matches(self):
        row = SimpleNamespace(url="https://arena.ai/app/1")
        assert _claim_matches(row, {"url": "https://arena.ai/app/1"}) is True
        assert _claim_matches(row, {"url": "https://arena.ai/app/2"}) is False
        assert _claim_matches(row, None) is False

    def test_claim_unlinked_from_pool(self):
        row1 = SimpleNamespace(enabled=True, tab_id="", url="https://arena.ai/app/1")
        row2 = SimpleNamespace(enabled=False, tab_id="", url="https://arena.ai/app/2")
        row3 = SimpleNamespace(enabled=True, tab_id="T9", url="https://arena.ai/app/3")
        pages = [
            {"tab_id": "P1", "is_connected": True, "url": "https://arena.ai/app/2"},
            {"tab_id": "P2", "is_connected": True, "url": "https://arena.ai/app/1"},
            {"tab_id": "T9", "is_connected": True, "url": "https://arena.ai/app/1"},
        ]
        claimed = claim_unlinked_from_pool([row1, row2, row3], pages)
        assert claimed == 1
        assert row1.tab_id == "P2"
        assert row2.tab_id == ""      # disabled rows never claimed
        assert row3.tab_id == "T9"    # already linked: untouched

    def test_claim_no_match(self):
        row = SimpleNamespace(enabled=True, tab_id="", url="https://other.test/x")
        pages = [{"tab_id": "P1", "is_connected": True, "url": "https://arena.ai/app/1"}]
        assert claim_unlinked_from_pool([row], pages) == 0
        assert claim_unlinked_from_pool(None, pages) == 0

    def test_claim_prefers_first_page(self):
        row = SimpleNamespace(enabled=True, tab_id="", url="https://arena.ai/app/1")
        pages = [
            {"tab_id": "P1", "is_connected": True, "url": "https://arena.ai/app/1"},
            {"tab_id": "P2", "is_connected": True, "url": "https://arena.ai/app/1"},
        ]
        assert claim_unlinked_from_pool([row], pages) == 1
        assert row.tab_id == "P1"
