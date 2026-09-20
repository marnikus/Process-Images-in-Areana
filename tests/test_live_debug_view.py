"""S9 RED: real bridge serialization, queue rule and read-only pause evidence."""
import copy
import json
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo
from app.core.pause_clock import PauseClock
from app.services.live import debug_view
from app.services.live.feed import eligible_images
from app.ui.panels.layout_state import emit_arena_state
from app.ui.services.arena_serialize import arena_to_js
from tests.characterization.harness import build_bridge


@pytest.fixture
def env(tmp_path):
    return build_bridge(tmp_path, [], n_images=6, pool=PagePool())


def test_live_view_is_read_only_and_does_not_sample_pool(env, monkeypatch):
    pool = env.bridge._page_pool
    spy = Mock(wraps=pool.status_snapshot)
    monkeypatch.setattr(pool, 'status_snapshot', spy)
    before = copy.deepcopy(env.bridge.state.to_dict())
    assert debug_view.live_view(env.bridge)['queued'] == 6
    assert env.bridge.state.to_dict() == before
    spy.assert_not_called()
    pool.status_snapshot()  # positive control for the observation counter
    spy.assert_called_once()


def test_next_queued_follows_eligibility_and_order(env):
    images = env.bridge.state.images
    for img, status in zip(images, ['completed', 'processing', 'pending', 'failed', 'needs_review', 'selected']):
        img.status = status
    images[2].selected = False
    assert debug_view.next_queued(images) == 'pic4.png'
    assert debug_view.next_queued([]) == ''
    assert debug_view.next_queued(images[:3]) == ''
    assert debug_view.live_view(env.bridge)['queued'] == len(eligible_images(images)) == 3
    images[3].selected = False
    assert debug_view.live_view(env.bridge)['next_image'] == 'pic5.png'


def test_receiver_counts_use_flag_not_enabled_or_pool(env):
    from app.core.models import UrlRow
    rows = [UrlRow.create('https://arena.ai/' + str(i), enabled=False) for i in range(5)]
    for row in rows[:3]:
        row.receiver = True
    env.bridge.state.urls = rows
    assert debug_view.receiver_counts(rows) == {'total': 5, 'receivers': 3, 'not_receivers': 2}
    assert debug_view.receiver_counts([]) == {'total': 0, 'receivers': 0, 'not_receivers': 0}
    assert debug_view.live_view(env.bridge)['receivers'] == debug_view.receiver_counts(rows)


def test_cadence_and_run_state_are_typed_and_json_safe(env):
    env.cfg.set_state(url_reconcile_interval_ms=1200)
    env.bridge._last_reconcile_at = 1000.25
    env.bridge._reconcile_passes = 3
    env.bridge._run_state = 'paused'
    view = debug_view.live_view(env.bridge)
    assert view['url_interval_ms'] == 1200
    assert view['last_pass_at'] == 1000.25
    assert view['passes'] == 3
    assert view['run_state'] == 'paused'
    assert json.loads(json.dumps(view)) == view


def test_progress_push_and_initial_getter_agree_without_changing_arena_push(env):
    expected_arena = copy.deepcopy(arena_to_js(env.bridge.state))
    before = copy.deepcopy(env.bridge.state.to_dict())
    emit_arena_state(env.bridge)
    prog = json.loads(env.recs['progress_updated'].calls[-1][0])
    assert prog['live']['queued'] == 6
    assert prog['live']['next_image'] == 'pic1.png'
    assert json.loads(env.recs['arena_state_updated'].calls[-1][0]) == expected_arena
    initial = json.loads(env.bridge.get_arena_state())
    assert initial['progress']['live'] == prog['live']
    del initial['progress']['live']
    assert initial == expected_arena
    assert env.bridge.state.to_dict() == before


def test_off_payload_has_no_captcha_wording_or_probe(env):
    env.cfg.set_state(watcher_enabled=False)
    env.bridge._page_pool.add_page(PageInfo(tab_id='t1'))
    env.bridge._page_pool.mark_waiting('t1', 'captcha')
    view = debug_view.live_view(env.bridge)
    assert view['queued'] == 6
    assert 'captcha' not in json.dumps(view).lower()


def waiting_pool(env):
    pool = env.bridge._page_pool
    pool.add_page(PageInfo(tab_id='t1'))
    pool.mark_busy('t1', 'job-1')
    pool.mark_waiting('t1', 'captcha')
    clock = PauseClock(300)
    clock.note(12)
    pool.register_client('t1', None, NS(pause_clock=clock))
    return pool, clock


def test_pool_pause_evidence_reads_real_clock_once_without_mutation(env, monkeypatch):
    from app.ui.services.pool_debug import pool_snapshot
    pool, clock = waiting_pool(env)
    env.cfg.set_state(watcher_enabled=True)
    before = copy.deepcopy(pool.status_snapshot())
    spy = Mock(wraps=pool.status_snapshot)
    monkeypatch.setattr(pool, 'status_snapshot', spy)
    snapshot = pool_snapshot(env.bridge)
    spy.assert_called_once()
    assert snapshot['waits_in_scope'] is True
    assert snapshot['pages'][0]['pause'] == {'absorbed_s': 12, 'cap_s': 300, 'remaining_s': 288}
    assert clock.total == 12
    assert pool.status_snapshot() == before
    json.dumps(snapshot, allow_nan=False)


def test_pool_off_does_not_even_read_controllers_and_missing_clock_is_unknown(env, monkeypatch):
    from app.ui.services.pool_debug import pool_snapshot
    pool, _ = waiting_pool(env)
    spy = Mock(wraps=pool.get_clients)
    monkeypatch.setattr(pool, 'get_clients', spy)
    env.cfg.set_state(watcher_enabled=False)
    snapshot = pool_snapshot(env.bridge)
    assert snapshot['waits_in_scope'] is False
    assert 'pause' not in snapshot['pages'][0]
    spy.assert_not_called()
    env.cfg.set_state(watcher_enabled=True)
    pool.register_client('t1', None, NS())
    assert 'pause' not in pool_snapshot(env.bridge)['pages'][0]
    spy.assert_called_once_with('t1')


@pytest.mark.parametrize('path', ['emit', 'get'])
def test_both_existing_pool_signal_paths_carry_evidence(env, path):
    waiting_pool(env)
    env.cfg.set_state(watcher_enabled=True)
    if path == 'get':
        reply = json.loads(env.bridge.get_page_pool_status())
        assert reply['pages'][0]['pause']['cap_s'] == 300
    else:
        env.bridge._emit_pool_status()
    payload = json.loads(env.recs['page_pool_updated'].calls[-1][0])
    assert payload['pages'][0]['pause']['remaining_s'] == 288


def test_uncapped_and_disappearing_controller_telemetry_is_json_safe(env, monkeypatch):
    from app.ui.services.pool_debug import pool_snapshot
    pool, _ = waiting_pool(env)
    env.cfg.set_state(watcher_enabled=True)
    pool.register_client('t1', None, NS(pause_clock=PauseClock()))
    snap = pool_snapshot(env.bridge)
    assert snap['pages'][0]['pause']['remaining_s'] is None
    json.dumps(snap, allow_nan=False)
    monkeypatch.setattr(pool, 'get_clients', Mock(side_effect=RuntimeError('disconnected')))
    assert 'pause' not in pool_snapshot(env.bridge)['pages'][0]


@pytest.mark.asyncio
async def test_idle_reconcile_publishes_fresh_cadence_without_a_commit(env, monkeypatch):
    from app.services.live.reconcile import reconcile_loop
    from app.services.live.bus import live_bus
    from app.ui.panels.browser_tabs import live_deps
    from unittest.mock import AsyncMock
    bridge = env.bridge
    bridge.state.urls = []
    bridge.cdp.fetch_tabs = AsyncMock(return_value=[])
    saved = Mock()
    monkeypatch.setattr(bridge, '_save_arena', saved)

    async def wait_once(timeout):
        bridge._stop_reconcile = True
        return ''

    monkeypatch.setattr(live_bus(bridge), 'wait', wait_once)
    await reconcile_loop(bridge, live_deps(bridge))
    assert bridge._reconcile_passes == 1
    assert json.loads(env.recs['progress_updated'].calls[-1][0])['live']['passes'] == 1
    assert json.loads(env.recs['page_pool_updated'].calls[-1][0])['pages'] == []
    saved.assert_not_called()
