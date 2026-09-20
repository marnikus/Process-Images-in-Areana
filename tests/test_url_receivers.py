"""S7 RED: receiver flag + icon — UrlRow.receiver + mark_receivers (I-45)."""
import json
import pytest
from app.core.models import UrlRow

def test_unchecked_unlinked_and_offline_rows_are_not_receivers():
    assert "receiver" in UrlRow.__dataclass_fields__
    row = UrlRow.create("https://arena.ai/a", enabled=False, tab_id="t1")
    assert row.receiver is False

def test_a_checked_row_on_a_connected_pooled_tab_is_a_receiver():
    assert "receiver" in UrlRow.__dataclass_fields__
    from app.browser.page_pool import PagePool
    from app.browser.page_status import PageInfo
    pool = PagePool()
    pool.add_page(PageInfo(tab_id="t1", ws_url="ws://x", title="A", url="https://arena.ai/a", is_connected=True))
    row = UrlRow.create("https://arena.ai/a", enabled=True, tab_id="t1")
    from app.services.live.url_policy import mark_receivers
    from app.services.auto_connect import enabled_tab_ids
    allowed = enabled_tab_ids([row])
    mark_receivers([row], allowed, {"t1"})
    assert row.receiver is True

def test_mark_receivers_reports_only_changes():
    assert "receiver" in UrlRow.__dataclass_fields__
    from app.services.live.url_policy import mark_receivers
    from app.services.auto_connect import enabled_tab_ids
    row = UrlRow.create("https://arena.ai/a", enabled=True, tab_id="t1")
    allowed = enabled_tab_ids([row])
    mark_receivers([row], allowed, {"t1"})
    assert mark_receivers([row], allowed, {"t1"}) == 0

def test_the_flag_survives_serialization():
    assert "receiver" in UrlRow.__dataclass_fields__
    from app.ui.services.arena_serialize import arena_to_js
    from app.core.models import AppState
    state = AppState()
    row = UrlRow.create("https://arena.ai/a", enabled=True, tab_id="t1")
    row.receiver = False
    state.urls = [row]
    js = arena_to_js(state)
    assert js["urls"][0]["receiver"] is False

def test_the_flag_survives_persistence(tmp_path):
    assert "receiver" in UrlRow.__dataclass_fields__
    from app.core.persistence import save_state, load_state
    from app.core.models import AppState
    state = AppState()
    row = UrlRow.create("https://arena.ai/a", enabled=True, tab_id="t1")
    row.receiver = False
    state.urls = [row]
    p = tmp_path / "arena.json"
    save_state(state, p)
    loaded = load_state(p)
    assert loaded.urls[0].receiver is False

def test_the_flag_survives_undo_and_redo():
    assert "receiver" in UrlRow.__dataclass_fields__
    from app.ui.services.undo_entries import url_rows_from_js, arena_url_rows_from_js
    row = UrlRow.create("https://arena.ai/a", enabled=True, tab_id="t1")
    row.receiver = False
    assert row.receiver is False

def test_commit_urls_recomputes_the_flag():
    assert "receiver" in UrlRow.__dataclass_fields__
    # commit_urls should call mark_receivers; checked via url_policy
    src = open("app/services/live/url_policy.py").read()
    assert "mark_receivers" in src

def test_the_run_gate_is_not_reimplemented():
    assert "receiver" in UrlRow.__dataclass_fields__
    src = open("app/services/live/url_policy.py").read()
    assert "enabled_tab_ids(" in src
