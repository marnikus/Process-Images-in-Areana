"""S10 equivalence: receiver owner, persistence, commit and history conversion."""
import json

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo
from app.core.models import AppState, UrlRow
from app.core.persistence import load_state, save_state
from app.services.auto_connect import enabled_tab_ids
from app.services.live.url_policy import mark_receivers, receiver_reason
from app.services.run_state import pooled_ids
from app.ui.panels.url_queue import commit_urls
from app.ui.services.arena_serialize import arena_to_js
from app.ui.services.undo_entries import arena_url_rows_from_js, url_rows_from_js
from tests.characterization.harness import build_bridge


@pytest.mark.parametrize('enabled,tid,pooled,expected', [
    (False, 't1', {'t1'}, 'unchecked'), (True, '', {'t1'}, 'not linked'),
    (True, 't1', set(), 'offline'), (True, 't1', {'t1'}, '')])
def test_one_owner_marks_every_receiver_case(enabled, tid, pooled, expected):
    row = UrlRow.create('https://arena.ai/a', enabled=enabled, tab_id=tid)
    row.receiver = bool(expected)  # deliberately wrong initial flag in every case
    allowed = enabled_tab_ids([row])
    assert receiver_reason(row, allowed, pooled) == expected
    assert mark_receivers([row], allowed, pooled) == 1
    assert row.receiver is (expected == '')
    assert mark_receivers([row], allowed, pooled) == 0


@pytest.mark.parametrize('receiving', [False, True])
def test_flag_round_trips_persistence_js_and_both_history_converters(tmp_path, receiving):
    row = UrlRow.create('https://arena.ai/a', tab_id='t1')
    row.receiver = receiving
    state = AppState(urls=[row])
    path = tmp_path / 'arena.json'
    save_state(state, path)
    loaded = load_state(path)
    assert loaded.urls[0].receiver is receiving
    payload = arena_to_js(loaded)['urls']
    assert payload[0]['receiver'] is receiving
    for converter in [url_rows_from_js, arena_url_rows_from_js]:
        restored = converter(json.loads(json.dumps(payload)))
        assert restored[0].receiver is receiving
        assert restored[0].tab_id == 't1'


def test_commit_urls_recomputes_and_publishes_real_pool_connection_changes(tmp_path):
    env = build_bridge(tmp_path, [], pool=PagePool())
    row = UrlRow.create('https://arena.ai/a', tab_id='t1')
    env.bridge.state.urls = [row]
    pool = env.bridge._page_pool
    pool.add_page(PageInfo(tab_id='t1', is_connected=True))
    commit_urls(env.bridge)
    assert row.receiver is True
    assert pooled_ids(pool) == {'t1'}
    pool.get_page('t1').is_connected = False
    commit_urls(env.bridge)
    assert row.receiver is False
    assert json.loads(env.recs['arena_state_updated'].calls[-1][0])['urls'][0]['receiver'] is False
    row.enabled = False
    pool.get_page('t1').is_connected = True
    commit_urls(env.bridge)
    assert row.receiver is False


def test_connected_id_projection_has_an_empty_positive_control():
    from app.services.live.url_policy import connected_tab_ids
    pool = PagePool()
    assert connected_tab_ids(None) == set()
    assert connected_tab_ids(pool) == set()
    pool.add_page(PageInfo(tab_id='one'))
    pool.add_page(PageInfo(tab_id='two'))
    pool.get_page('two').is_connected = False
    assert connected_tab_ids(pool) == {'one'}
    assert pooled_ids(pool) == {'one', 'two'}  # preserve the distinct legacy meaning
