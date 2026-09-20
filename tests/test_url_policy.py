"""S6: URL row policy — removals with reasons, hysteresis, dedupe/add, memory (pure)."""

import pytest

from app.core.models import UrlRow
from app.services.live import url_policy as up
from app.services.live.url_policy import Removal, RemovalSpec


def row(url="https://arena.ai/c/1", tab_id="t1", enabled=True, status="unchecked"):
    r = UrlRow.create(url, enabled=enabled, tab_id=tab_id)
    r.last_status = status
    return r


def spec(rows, live=(), pattern="arena.ai", busy=(), misses=None):
    return RemovalSpec(rows=list(rows), live_keys=set(live), pattern=pattern,
                       busy_tabs=set(busy), misses=dict(misses or {}))


@pytest.mark.unit
@pytest.mark.parametrize("reason,rows,live,pattern,misses", [
    ("tab_gone", [row()], (), "arena.ai", {"t1": 3}),
    ("pattern_mismatch", [row("https://google.com/x")], ("t1",), "arena.ai", {}),
    ("invalid", [row("not-a-url")], ("t1",), "", {}),
    ("duplicate", [row(), row()], ("t1",), "arena.ai", {}),
], ids=["tab_gone", "pattern_mismatch", "invalid", "duplicate"])
def test_removable_rows_names_a_reason_for_every_removal(reason, rows, live, pattern, misses):
    s = spec(rows, live, pattern, misses=misses)
    out = up.removable_rows(s)
    assert len(out) == 1 and out[0].reason == reason
    assert out[0].row_id == rows[-1].id and out[0].url == rows[-1].url


@pytest.mark.unit
def test_a_row_whose_tab_has_a_live_job_is_deferred_not_removed():
    from app.browser.page_pool import PagePool
    from app.services.cooldown_service import set_tab_image, tab_has_live_job
    from tests.test_captcha_service import make_info
    pool = PagePool()
    pool.add_page(make_info("t1"))
    set_tab_image(pool, "t1", "a.png")
    assert tab_has_live_job(pool, "t1") is True
    r = row()
    s = spec([r], busy={"t1"}, misses={"t1": 9})  # over threshold, still deferred
    assert up.removable_rows(s) == []
    assert s.deferred == [r.id]


@pytest.mark.unit
def test_never_linked_user_rows_are_kept():
    rows = [row(tab_id=""), row(tab_id="", status="ok")]
    s = spec(rows, pattern="zzz-no-match")
    assert up.removable_rows(s) == []
    assert s.deferred == []


@pytest.mark.unit
def test_misses_give_hysteresis_and_reset_on_reappearance():
    rows = [row(tab_id="t1")]
    m1 = up.advance_misses(rows, set(), {})
    assert m1 == {"t1": 1}
    m2 = up.advance_misses(rows, set(), m1)
    assert m2 == {"t1": 2}
    assert up.removable_rows(spec(rows, misses=m2)) == []  # kept below threshold
    m3 = up.advance_misses(rows, set(), m2)
    assert m3 == {"t1": 3}
    out = up.removable_rows(spec(rows, misses=m3))
    assert [r.reason for r in out] == ["tab_gone"]
    assert up.advance_misses(rows, {"t1"}, m3) == {}  # reappearance resets


def _shape_builders():
    a = lambda: [row("https://arena.ai/1", "t1"), row("https://arena.ai/2", "t2")]
    b = lambda: [row("https://arena.ai/1", "t1"), row("https://arena.ai/1b", "t1", False)]
    c = lambda: [row("https://arena.ai/1", "t1", False), row("https://arena.ai/1b", "t1")]
    d = lambda: [row("https://arena.ai/1", "t1"), row("https://arena.ai/1b", "t1")]
    e = lambda: [row("https://arena.ai/1", ""), row("https://arena.ai/2", "")]
    f = lambda: [row("https://arena.ai/1", "t1"), row("https://arena.ai/1b", "t1"),
                 row("https://arena.ai/2", "")]
    return [a, b, c, d, e, f]


@pytest.mark.unit
@pytest.mark.parametrize("shape_id", range(6))
def test_dedupe_keeps_one_row_per_tab(shape_id):
    import copy
    from app.ui.panels.url_queue import _dedupe_state_rows
    shape = _shape_builders()[shape_id]
    old_rows = shape()
    new_rows = copy.deepcopy(old_rows)  # same ids; dedupe mutates in place
    old_kept, old_n = _dedupe_state_rows(old_rows)
    new_kept, new_n = up.dedupe_rows(new_rows)
    assert (new_kept, new_n) == (old_kept, old_n)


@pytest.mark.unit
def test_restore_enabled_reuses_the_remembered_checkbox():
    mem = {}
    up.remember("t1", False, mem)
    assert up.restore_enabled("t1", mem) is False
    assert up.restore_enabled("t9", mem) is True  # unknown defaults checked
    up.remember("t1", True, mem)
    assert up.restore_enabled("t1", mem) is True
    rows = []
    up.add_rows(rows, [("https://arena.ai/c/1", "t1")], {"t1": False})
    assert rows[0].enabled is False and rows[0].tab_id == "t1"  # reopens unchecked
    big = {}
    for i in range(250):
        up.remember(f"t{i}", True, big)
    assert len(big) == 200


@pytest.mark.unit
def test_removal_lines_are_one_per_row_and_carry_the_reason():
    rs = [Removal("a", "https://arena.ai/1", "tab_gone"),
          Removal("b", "https://x/2", "invalid")]
    lines = up.removal_lines(rs)
    assert len(lines) == 2
    assert "tab_gone" in lines[0] and "https://arena.ai/1" in lines[0]
    assert "invalid" in lines[1] and "https://x/2" in lines[1]


@pytest.mark.unit
def test_removable_rows_is_a_table_not_a_chain():
    import inspect
    assert "elif" not in inspect.getsource(up.removable_rows)


@pytest.mark.unit
def test_enabled_rows_gate_matches_auto_connect():
    """S6 half of the S6/S7 seam: enabled_tab_ids on 8 shapes (S7 adds mark_receivers)."""
    from app.services.auto_connect import enabled_tab_ids
    t1 = row(tab_id="t1")
    t1d = row(tab_id="t1", enabled=False)
    free = row(tab_id="")
    freed = row(tab_id="", enabled=False)
    cases = [([t1], {"t1"}), ([t1d], set()), ([free], set()), ([freed], set()),
             ([t1, row(tab_id="t2"), row(tab_id="t3", enabled=False)], {"t1", "t2"}),
             ([t1, row(tab_id="t1")], {"t1"}), ([], set()), (None, set())]
    for rows, want in cases:
        assert enabled_tab_ids(rows) == want
