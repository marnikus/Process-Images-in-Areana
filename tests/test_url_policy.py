"""S6 · `live/url_policy` — pure URL-row policy (no bridge, no I/O).

Removal is a table of `(reason, predicate)` pairs (RULE 19 step 2), a row
whose tab has a live job is deferred (RULE 15), never-linked user rows are
kept (D-4), hysteresis counters give a closed tab two reconciles before its
row goes, and the two row helpers moved out of `panels/url_queue` keep their
behaviour byte-for-byte.

RED at base: `ModuleNotFoundError: app.services.live.url_policy`.
"""

import inspect

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo
from app.core.models import UrlRow
from app.services import auto_connect as ac
from app.services.cooldown_service import set_tab_image
from app.services.live import url_policy as up

pytestmark = pytest.mark.unit


def row(url="https://arena.ai/c/1", tab_id="", enabled=True, status="unchecked", rid=None):
    r = UrlRow.create(url, enabled=enabled, tab_id=tab_id)
    r.last_status = status
    if rid:
        r.id = rid
    return r


def spec(rows, live=("t1",), pattern="arena.ai", busy=(), misses=None, threshold=2):
    return up.RemovalSpec(rows=list(rows), live_keys=set(live), pattern=pattern,
                          busy_tabs=set(busy), misses=dict(misses or {}), miss_threshold=threshold)


@pytest.mark.parametrize("reason, victim, others", [
    ("tab_gone", row(tab_id="t9", rid="gone"), [row(tab_id="t1", rid="ok")]),
    ("pattern_mismatch", row("https://example.com/x", tab_id="t1", rid="mis"), [row(tab_id="t2", rid="ok")]),
    ("invalid", row(tab_id="t1", status="authentication required", rid="bad"), [row(tab_id="t2", rid="ok")]),
    ("duplicate", row(tab_id="t1", rid="dupe"), [row(tab_id="t1", rid="ok")]),
])
def test_removable_rows_names_a_reason_for_every_removal(reason, victim, others):
    rows = others + [victim]
    live = {"t1", "t2"}
    misses = {"t9": 2} if reason == "tab_gone" else {}
    got = up.removable_rows(spec(rows, live=live, misses=misses))
    assert [(r.row_id, r.reason) for r in got] == [(victim.id, reason)]
    assert got[0].url == victim.url


def test_a_row_whose_tab_has_a_live_job_is_deferred_not_removed():
    pool = PagePool(logger=lambda m, l="info": None)
    pool.add_page(PageInfo(tab_id="t1", ws_url="ws://x", title="T", url="https://arena.ai", is_connected=True))
    set_tab_image(pool, "t1", "a.png")
    busy = up.busy_tabs(pool, ["t1", "t2"])
    assert busy == {"t1"}
    victim = row("https://example.com/x", tab_id="t1", rid="mis")
    s = spec([victim], live={"t1"}, busy=busy)
    assert up.removable_rows(s) == []
    assert [(d.row_id, d.reason) for d in up.deferred_rows(s)] == [("mis", "pattern_mismatch")]


def test_never_linked_user_rows_are_kept():
    typed = row("https://arena.ai/typed", tab_id="", status="unchecked", rid="typed")
    foreign = row("https://elsewhere.org/typed", tab_id="", status="unchecked", rid="foreign")
    got = up.removable_rows(spec([typed, foreign], live=set(), misses={}))
    assert got == []  # a typed row is authorisation, not garbage (D-4)


def test_misses_give_hysteresis_and_reset_on_reappearance():
    rows = [row(tab_id="t1", rid="a")]
    misses = up.advance_misses(rows, live_keys=set(), misses={})
    assert misses == {"t1": 1}
    assert up.removable_rows(spec(rows, live=set(), misses=misses)) == []  # once: kept
    misses = up.advance_misses(rows, live_keys=set(), misses=misses)
    assert misses == {"t1": 2}
    assert [r.reason for r in up.removable_rows(spec(rows, live=set(), misses=misses))] == ["tab_gone"]
    assert up.advance_misses(rows, live_keys={"t1"}, misses=misses) == {}  # reappeared: dropped


@pytest.mark.parametrize("shape", [
    [],
    [{"id": "a", "url": "u", "tab_id": "", "enabled": True}],
    [{"id": "a", "url": "u", "tab_id": "t1", "enabled": True}, {"id": "b", "url": "u", "tab_id": "t1", "enabled": True}],
    [{"id": "a", "url": "u", "tab_id": "t1", "enabled": False}, {"id": "b", "url": "u", "tab_id": "t1", "enabled": True}],
    [{"id": "a", "url": "u", "tab_id": "t1", "enabled": True}, {"id": "b", "url": "v", "tab_id": "t2", "enabled": True}],
    [{"id": "a", "url": "u", "tab_id": "", "enabled": True}, {"id": "b", "url": "u", "tab_id": "t1", "enabled": True},
     {"id": "c", "url": "u", "tab_id": "t1", "enabled": False}, {"id": "d", "url": "u", "tab_id": "t1", "enabled": True}],
])
def test_dedupe_keeps_one_row_per_tab(shape):
    """The moved `_dedupe_state_rows`: same (kept, removed) as the planner's `dedupe_linked_rows`."""
    state_urls = [UrlRow(id=d["id"], url=d["url"], enabled=d["enabled"], tab_id=d["tab_id"]) for d in shape]
    kept_ref, dropped_ref = ac.dedupe_linked_rows([dict(d) for d in shape])
    kept, removed = up.dedupe_rows(state_urls)
    assert [k["id"] for k in kept] == [k["id"] for k in kept_ref] and removed == len(dropped_ref)
    assert [u.id for u in state_urls] == [k["id"] for k in kept_ref]  # the state list is repaired in place


def test_add_rows_never_doubles_a_tab_and_restores_the_remembered_checkbox():
    urls = [row(tab_id="t1", rid="own")]
    memory = {}
    up.remember([row("https://arena.ai/c/2", tab_id="t2", enabled=False, rid="old")], memory)
    added = up.add_rows(urls, [("https://arena.ai/c/x", "t1"), ("https://arena.ai/c/2", "t2"), ("https://arena.ai/c/3", "t3")], memory)
    assert added == 2 and len(urls) == 3
    by_url = {u.url: u for u in urls}
    assert by_url["https://arena.ai/c/2"].enabled is False  # reopened unchecked, as the user left it
    assert by_url["https://arena.ai/c/3"].enabled is True


def test_memory_is_bounded_at_200_entries():
    memory = {}
    up.remember([row(f"https://arena.ai/c/{i}", tab_id=f"t{i}") for i in range(250)], memory)
    assert len(memory) == up.MEMORY_LIMIT == 200
    assert "https://arena.ai/c/249" in memory and "https://arena.ai/c/0" not in memory  # oldest evicted


def test_removal_lines_are_one_per_row_and_carry_the_reason():
    removals = [up.Removal("a", "https://arena.ai/c/1", "tab_gone"),
                up.Removal("b", "https://example.com/x", "pattern_mismatch"),
                up.Removal("c", "https://arena.ai/c/3", "invalid"),
                up.Removal("d", "https://arena.ai/c/4", "duplicate")]
    lines = up.removal_lines(removals, pattern="arena.ai", threshold=2)
    assert len(lines) == 4 and all(line.startswith("🔻 URL removed ") for line in lines)
    assert "tab closed (2 reconciles)" in lines[0]
    assert "does not match pattern 'arena.ai'" in lines[1]
    assert "invalid" in lines[2] and "duplicate" in lines[3]


def test_removable_rows_is_a_table_not_a_chain():
    src = inspect.getsource(up.removable_rows)
    assert "elif" not in src
    assert len(up.REMOVAL_RULES) == 4 and [r for r, _p in up.REMOVAL_RULES] == ["duplicate", "invalid", "pattern_mismatch", "tab_gone"]


@pytest.mark.parametrize("shape", [
    dict(enabled=True, tab_id="t1"), dict(enabled=False, tab_id="t1"), dict(enabled=True, tab_id=""),
    dict(enabled=False, tab_id=""), dict(enabled=True, tab_id="t2"), dict(enabled=True, tab_id=None),
    dict(enabled=None, tab_id="t1"), dict(enabled=1, tab_id="t3"),
])
def test_enabled_rows_gate_matches_auto_connect(shape):
    """The seam with S7: what `auto_connect.enabled_tab_ids` counts as a run tab, `owns_run_tab` agrees with."""
    r = UrlRow.create("https://arena.ai/c", enabled=shape["enabled"], tab_id=shape["tab_id"])
    assert up.owns_run_tab(r) is (r.tab_id in ac.enabled_tab_ids([r]))
