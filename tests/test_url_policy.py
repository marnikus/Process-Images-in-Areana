"""S6 url_policy — removal table, hysteresis, remember/restore (plan §S6 tests 1-8).

RED at base: `app.services.live.url_policy` does not exist yet.
"""
from __future__ import annotations

import inspect

import pytest

from app.core.models import UrlRow
from app.services.live import url_policy
from app.services.live.url_policy import (
    MEMORY_MAX, MISS_THRESHOLD, RemovalSpec, advance_misses, dedupe_rows,
    removable_rows, removal_lines, remember, restore_enabled, add_rows,
)
from app.services.auto_connect import dedupe_linked_rows
from app.ui.panels import url_queue


def _spec(rows, live=(), pattern="arena.ai", busy=(), misses=None) -> RemovalSpec:
    return RemovalSpec(rows=rows, live_keys=set(live), pattern=pattern,
                       busy_tabs=set(busy), misses=misses or {})


def _row(url, tab_id="", status="ready", enabled=True, row_id=None) -> UrlRow:
    r = UrlRow.create(url, enabled=enabled, tab_id=tab_id)
    r.last_status = status
    if row_id is not None:
        r.id = row_id
    return r


@pytest.mark.unit
@pytest.mark.parametrize("reason,make_rows,keep", [
    ("tab_gone",
     lambda: [_row("https://arena.ai/a", "t1", row_id="r1"), _row("https://arena.ai/b", "t2", row_id="r2")],
     "t2"),
    ("invalid",
     lambda: [_row("not-a-url", row_id="r1"), _row("https://arena.ai/b", "t2", row_id="r2")],
     None),
    ("pattern_mismatch",
     lambda: [_row("https://other.example/a", "t1", row_id="r1"), _row("https://arena.ai/b", "t2", row_id="r2")],
     "t2"),
])
def test_removable_rows_names_a_reason_for_every_removal(reason, make_rows, keep):
    rows = make_rows()
    live = {keep} if keep else set()
    misses = {"r1": MISS_THRESHOLD} if reason == "tab_gone" else {}
    removals = removable_rows(_spec(rows, live=live, misses=misses))
    assert [r.reason for r in removals] == [reason]
    assert removals[0].row_id == "r1"


@pytest.mark.unit
def test_duplicate_rows_removed_with_duplicate_reason():
    rows = [_row("https://arena.ai/a", "t1", row_id="r1"),
            _row("https://arena.ai/b", "t1", row_id="r2")]
    removals = removable_rows(_spec(rows, live={"t1"}))
    assert [(r.row_id, r.reason) for r in removals] == [("r2", "duplicate")]


@pytest.mark.unit
def test_a_row_whose_tab_has_a_live_job_is_deferred_not_removed():
    from app.browser.page_pool import PagePool
    from app.browser.page_status import PageInfo
    from app.services import cooldown_service
    pool = PagePool()
    pool.add_page(PageInfo(tab_id="t1", url="https://arena.ai", ws_url="ws://x"))
    cooldown_service.set_tab_image(pool, "t1", "a.png")
    page = pool.get_page("t1")
    busy = {"t1"} if page.current_image else set()
    rows = [_row("https://arena.ai/a", "t1", row_id="r1")]
    spec = _spec(rows, live=set(), busy=busy, misses={"r1": MISS_THRESHOLD})
    removals = removable_rows(spec)
    assert removals == []
    assert "t1" in spec.deferred


@pytest.mark.unit
def test_never_linked_user_rows_are_kept():
    rows = [_row("https://arena.ai/pending", "", "unchecked", row_id="r1")]
    spec = _spec(rows, live=set())
    once = removable_rows(spec)
    twice = removable_rows(_spec(spec.rows, misses=advance_misses(spec.rows, set(), {"r1": 3})))
    assert once == [] and twice == []


@pytest.mark.unit
def test_misses_give_hysteresis_and_reset_on_reappearance():
    rows = [_row("https://arena.ai/a", "t1", row_id="r1")]
    first = advance_misses(rows, set(), {})
    assert first["r1"] == 1
    assert removable_rows(_spec(rows, misses=first)) == []
    second = advance_misses(rows, set(), first)
    assert second["r1"] == 2
    assert [r.row_id for r in removable_rows(_spec(rows, misses=second))] == ["r1"]
    reappeared = advance_misses(rows, {"t1"}, second)
    assert "r1" not in reappeared


@pytest.mark.unit
def test_dedupe_keeps_one_row_per_tab_a_pair_with_the_panel_helper():
    shapes = [
        [],
        [_row("https://arena.ai/a", "")],
        [_row("https://arena.ai/a", "t1"), _row("https://arena.ai/b", "t1")],
        [_row("https://arena.ai/a", "t1"), _row("https://arena.ai/b", "t1", enabled=False)],
        [_row("https://arena.ai/a", ""), _row("https://arena.ai/a", ""), _row("https://arena.ai/b", "t1")],
        [_row("https://a.io", "t1"), _row("https://b.io", "t2"), _row("https://c.io", "t1", enabled=False)],
    ]
    for rows in shapes:
        legacy = [dict(id=u.id, url=u.url, tab_id=u.tab_id, enabled=u.enabled) for u in rows]
        kept_legacy, dropped_legacy = dedupe_linked_rows(list(legacy))
        dicts = [dict(id=u.id, url=u.url, tab_id=u.tab_id, enabled=u.enabled) for u in rows]
        kept, dropped = dedupe_rows(dicts)
        assert kept == kept_legacy and dropped == dropped_legacy
        direct = [UrlRow(id=r["id"], url=r["url"], tab_id=r["tab_id"], enabled=r["enabled"]) for r in legacy]
        assert url_queue._dedupe_state_rows(direct)[1] == len(dropped_legacy)


@pytest.mark.unit
def test_add_rows_respects_one_row_per_tab_a_pair_with_the_panel_helper():
    adds = [("https://arena.ai/x", "t1"), ("https://arena.ai/y", "t2")]
    owned = [_row("https://arena.ai/a", "t1")]
    assert add_rows([_row("https://arena.ai/a", "t1")], adds) == 1
    assert url_queue._add_missing_rows(owned, adds) == 1
    assert {u.tab_id for u in owned} == {"t1", "t2"}


@pytest.mark.unit
def test_restore_enabled_reuses_the_remembered_checkbox_and_stays_bounded():
    memory = {}
    remember(memory, "https://arena.ai/a", False)   # rows die and re-add; the URL is the identity
    remember(memory, "https://arena.ai/b", True)
    gone_reopened = _row("https://arena.ai/a", "t9")
    restore_enabled(gone_reopened, memory)
    assert gone_reopened.enabled is False
    fresh = _row("https://arena.ai/unknown", "t8")
    restore_enabled(fresh, memory)
    assert fresh.enabled is True
    for i in range(MEMORY_MAX + 50):
        remember(memory, f"https://arena.ai/{i}", True)
    assert len(memory) <= MEMORY_MAX
    assert "https://arena.ai/a" not in memory


@pytest.mark.unit
def test_removal_lines_are_one_per_row_and_carry_the_reason():
    rows = [_row("https://arena.ai/a", "t1", row_id="r1"),
            _row("https://arena.ai/b", "t2", row_id="r2")]
    removals = removable_rows(_spec(rows, live=set(), misses={"r1": 9, "r2": 9}))
    lines = removal_lines(removals)
    assert len(lines) == 2
    for removal, line in zip(removals, lines):
        assert removal.url in line and removal.reason.replace("_", " ") in line


@pytest.mark.unit
def test_removable_rows_is_a_table_not_a_chain():
    src = inspect.getsource(removable_rows)
    assert "elif" not in src, "RULE 19 step 2: the removal lookup is a predicate table"
    assert "_REMOVAL_CHECKS" in inspect.getsource(url_policy)
