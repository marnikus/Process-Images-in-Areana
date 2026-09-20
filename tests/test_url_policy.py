"""live.url_policy — rows follow Chrome, with a reason for every removal (S6, D-4 / I-50).

Pure functions over the planner's row dicts (`{id, url, tab_id, enabled}`);
the only real object is a PagePool for the live-job deferral (RULE 15).
`dedupe_rows` / `add_rows` are the moved `url_queue` helpers — equivalence is
pinned through the panel's delegations in `tests/test_url_selection.py`.
"""

import inspect

import pytest

from app.browser.page_pool import PagePool
from app.core.models import UrlRow
from app.services import cooldown_service
from app.services.live import url_policy as up
from app.ui.panels import url_queue
from tests.test_captcha_service import make_info

pytestmark = pytest.mark.unit


def row(rid, url="https://arena.ai/c/1", tab_id="t1", enabled=True):
    return {"id": rid, "url": url, "tab_id": tab_id, "enabled": enabled}


@pytest.mark.parametrize("reason,rows,live,pattern,misses", [
    ("tab_gone", [row("a", tab_id="t1"), row("b", tab_id="t2")], {"t2"}, "arena.ai", {"t1": 2}),
    ("pattern_mismatch", [row("a", url="https://other.example/x", tab_id="t1"), row("b", tab_id="t2")],
     {"t1", "t2"}, "arena.ai", {}),
    ("invalid", [row("a", url="not a url", tab_id="t1"), row("b", tab_id="t2")], {"t1", "t2"}, "", {}),
    ("duplicate", [row("b", tab_id="t1"), row("a", tab_id="t1")], {"t1"}, "", {}),
])
def test_removable_rows_names_a_reason_for_every_removal(reason, rows, live, pattern, misses):
    spec = up.RemovalSpec(rows=rows, live_keys=live, pattern=pattern, misses=misses)
    removals = up.removable_rows(spec)
    assert [(r.row_id, r.reason) for r in removals] == [("a", reason)]
    assert removals[0].url == rows[[r["id"] for r in rows].index("a")]["url"]


def test_a_row_whose_tab_has_a_live_job_is_deferred_not_removed():
    pool = PagePool()
    pool.add_page(make_info("t1"))
    cooldown_service.set_tab_image(pool, "t1", "a.png")
    busy = up.busy_tabs(pool)
    assert busy == {"t1"}
    spec = up.RemovalSpec(rows=[row("a", tab_id="t1")], live_keys=set(), pattern="", busy_tabs=busy,
                          misses={"t1": 99})
    assert up.removable_rows(spec) == []
    assert spec.deferred == ["a"]                       # reported, not silently kept (RULE 15)


def test_never_linked_user_rows_are_kept():
    rows = [row("u", url="https://arena.ai/typed", tab_id=""), row("bad", url="garbage", tab_id="")]
    spec = up.RemovalSpec(rows=rows, live_keys=set(), pattern="arena.ai", misses={})
    assert up.removable_rows(spec) == []                # D-4: a user's own row never follows Chrome


def test_misses_give_hysteresis_and_reset_on_reappearance():
    rows = [row("a", tab_id="t1")]
    misses = up.advance_misses(rows, live_keys=set(), misses={})
    assert misses == {"t1": 1}
    assert up.removable_rows(up.RemovalSpec(rows=rows, live_keys=set(), misses=misses)) == []   # once: kept
    misses = up.advance_misses(rows, live_keys=set(), misses=misses)
    assert misses == {"t1": 2} and up.MISS_THRESHOLD == 2
    assert [r.reason for r in up.removable_rows(up.RemovalSpec(rows=rows, live_keys=set(), misses=misses))] == ["tab_gone"]
    assert up.advance_misses(rows, live_keys={"t1"}, misses=misses) == {}                       # back: forgotten


def test_dedupe_keeps_one_row_per_tab_exactly_like_the_panel_helper():
    """Equivalence for the move: the panel's `_dedupe_state_rows` is now a delegation."""
    shapes = [
        [UrlRow.create("https://a", tab_id="t1"), UrlRow.create("https://b", tab_id="t1")],
        [UrlRow.create("https://a", enabled=False, tab_id="t1"), UrlRow.create("https://b", tab_id="t1")],
        [UrlRow.create("https://a"), UrlRow.create("https://b")],
        [],
        [UrlRow.create("https://a", tab_id="t1"), UrlRow.create("https://b", tab_id="t2"), UrlRow.create("https://c", tab_id="t1")],
        [UrlRow.create("https://a", tab_id="")],
    ]
    for urls in shapes:
        mine, theirs = list(urls), list(urls)
        assert up.dedupe_rows(mine) == url_queue._dedupe_state_rows(theirs)
        assert [u.id for u in mine] == [u.id for u in theirs]
    assert url_queue._dedupe_state_rows.__module__ == "app.ui.panels.url_queue"   # a delegation, not a copy
    assert "dedupe_rows" in inspect.getsource(url_queue._dedupe_state_rows)


def test_restore_enabled_reuses_the_remembered_checkbox():
    memory = {}
    up.remember(memory, row("a", url="https://arena.ai/c/9", enabled=False))
    assert up.restore_enabled(memory, "https://arena.ai/c/9") is False
    assert up.restore_enabled(memory, "https://arena.ai/unknown") is True
    urls = []
    assert up.add_rows(urls, [("https://arena.ai/c/9", "t9"), ("https://arena.ai/new", "t10")], memory) == 2
    assert [(u.enabled, u.tab_id) for u in urls] == [(False, "t9"), (True, "t10")]   # reopened unchecked
    assert up.add_rows(urls, [("https://arena.ai/c/9", "t9")], memory) == 0             # one row per tab
    for i in range(up.MEMORY_MAX + 20):
        up.remember(memory, row(str(i), url=f"https://arena.ai/m/{i}", enabled=False))
    assert len(memory) == up.MEMORY_MAX                                                # bounded, oldest out
    assert "https://arena.ai/c/9" not in memory


def test_removal_lines_are_one_per_row_and_carry_the_reason():
    lines = up.removal_lines([up.Removal("a", "https://arena.ai/c/1", "tab_gone"),
                              up.Removal("b", "https://arena.ai/c/2", "duplicate")])
    assert len(lines) == 2
    assert "https://arena.ai/c/1" in lines[0] and "tab closed" in lines[0]
    assert "https://arena.ai/c/2" in lines[1] and "duplicate" in lines[1]
    assert set(up.REASON_TEXT) == {"tab_gone", "pattern_mismatch", "invalid", "duplicate"}


def test_removable_rows_is_a_table_not_a_chain():
    assert "elif" not in inspect.getsource(up.removable_rows)
    assert [reason for reason, _pred in up.REMOVAL_RULES] == ["duplicate", "invalid", "pattern_mismatch", "tab_gone"]


def test_add_rows_and_tab_owned_back_the_panel_helpers():
    urls = [UrlRow.create("https://a", tab_id="t1")]
    assert up.tab_owned(urls, "t1") is True and up.tab_owned(urls, "t9") is False
    assert url_queue._add_missing_rows(urls, [("https://b", "t1"), ("https://c", "t2")]) == 1
    assert [u.tab_id for u in urls] == ["t1", "t2"]
    assert "add_rows" in inspect.getsource(url_queue._add_missing_rows)
    assert "tab_owned" in inspect.getsource(url_queue._tab_already_owned)
