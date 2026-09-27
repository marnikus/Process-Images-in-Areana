"""Exercise actual transport, socket receive loop and connect setup; fake only I/O."""
import asyncio
import json

import pytest

from app.browser.cdp.client import CDPClient
from app.browser.cdp import connect
from app.browser.page_recovery import page_answers, still_frozen

URL = 'ws://127.0.0.1:9223/devtools/page/IMAGE-TAB'


class Socket:
    def __init__(self, *, blackhole=False, frozen=False):
        self.queue = asyncio.Queue()
        self.blackhole, self.frozen = blackhole, frozen
        self.closed = False
        self.commands = []

    async def send(self, payload):
        msg = json.loads(payload)
        self.commands.append(msg)
        if self.blackhole:
            return
        result = {}
        if msg['method'] == 'Runtime.evaluate':
            value = 1 if msg['params']['expression'] == '1' else {'ready': True, 'src': 'generated.png'}
            result = {'result': {'value': value}}
        reply = {'id': msg['id'], 'result': result}
        if self.frozen and msg['method'] == 'Runtime.evaluate':
            reply = {'id': msg['id'], 'error': {'message': 'Execution context unavailable'}}
        await self.queue.put(json.dumps(reply))

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.queue.get()

    async def close(self):
        self.closed = True


def stalled_client():
    client = CDPClient()
    client._ws = Socket(blackhole=True)
    client._connected = True
    client._current_ws_url = URL
    client._current_tab_id = 'IMAGE-TAB'
    client.last_error_kind = 'transport'
    client.last_error = 'CDP command Runtime.evaluate timed out after 30s'
    client._receive_task = asyncio.create_task(client._receive_loop())
    return client


async def test_stalled_socket_is_replaced_without_navigation_or_submission(monkeypatch):
    client = stalled_client()
    old = client._ws
    fresh = Socket()
    opened, notes = [], []
    client.dialogs.report = notes.append

    async def open_socket(url):
        opened.append(url)
        return fresh

    monkeypatch.setattr(connect, '_create_ws_connection', open_socket)
    try:
        assert await page_answers(client, timeout_s=.01)
        assert opened == [URL] and old.closed
        assert await client.evaluate('read output') == {'ready': True, 'src': 'generated.png'}
        assert client.last_error == '' and not client._pending
        methods = [m['method'] for m in fresh.commands]
        assert methods == ['Page.enable', 'DOM.enable', 'Runtime.enable', 'Network.enable',
                           'Runtime.evaluate', 'Runtime.evaluate']
        assert any('same tab' in note for note in notes)
        assert any('restored' in note for note in notes)
    finally:
        await client.disconnect()


async def test_protocol_error_ping_does_not_clear_timeout():
    client = stalled_client()
    client._ws.blackhole = False
    client._ws.frozen = True
    client._current_ws_url = ''  # no address to repair
    try:
        assert not await page_answers(client, timeout_s=.01)
        assert client.last_error_kind == 'transport'
    finally:
        await client.disconnect()


async def test_unresponsive_replacement_is_attempted_once_for_concurrent_callers(monkeypatch):
    client = stalled_client()
    fresh = Socket(frozen=True)
    opened = []

    async def open_socket(url):
        opened.append(url)
        return fresh

    monkeypatch.setattr(connect, '_create_ws_connection', open_socket)
    try:
        assert await asyncio.gather(page_answers(client, .01), page_answers(client, .01)) == [False, False]
        assert opened == [URL]
        assert await still_frozen(client)
        assert opened == [URL] and client.last_error_kind == 'transport'
    finally:
        await client.disconnect()


async def test_cancelled_repair_cleans_up_and_propagates(monkeypatch):
    client = stalled_client()
    fresh = Socket(blackhole=True)  # domain enable never returns
    opened = asyncio.Event()

    async def open_socket(url):
        opened.set()
        return fresh

    monkeypatch.setattr(connect, '_create_ws_connection', open_socket)
    task = asyncio.create_task(page_answers(client, .01))
    await asyncio.wait_for(opened.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert fresh.closed and not client.is_connected
    assert not client._pending and client._receive_task is None


async def test_repair_deadline_and_broken_reporter_do_not_escape(monkeypatch):
    from app.browser.cdp import recovery
    client = stalled_client()
    fresh = Socket(blackhole=True)

    async def open_socket(url):
        return fresh

    def broken_reporter(note):
        raise RuntimeError('UI closed')

    client.dialogs.report = broken_reporter
    monkeypatch.setattr(connect, '_create_ws_connection', open_socket)
    monkeypatch.setattr(recovery, 'REPAIR_TIMEOUT_S', .02)
    assert not await page_answers(client, .01)
    assert fresh.closed and not client.is_connected
    assert client._receive_task is None and not client._pending
    assert client.last_error_kind == 'transport'


async def test_a_later_outage_is_rearmed_after_a_healthy_ping(monkeypatch):
    client = stalled_client()
    sockets = []

    async def open_socket(url):
        socket = Socket()
        sockets.append(socket)
        return socket

    monkeypatch.setattr(connect, '_create_ws_connection', open_socket)
    try:
        assert await page_answers(client, .01)
        sockets[0].blackhole = True
        client.last_error_kind = 'transport'
        client.last_error = 'CDP command Runtime.evaluate timed out'
        assert await page_answers(client, .01)
        assert len(sockets) == 2 and sockets[0].closed
    finally:
        await client.disconnect()


async def test_socket_open_failure_leaves_no_tasks(monkeypatch):
    client = stalled_client()

    async def open_socket(url):
        raise OSError('unreachable')

    monkeypatch.setattr(connect, '_create_ws_connection', open_socket)
    assert not await page_answers(client, .01)
    assert not client.is_connected and not client._pending
    assert client._receive_task is None
