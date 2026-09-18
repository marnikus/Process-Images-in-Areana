"""CDP command replies and asynchronous event fan-out."""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from app.browser.cdp_events import CDPEventRouter, route_cdp_message


@pytest.mark.unit
def test_route_resolves_command_reply():
    loop = asyncio.new_event_loop()
    try:
        future = loop.create_future()
        client = SimpleNamespace(_pending={7: future}, events=CDPEventRouter())
        route_cdp_message(client, {"id": 7, "result": {"ok": True}})
        result = loop.run_until_complete(asyncio.wait_for(future, timeout=1))
        assert result["result"]["ok"] is True
        assert client._pending == {}
    finally:
        loop.close()


@pytest.mark.unit
def test_reply_from_worker_thread_uses_future_owner_loop():
    loop = asyncio.new_event_loop()
    try:
        future = loop.create_future()
        client = SimpleNamespace(_pending={8: future}, events=CDPEventRouter())
        worker = threading.Thread(target=route_cdp_message,
                                  args=(client, {"id": 8, "result": {"threaded": True}}))
        worker.start()
        worker.join(timeout=1)
        result = loop.run_until_complete(asyncio.wait_for(future, timeout=1))
        assert result["result"]["threaded"] is True
    finally:
        loop.close()


@pytest.mark.unit
def test_event_listener_add_remove_and_exception_isolation():
    router = CDPEventRouter()
    seen = []
    good = lambda message: seen.append(message["method"])
    router.add(lambda _message: (_ for _ in ()).throw(RuntimeError("boom")))
    router.add(good)
    router.dispatch({"method": "Network.responseReceived", "params": {}})
    router.remove(good)
    router.dispatch({"method": "Page.loadEventFired", "params": {}})
    assert seen == ["Network.responseReceived"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_event_listener_is_scheduled():
    router = CDPEventRouter()
    completed = asyncio.Event()

    async def listener(_message):
        completed.set()

    router.add(listener)
    router.dispatch({"method": "Network.loadingFinished", "params": {}})
    await asyncio.wait_for(completed.wait(), timeout=1)
