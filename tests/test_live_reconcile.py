"""S10 audit: execute the S6 loop/bridge instead of its former placeholders."""
import asyncio
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo
from app.core.models import UrlRow
from app.services.live.bus import live_bus
from app.services.live.reconcile import LiveDeps, reconcile_loop, reconcile_once
from app.ui.panels import browser_tabs
from tests.characterization.harness import build_bridge


@pytest.fixture
def env(tmp_path):
    env = build_bridge(tmp_path, [], pool=PagePool())
    env.bridge.state.urls = []
    env.cfg.set_state(url_pattern='arena.ai')
    return env


def tab(tid, url=None):
    return NS(id=tid, title='Arena', url=url or 'https://arena.ai/' + tid,
              ws_url='ws://test/devtools/page/' + tid)


def deps_for(env, tabs):
    return LiveDeps(fetch_tabs=AsyncMock(return_value=tabs), join_tab=AsyncMock(),
                    commit=Mock(), log=Mock())


@pytest.mark.asyncio
async def test_interval_is_reread_and_cancellation_exits_after_real_passes(env, monkeypatch):
    deps = deps_for(env, [])
    waits = []

    async def wait(timeout):
        waits.append(timeout)
        if len(waits) == 1:
            env.cfg.set_state(url_reconcile_interval_ms=750)
            return 'interval'
        raise asyncio.CancelledError

    monkeypatch.setattr(live_bus(env.bridge), 'wait', wait)
    await reconcile_loop(env.bridge, deps)
    assert waits == [5.0, 0.75]
    assert deps.fetch_tabs.await_count == 2
    assert env.bridge._reconcile_passes == 2
    assert env.bridge._last_reconcile_at > 0


@pytest.mark.asyncio
@pytest.mark.parametrize('broken', [False, True])
async def test_empty_or_broken_fetch_does_not_remove_rows_and_errors_are_logged(env, broken):
    row = UrlRow.create('https://arena.ai/gone', tab_id='gone')
    env.bridge.state.urls = [row]
    deps = deps_for(env, [])
    if broken:
        deps.fetch_tabs.side_effect = OSError('Chrome disconnected')
    report = await reconcile_once(env.bridge, deps, 'auto')
    assert env.bridge.state.urls == [row]
    assert report.removed == 0
    deps.commit.assert_not_called()
    deps.join_tab.assert_not_awaited()
    assert deps.log.call_count == int(broken)
    if broken:
        assert 'Chrome disconnected' in deps.log.call_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('state', ['idle', 'running', 'waiting', 'paused'])
async def test_new_tab_is_added_and_existing_row_claimed_in_every_run_state(env, state):
    row = UrlRow.create('https://arena.ai/one')
    env.bridge.state.urls = [row]
    env.bridge._run_state = state
    tabs = [tab('one'), tab('two')]
    deps = deps_for(env, tabs)
    report = await reconcile_once(env.bridge, deps, 'auto')
    assert row.tab_id == 'one'
    assert [r.tab_id for r in env.bridge.state.urls] == ['one', 'two']
    assert (report.added, report.linked, report.joined) == (1, 1, 2)
    assert [c.args[0] for c in deps.join_tab.await_args_list] == [t.ws_url for t in tabs]
    deps.commit.assert_called_once()
    assert env.bridge._run_state == state


@pytest.mark.asyncio
async def test_closed_row_is_removed_after_three_misses_and_clears_assignment(env):
    row = UrlRow.create('https://arena.ai/gone', tab_id='gone')
    env.bridge.state.urls = [row]
    env.bridge.state.images[0].assigned_url_id = row.id
    # A healthy, nonmatching tab list distinguishes "closed" from CDP down.
    deps = deps_for(env, [tab('other', 'https://example.org/')])
    for _ in range(2):
        assert (await reconcile_once(env.bridge, deps, 'auto')).removed == 0
        assert env.bridge.state.urls == [row]
    assert (await reconcile_once(env.bridge, deps, 'auto')).removed == 1
    assert env.bridge.state.urls == []
    assert env.bridge.state.images[0].assigned_url_id is None
    deps.commit.assert_called_once()
    assert any('tab_gone' in c.args[0] for c in deps.log.call_args_list)


@pytest.mark.asyncio
async def test_busy_closed_tab_is_deferred(env):
    row = UrlRow.create('https://arena.ai/gone', tab_id='gone')
    env.bridge.state.urls = [row]
    env.bridge._page_pool.add_page(PageInfo(tab_id='gone', current_image='pic1.png'))
    env.bridge._reconcile_misses = {'gone': 4}
    report = await reconcile_once(env.bridge, deps_for(env, [tab('other', 'https://example.org/')]), 'auto')
    assert report.removed == 0
    assert env.bridge.state.urls == [row]


@pytest.mark.asyncio
async def test_dedupe_only_change_still_commits(env):
    rows = [UrlRow.create('https://arena.ai/one', tab_id='one') for _ in range(2)]
    for row in rows:
        row.receiver = True
    env.bridge.state.urls = rows[:]
    env.bridge._page_pool.add_page(PageInfo(tab_id='one'))
    deps = deps_for(env, [tab('one')])
    report = await reconcile_once(env.bridge, deps, 'auto')
    assert env.bridge.state.urls == [rows[0]]
    assert (report.added, report.linked, report.removed, report.joined) == (0, 0, 0, 0)
    deps.commit.assert_called_once()


@pytest.mark.asyncio
async def test_manual_slot_runs_real_reconcile_and_ui_commit_wakes_bus(env, monkeypatch):
    bridge = env.bridge
    row = UrlRow.create('https://arena.ai/one')
    bridge.state.urls = [row]
    bridge._page_pool.add_page(PageInfo(tab_id='one'))  # no network join required
    bridge.cdp.fetch_tabs = AsyncMock(return_value=[tab('one')])
    tasks = []
    # Scheduling is the boundary. The submitted coroutine and all panel/deps code run.
    monkeypatch.setattr(browser_tabs, 'schedule_coro', lambda b, coro: tasks.append(asyncio.create_task(coro)))
    assert bridge.auto_connect_scan('manual') == 'pending'
    await asyncio.gather(*tasks)
    assert len(tasks) == 1
    assert row.tab_id == 'one'
    assert bridge._auto_scan_running is False
    assert 'urls' in live_bus(bridge).reasons()
    payload = json.loads(env.recs['arena_state_updated'].calls[-1][0])
    assert payload['urls'][0]['tab_id'] == 'one'


@pytest.mark.asyncio
async def test_reconcile_does_not_advertise_a_disconnected_pool_page_as_receiver(env):
    row = UrlRow.create('https://arena.ai/one', tab_id='one')
    row.receiver = True
    env.bridge.state.urls = [row]
    env.bridge._page_pool.add_page(PageInfo(tab_id='one', is_connected=False))
    deps = deps_for(env, [tab('one')])
    await reconcile_once(env.bridge, deps, 'auto')
    assert row.receiver is False
