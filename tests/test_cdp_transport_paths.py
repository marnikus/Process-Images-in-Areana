"""Error-path coverage for app/browser/cdp/transport.py.

RULE 8: no live Chrome — dead sockets and throwing tasks are faked so the
disconnect/receive-loop guards (swallow-and-continue) are pinned for real.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.browser.cdp.transport import CDPTransport, _exception_text, _protocol_text

pytestmark = pytest.mark.unit


class DeadSocket:
    """An async-iterable websocket whose iterator dies immediately."""

    def __aiter__(self):
        raise RuntimeError("socket died")


async def _boom():
    raise RuntimeError("boom")


async def test_disconnect_swallows_task_and_close_errors():
    t = CDPTransport()
    task = asyncio.ensure_future(_boom())
    await asyncio.sleep(0)                     # let it finish with its exception
    t._receive_task = task
    t._ws = SimpleNamespace(close=_boom)       # close() raises too
    await t.disconnect()                       # must not raise
    assert t._ws is None and t._receive_task is None
    assert t._connected is False


async def test_receive_loop_reports_error_and_disconnected_guard():
    t = CDPTransport()
    t._connected = True
    t._current_ws_url = "ws://127.0.0.1:9222/devtools/page/x"
    t._ws = DeadSocket()
    errors = []
    t.error.connect(errors.append)
    t.disconnected = SimpleNamespace(emit=lambda: (_ for _ in ()).throw(RuntimeError("emit boom")))
    await t._receive_loop()
    assert len(errors) == 1 and "receive error" in errors[0]
    assert t._connected is False


def test_protocol_text_non_dict_and_exception_text_junk():
    assert _protocol_text("plain failure") == "plain failure"
    assert _exception_text(["junk"]) == "['junk']"


# ── 2026-09-25: a dead connection must fail commands NOW, not after timeout ──

class SendableDeadSocket(DeadSocket):
    """Accepts sends into the void — the black-holed socket from the owner log:
    writes succeed, the receive side is already gone, nobody will ever answer."""

    def __init__(self):
        self.sent = []

    async def send(self, payload):
        self.sent.append(payload)


class LiveQuietSocket:
    """Live socket, no answer ever — the honest-timeout control case."""

    def __aiter__(self):
        async def _forever():
            await asyncio.sleep(3600)
            yield ""
        return _forever()

    async def send(self, payload):
        pass


async def test_receive_loop_death_fails_pending_commands_immediately():
    """Connection lost → in-flight commands get ConnectionError at once.

    The owner log showed `Runtime.evaluate timed out after 30s` while the
    socket was already dead (no close frame) — the pending future must be
    failed by the loop's teardown, not left to burn its full wait_for.
    """
    t = CDPTransport()
    t._connected = True
    t._current_ws_url = "ws://127.0.0.1:9223/devtools/page/x"
    t._ws = DeadSocket()
    fut = asyncio.get_running_loop().create_future()
    t._pending[1] = fut
    await t._receive_loop()
    assert not t._pending                              # teardown drained them
    with pytest.raises(ConnectionError):               # NOT a 30 s TimeoutError
        await asyncio.wait_for(fut, timeout=0.5)


async def test_send_after_receive_death_fails_immediately_not_30s():
    """After `CDP disconnected` the next command fails in ms (was: 2×30 s)."""
    t = CDPTransport()
    t._connected = True
    t._current_ws_url = "ws://127.0.0.1:9223/devtools/page/x"
    t._ws = SendableDeadSocket()
    await t._receive_loop()                            # dies → teardown detaches
    assert t._ws is None
    with pytest.raises(ConnectionError):
        await asyncio.wait_for(
            t.send("Runtime.evaluate", {"expression": "1"}, timeout=30), timeout=1)


async def test_disconnect_fails_pending_instead_of_dropping_it():
    """disconnect() used to `clear()` the map — waiters still burned timeout."""
    t = CDPTransport()

    async def _ok_close():
        return None

    t._ws = SimpleNamespace(close=_ok_close)
    fut = asyncio.get_running_loop().create_future()
    t._pending[7] = fut
    await t.disconnect()
    assert t._ws is None and t._pending == {}
    with pytest.raises(ConnectionError):
        await asyncio.wait_for(fut, timeout=0.5)


async def test_unanswered_command_on_a_live_socket_still_times_out():
    """The honest control: a LIVE socket with no answer keeps its TimeoutError."""
    t = CDPTransport()
    t._connected = True
    t._ws = LiveQuietSocket()
    with pytest.raises(TimeoutError):
        await t.send("Runtime.evaluate", {"expression": "1"}, timeout=0.1)
    assert t._pending == {}                            # timeout path still pops
