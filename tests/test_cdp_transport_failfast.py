"""L-9: a dead CDP socket must fail in-flight commands FAST (RED at base).

User-visible symptom (real run, 2026-09-20): after the automated tab's
websocket died without a close frame, the log showed the disconnect, and
then — 30 s late — `evaluate transport error: TimeoutError`. The receive
loop's post-mortem flipped `_connected` but left `_pending` futures and
the `_ws` handle behind, so every in-flight command sat out its full
timeout against a target that can never answer. A transport error after a
known disconnect must arrive in milliseconds, honestly labelled.

Harness note: the abrupt close is modelled by upgrading the FakeWS class
in place (`__class__` swap) because `async for` resolves `__anext__` on
the type — instance attributes would never be seen.
"""

import asyncio
import sys
from types import ModuleType

import pytest

from tests.conftest import FakeCDPServer, FakeWS, make_client

pytestmark = pytest.mark.unit


class AbruptWS(FakeWS):
    """A socket whose peer dies with no close frame (the real-world shape)."""

    async def __anext__(self):
        if getattr(self, "abrupt", False):
            raise ConnectionError("no close frame received or sent")
        return await super().__anext__()


def _responder(method, params, server):
    # NO_REPLY only for the command under test — connect-time `*.enable`
    # handshakes must answer, or `connect()` itself sits out 30 s timeouts.
    if method == "Stall":
        return "NO_REPLY", None
    return {"ok": True}, None


@pytest.fixture
def abrupt_server(monkeypatch):
    server = FakeCDPServer(responder=_responder)
    original_connect = server.connect

    async def connect(url, **kwargs):
        ws = await original_connect(url, **kwargs)
        ws.__class__ = AbruptWS
        return ws

    server.connect = connect
    fake_mod = ModuleType("websockets")
    fake_mod.connect = server.connect
    monkeypatch.setitem(sys.modules, "websockets", fake_mod)
    return server


async def _kill_abruptly(server):
    """Die mid-stream: wake the blocked read, then raise like a dead peer."""
    ws = server.last_ws
    ws.abrupt = True
    ws.push("wake")  # not JSON — the loop discards it and re-enters __anext__
    await asyncio.sleep(0.05)


async def test_abrupt_socket_death_fails_inflight_commands_fast(abrupt_server):
    client = make_client(abrupt_server)
    await client.connect("ws://10.0.0.9:9222/devtools/page/t1")
    inflight = asyncio.ensure_future(client.send("Stall", timeout=30))
    await _kill_abruptly(abrupt_server)
    with pytest.raises(ConnectionError):  # NOT a 30 s TimeoutError
        await asyncio.wait_for(asyncio.shield(inflight), timeout=1.0)
    assert client.is_connected is False


async def test_deliberate_disconnect_fails_inflight_commands_fast(abrupt_server):
    client = make_client(abrupt_server)
    await client.connect("ws://10.0.0.9:9222/devtools/page/t1")
    inflight = asyncio.ensure_future(client.send("Stall", timeout=30))
    await asyncio.sleep(0.02)  # let the command reach the pending table
    await client.disconnect()
    with pytest.raises(ConnectionError):  # base orphaned the future instead
        await asyncio.wait_for(asyncio.shield(inflight), timeout=1.0)


async def test_evaluate_after_socket_death_returns_none_fast(abrupt_server):
    client = make_client(abrupt_server)
    await client.connect("ws://10.0.0.9:9222/devtools/page/t1")
    await _kill_abruptly(abrupt_server)
    result = await asyncio.wait_for(client.evaluate("1 + 1"), timeout=1.0)
    assert result is None
    assert client.last_error_kind == "transport"
