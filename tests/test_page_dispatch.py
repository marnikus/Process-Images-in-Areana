"""Behavior tests exercise scheduling and the real desktop action stack."""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core.models import AppState, UrlRow
from app.ui.bridge import Bridge


def bridge_stub():
    state = AppState()
    state.urls = [UrlRow.create('https://arena.ai/c/one')]
    state.prompt = {'user_prompt': 'transform'}
    img = SimpleNamespace(id='i', selected=True, status='pending', attempt_count=0,
                          relative_path='a.png', absolute_path='/tmp/a.png',
                          assigned_url_id=None, output_path=None, error=None)
    state.images = [img]
    b = SimpleNamespace(state=state, config=SimpleNamespace(get_state=lambda k, d: d),
                        cdp=object(), _cancel_requested=False, _pause_requested=False,
                        _stop_after=False, _run_state='running')
    for name in ('_log', '_save_arena', '_emit_arena_state', '_emit_action_blocks',
                 '_emit_job_action_status'):
        setattr(b, name, Mock())
    b.job_started = SimpleNamespace(emit=Mock())
    b.job_finished = SimpleNamespace(emit=Mock())
    b._get_selected_images = lambda: state.images
    b._get_enabled_urls = lambda: state.urls
    b._get_action_blocks = lambda: []
    return b


@pytest.mark.asyncio
async def test_legacy_stack_characterization(monkeypatch):
    b = bridge_stub()
    class Controller:
        def __init__(self, *args, **kwargs):
            pass
        async def is_page_ready(self):
            return True, []
    monkeypatch.setattr('app.browser.cdp_arena.CDPArenaController', Controller)
    from app.services.page_sessions import PageSession
    await Bridge._do_run_batch(b, PageSession(b.state.urls[0], Controller(), b.state.images[0]))
    assert b.state.images[0].status == 'completed'
    assert b.state.images[0].assigned_url_id == b.state.urls[0].id
    assert b.job_started.emit.call_count == 1
    assert b.job_finished.emit.call_count == 1

from app.services.page_dispatch import PageDispatcher, run_page_batch
from app.services.page_sessions import PageSession, PageSessions, exact_url
from app.browser.page_availability import PAGE_AVAILABILITY_JS, observe_availability


class FakeClient:
    def __init__(self, *args):
        self.mode = 'steady'
        self.closed = False
        self.connected_to = None
        self.probes = 0
        self.bad = None
        self.connect_ok = True

    async def connect(self, ws_url):
        self.connected_to = ws_url
        return self.connect_ok

    async def disconnect(self):
        self.closed = True

    async def evaluate(self, js):
        assert js == PAGE_AVAILABILITY_JS
        self.probes += 1
        if self.bad:
            raise RuntimeError(self.bad)
        return {'status': self.mode}


def setup_dispatch(count=3):
    b = bridge_stub()
    template = vars(b.state.images[0])
    b.state.images = [SimpleNamespace(**dict(template, id=str(i))) for i in range(count)]
    b.state.urls.append(UrlRow.create('https://arena.ai/c/two'))
    clients = [FakeClient(), FakeClient()]
    pages = [PageSession(row, SimpleNamespace(cdp=c)) for row, c in zip(b.state.urls, clients)]
    sessions = PageSessions(b)
    dispatcher = PageDispatcher(b, sessions, .001)
    return b, pages, dispatcher


async def eventually(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(.001)
    await asyncio.wait_for(wait(), 2)


@pytest.mark.asyncio
async def test_parallel_pages_fastest_free_claims_next_and_waits_for_browser():
    b, pages, dispatcher = setup_dispatch(4)
    started = []
    releases = [asyncio.Event(), asyncio.Event()]
    async def execute(page):
        index = pages.index(page)
        started.append((index, page.image.id))
        assert page.row.last_status == 'busy'
        if len(started) <= 2:
            await releases[index].wait()
        # Returning from a job is NOT proof the page is idle.
        page.controller.cdp.mode = 'busy'
    b._do_run_batch = execute
    task = asyncio.create_task(dispatcher.run(pages))
    await eventually(lambda: len(started) == 2)
    assert {i for i, _ in started} == {0, 1}
    releases[1].set()
    await eventually(lambda: pages[1].controller.cdp.probes >= 4)
    assert len(started) == 2
    assert pages[1].row.last_status == 'busy'
    pages[1].controller.cdp.mode = 'steady'
    await eventually(lambda: len(started) == 3)
    assert started[2][0] == 1
    pages[1].controller.cdp.mode = 'steady'
    await eventually(lambda: len(started) == 4)
    assert started[3][0] == 1
    releases[0].set()
    await eventually(lambda: pages[0].controller.cdp.mode == 'busy')
    for page in pages:
        page.controller.cdp.mode = 'steady'
    await asyncio.wait_for(task, 2)
    assert len({image for _, image in started}) == 4
    assert all(p.row.last_status == 'steady' for p in pages)


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['busy', 'waiting_captcha', 'not_ready'])
async def test_external_activity_blocks_only_its_own_page(mode):
    b, pages, dispatcher = setup_dispatch(2)
    pages[0].controller.cdp.mode = mode
    claimed = []
    async def execute(page):
        claimed.append(page.row.id)
    b._do_run_batch = execute
    task = asyncio.create_task(dispatcher.run(pages))
    await eventually(lambda: len(claimed) == 2)
    await asyncio.wait_for(task, 2)
    assert claimed == [pages[1].row.id] * 2
    assert pages[0].row.last_status == mode


@pytest.mark.asyncio
async def test_pause_rechecks_before_resume_and_stop_prevents_new_claims():
    b, pages, dispatcher = setup_dispatch()
    b._pause_requested = True
    called = []
    async def execute(page):
        called.append(page.image.id)
        b._stop_after = True
    b._do_run_batch = execute
    task = asyncio.create_task(dispatcher.run(pages))
    await eventually(lambda: all(p.controller.cdp.probes >= 3 for p in pages))
    assert called == []
    pages[0].controller.cdp.mode = 'busy'
    b._pause_requested = False
    await asyncio.wait_for(task, 2)
    assert len(called) == 1
    assert len(dispatcher.pending) == 2


@pytest.mark.asyncio
async def test_probe_failure_is_not_idle_and_other_page_survives():
    b, pages, dispatcher = setup_dispatch(1)
    pages[0].controller.cdp.bad = 'socket lost'
    called = []
    async def execute(page):
        called.append(page.row.id)
    b._do_run_batch = execute
    await dispatcher.run(pages)
    assert called == [pages[1].row.id]
    assert pages[0].row.last_status == 'unavailable'
    assert 'socket lost' in pages[0].row.error


@pytest.mark.asyncio
async def test_cancel_joins_all_workers_and_does_not_mark_pages_steady():
    b, pages, dispatcher = setup_dispatch()
    active, ended = set(), set()
    async def execute(page):
        active.add(page.row.id)
        try:
            await asyncio.Event().wait()
        finally:
            ended.add(page.row.id)
    b._do_run_batch = execute
    task = asyncio.create_task(dispatcher.run(pages))
    await eventually(lambda: len(active) == 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ended == active
    assert all(p.row.last_status == 'unchecked' for p in pages)
    assert len(dispatcher.pending) == 1


@pytest.mark.asyncio
async def test_cancel_predicate_and_job_exception():
    b, pages, dispatcher = setup_dispatch(1)
    b._cancel_requested = True
    assert not await dispatcher.wait_steady(pages[0])
    b._cancel_requested = False
    async def execute(page):
        raise RuntimeError('execution failed')
    b._do_run_batch = execute
    await dispatcher.run(pages[:1])
    assert pages[0].row.last_status == 'unavailable'
    assert pages[0].row.error == 'execution failed'


@pytest.mark.asyncio
async def test_stop_while_all_pages_busy_keeps_queue_pending():
    b, pages, dispatcher = setup_dispatch(2)
    for page in pages:
        page.controller.cdp.mode = 'busy'
    b._do_run_batch = Mock(side_effect=AssertionError('must not run'))
    task = asyncio.create_task(dispatcher.run(pages))
    await eventually(lambda: all(p.row.last_status == 'busy' for p in pages))
    b._stop_after = True
    await asyncio.wait_for(task, 2)
    assert len(dispatcher.pending) == 2
    await dispatcher.run([])
    assert 'No connected eligible pages' in b._log.call_args_list[-1].args[0]


@pytest.mark.asyncio
async def test_exact_matching_deduplicates_targets_and_owns_connections():
    b = bridge_stub()
    b.state.urls.extend([UrlRow.create(b.state.urls[0].url),
                         UrlRow.create('https://arena.ai/c/missing'),
                         UrlRow.create('https://arena.ai/c/broken')])
    tabs = [SimpleNamespace(id='one', url=b.state.urls[0].url, ws_url='ws://one'),
            SimpleNamespace(id='bad', url=b.state.urls[-1].url, ws_url='ws://bad')]
    async def fetch():
        return tabs
    b.cdp = SimpleNamespace(fetch_tabs=fetch, get_host_port=lambda: ('host', 9222))
    created = []
    def factory(*args):
        assert args == ('host', 9222)
        client = FakeClient()
        client.connect_ok = not created
        created.append(client)
        return client
    sessions = PageSessions(b, factory)
    pages = await sessions.open()
    assert len(pages) == 1
    assert pages[0].controller.cdp is created[0]
    assert created[0].connected_to == 'ws://one'
    assert all(r.last_status == 'unavailable' for r in b.state.urls[1:])
    await sessions.close()
    assert all(c.closed for c in created)
    assert sessions.clients == []
    assert exact_url(' HTTPS://Arena.ai/c/AbC?q=Case#fragment ') == 'https://arena.ai/c/AbC?q=Case'
    assert exact_url('https://arena.ai') == 'https://arena.ai/'


@pytest.mark.asyncio
async def test_session_disconnect_error_logged_and_remaining_clients_closed():
    b = bridge_stub()
    sessions = PageSessions(b)
    bad, good = FakeClient(), FakeClient()
    async def broken():
        raise RuntimeError('close failed')
    bad.disconnect = broken
    sessions.clients = [bad, good]
    await sessions.close()
    assert good.closed
    assert 'close failed' in b._log.call_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('result', [None, {}, {'status': 'unknown'}, False])
async def test_invalid_observation_is_broken_not_steady(result):
    async def evaluate(js):
        return result
    with pytest.raises(RuntimeError):
        await observe_availability(SimpleNamespace(cdp=SimpleNamespace(evaluate=evaluate)))


@pytest.mark.asyncio
@pytest.mark.parametrize('scenario', ['empty', 'normal', 'error', 'cancel'])
async def test_coordinator_lifecycle_always_closes_connections(monkeypatch, scenario):
    b = bridge_stub()
    events = []
    if scenario == 'empty':
        b.state.images.clear()
    class Sessions:
        def __init__(self, bridge):
            assert bridge is b
        async def open(self):
            events.append('open')
            if scenario == 'error':
                raise RuntimeError('discovery failed')
            if scenario == 'cancel':
                raise asyncio.CancelledError()
            return []
        async def close(self):
            events.append('close')
    monkeypatch.setattr('app.services.page_dispatch.PageSessions', Sessions)
    if scenario == 'cancel':
        with pytest.raises(asyncio.CancelledError):
            await run_page_batch(b)
    else:
        await run_page_batch(b)
    assert events[-1] == 'close'
    assert b._run_state == 'idle'
    b._emit_arena_state.assert_called_once()


@pytest.mark.asyncio
async def test_real_action_stack_uses_reserved_cdp_not_shared_connection():
    from app.core.action_blocks import create_default_block
    b = bridge_stub()
    block = create_default_block('HIGHLIGHT')
    block.pre_delay_ms = 0
    b._get_action_blocks = lambda: [block]
    clients = []
    for _ in range(2):
        client = SimpleNamespace(calls=[])
        async def evaluate(js, target=client):
            target.calls.append(js)
            return '{"found":true,"rect":{"x":1,"y":2,"width":3,"height":4}}'
        client.evaluate = evaluate
        clients.append(client)
    b.cdp = SimpleNamespace(evaluate=Mock(side_effect=AssertionError('shared CDP used')))
    pages = [PageSession(UrlRow.create(f'https://arena.ai/c/{i}'),
                         SimpleNamespace(cdp=c), SimpleNamespace(**vars(b.state.images[0])))
             for i, c in enumerate(clients)]
    await asyncio.gather(*(Bridge._do_run_batch(b, p) for p in pages))
    assert all(c.calls for c in clients)
    assert all(p.image.assigned_url_id == p.row.id for p in pages)
    assert all(p.image.status == 'completed' for p in pages)
    assert b._run_state == 'running'  # only coordinator may finish the batch


@pytest.mark.parametrize('state', ['running', 'paused', 'stopping'])
def test_start_cannot_overlap_an_existing_batch(state):
    import json
    b = bridge_stub()
    b._run_state = state
    b.cdp = SimpleNamespace(is_connected=True)
    b._schedule_coro = Mock(side_effect=AssertionError('overlapping start'))
    result = json.loads(Bridge.start_run(b))
    assert result == {'ok': False, 'error': 'already running'}


def test_idle_cancel_is_noop_and_active_cancel_waits_for_cleanup():
    import json
    b = bridge_stub()
    b._run_state = 'idle'
    assert json.loads(Bridge.cancel_current(b)) == {'ok': True}
    assert b._run_state == 'idle'
    b._run_state = 'running'
    b._batch_future = Mock()
    b.state.images[0].status = 'processing'
    Bridge.cancel_current(b)
    assert b._run_state == 'stopping'
    assert b._cancel_requested
    b._batch_future.cancel.assert_called_once()
    assert b.state.images[0].status == 'failed'


def test_global_watcher_does_not_control_batch_workers():
    b = bridge_stub()
    b.cdp = SimpleNamespace(is_connected=True)
    assert Bridge._get_watcher_cdp_controller(b) is None
    b._run_state = 'idle'
    assert Bridge._get_watcher_cdp_controller(b).cdp is b.cdp


@pytest.mark.asyncio
async def test_real_submit_routes_visual_runner_to_assigned_page(monkeypatch):
    from app.core.action_blocks import create_default_block
    b = bridge_stub()
    block = create_default_block('SUBMIT')
    block.pre_delay_ms = 0
    b._get_action_blocks = lambda: [block]
    client = object()
    calls = []
    async def visual_click(cdp, request, engine):
        calls.append(cdp)
        return 'ok'
    monkeypatch.setattr('app.ui.bridge.find_and_click', visual_click)
    page = PageSession(b.state.urls[0], SimpleNamespace(cdp=client), b.state.images[0])
    await Bridge._do_run_batch(b, page)
    assert calls == [client]
    assert page.image.status == 'completed'


@pytest.mark.asyncio
async def test_steady_requires_consecutive_checks_after_generation_flicker():
    b, pages, dispatcher = setup_dispatch(1)
    client = pages[0].controller.cdp
    states = iter(['steady', 'busy', 'steady', 'steady'])
    async def evaluate(js):
        client.probes += 1
        return {'status': next(states, 'steady')}
    client.evaluate = evaluate
    started_at = []
    async def execute(page):
        started_at.append(client.probes)
    b._do_run_batch = execute
    await dispatcher.run(pages[:1])
    assert started_at == [4]
    assert pages[0].row.last_status == 'steady'


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel', [False, True])
async def test_interrupted_processing_image_is_failed_not_left_in_progress(cancel):
    b, pages, dispatcher = setup_dispatch(1)
    async def execute(page):
        page.image.status = 'processing'
        if cancel:
            raise asyncio.CancelledError()
        raise RuntimeError('lost browser')
    b._do_run_batch = execute
    if cancel:
        with pytest.raises(asyncio.CancelledError):
            await dispatcher.run(pages[:1])
    else:
        await dispatcher.run(pages[:1])
    assert b.state.images[0].status == 'failed'
    assert b.state.images[0].error == ('Cancelled by user' if cancel else 'lost browser')
