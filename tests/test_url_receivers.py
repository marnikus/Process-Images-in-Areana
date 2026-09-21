"""S7 UrlRow.receiver — one Python owner of the run gate, the icon only reflects (plan §S7 tests 1-8).

RED at base: `UrlRow` has no `receiver` attribute → AttributeError inside mark/reason paths.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.models import AppState, UrlRow
from app.core.persistence import load_state, save_state
from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo
from app.services.live.url_policy import (
    allowed_tab_ids, mark_receivers, receiver_reason,
)
from app.ui.services import arena_serialize, undo_entries
from app.ui.panels.url_queue import UrlQueueMixin
from tests.test_panel_slots import make_host, make_state


def pool_with(tab_id="t1", connected=True, image=None):
    pool = PagePool()
    pool.add_page(PageInfo(url="https://arena.ai/c", title="T", tab_id=tab_id, ws_url=f"ws://x/{tab_id}"))
    page = pool.get_page(tab_id)
    page.is_connected = connected
    page.current_image = image
    return pool


def row_for(url="https://arena.ai/c", enabled=True, tab_id=""):
    r = UrlRow.create(url, enabled=enabled, tab_id=tab_id)
    r.last_status = "ready"
    return r


@pytest.mark.unit
@pytest.mark.parametrize(
    "reason,make_row,make_pool",
    [
        ("unchecked", lambda: row_for(enabled=False), None),
        ("not linked", lambda: row_for(tab_id=""), None),
        ("offline", lambda: row_for(tab_id="t1"), lambda: pool_with(connected=False)),
        ("busy", lambda: row_for(tab_id="t1"), lambda: pool_with(image="a.png")),
    ],
)
def test_unchecked_unlinked_and_offline_rows_are_not_receivers(reason, make_row, make_pool):
    r = make_row()
    pool = make_pool() if make_pool else None
    assert receiver_reason(r, allowed_tab_ids([r]), pool) == reason
    assert mark_receivers([r], allowed_tab_ids([r]), pool) == 1
    assert r.receiver is False


@pytest.mark.unit
def test_a_checked_row_on_a_connected_pooled_tab_is_a_receiver():
    r = row_for(tab_id="t1")
    pool = pool_with()
    assert receiver_reason(r, {"t1"}, pool) == ""
    mark_receivers([r], {"t1"}, pool)
    assert r.receiver is True


@pytest.mark.unit
def test_mark_receivers_reports_only_changes():
    r = row_for(tab_id="t1")
    pool = pool_with()
    assert mark_receivers([r], {"t1"}, pool) == 1
    assert mark_receivers([r], {"t1"}, pool) == 0


@pytest.mark.unit
def test_the_flag_survives_serialization():
    state = AppState()
    state.urls = [row_for()]
    mark_receivers(state.urls, allowed_tab_ids(state.urls), None)
    js_urls = arena_serialize.arena_to_js(state)["urls"]
    assert js_urls[0]["receiver"] is False
    assert js_urls[0]["receiver_reason"] == "not linked"


@pytest.mark.unit
def test_the_flag_survives_persistence(tmp_path):
    state = AppState()
    state.urls = [row_for()]
    mark_receivers(state.urls, allowed_tab_ids(state.urls), None)
    save_state(state, tmp_path / "arena.json")
    loaded = load_state(tmp_path / "arena.json")
    assert loaded.urls[0].receiver is False
    assert loaded.urls[0].receiver_reason == "not linked"


@pytest.mark.unit
def test_the_flag_survives_undo_and_redo():
    state = AppState()
    state.urls = [row_for(tab_id="t1")]
    mark_receivers(state.urls, allowed_tab_ids(state.urls), pool_with())
    assert state.urls[0].receiver is True
    js_value = arena_serialize.arena_to_js(state)["urls"]      # undo captures the state at flip time
    state.urls[0].enabled = False
    mark_receivers(state.urls, allowed_tab_ids(state.urls), pool_with())
    assert state.urls[0].receiver is False
    restored = undo_entries.url_rows_from_js(js_value)
    assert restored[0].receiver is True                        # undo: back to receiver
    assert restored[0].receiver_reason == ""
    re = undo_entries.arena_url_rows_from_js(js_value)
    assert re[0].receiver is True                              # redo/snapshot restore too


@pytest.mark.unit
def test_commit_urls_recomputes_the_flag():
    host, _logs = make_host(
        (UrlQueueMixin,),
        config=None,
        state=make_state(urls=[row_for(tab_id="t1")]),
        _page_pool=pool_with(),
        undo_service=None,
    )
    host._commit_urls()
    assert host.state.urls[0].receiver is True
    reply = json.loads(host.toggle_url(host.state.urls[0].id))
    assert reply["ok"] is True and reply["enabled"] is False
    assert host.state.urls[0].receiver is False
    assert host.state.urls[0].receiver_reason == "unchecked"


@pytest.mark.unit
def test_the_run_gate_is_not_reimplemented():
    import inspect
    src = Path("app/services/live/url_policy.py").read_text(encoding="utf-8")
    assert "enabled_tab_ids(" in src, "receivers must READ auto_connect's run gate, one owner (RULE 10)"
    for fn in (mark_receivers, receiver_reason):          # scoped lock: a pre-S7 comprehension lives at :110
        body = inspect.getsource(fn)
        assert "for u in" not in body
        assert ".enabled and" not in body
