"""One CDP socket, one event loop — whoever calls (I-76, owner log 2026-09-27 22:37–22:58).

The app runs two loops: qasync's on the Qt thread and `arena-bg-loop` (run_state). A
connection opened on one and used from the other made Qt refuse the other thread's
callbacks ("QObject::startTimer: Timers cannot be started from another thread", qasync
`assert timerid not in self.__callbacks` from `_fail_pending`), left cancelled receive
tasks pending forever ("Task was destroyed but it is pending!") and, on Windows' Proactor,
lost writes ("socket.send() raised exception") — commands Chrome never saw, 30 s timeouts,
"silent socket" re-dials. `StrictLoop` flags what qasync asserts on: a `call_soon` from a
thread that is not running the loop (`call_soon_threadsafe` is the legal door).
"""
import asyncio
import json
import threading

import pytest
import websockets

from app.browser.cdp import home_loop as hl
from app.browser.cdp import transport as tr
from app.browser.cdp.client import CDPClient

pytestmark = pytest.mark.unit


class StrictLoop(asyncio.SelectorEventLoop):
    """Like qasync: a call_soon from a thread that is not running this loop is a bug."""

    def __init__(self):
        super().__init__()
        self.cross_thread = []

    def call_soon(self, callback, *args, context=None):
        if self._thread_id is not None and threading.get_ident() != self._thread_id:
            self.cross_thread.append(getattr(callback, "__qualname__", repr(callback)))
        return super().call_soon(callback, *args, context=context)


class LoopThread:
    """A strict loop running forever on its own thread — the app's `arena-bg-loop`."""

    def __init__(self, name):
        self.loop, ready = StrictLoop(), threading.Event()
        def run():
            asyncio.set_event_loop(self.loop)
            self.loop.call_soon(ready.set)
            self.loop.run_forever()
        self.thread = threading.Thread(target=run, name=name, daemon=True)
        self.thread.start()
        ready.wait(5)

    def run(self, coro, timeout=10):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)
        self.loop.close()


class Chrome:
    """Answers every command after `delay` s; `hang()` stops answering, `drop()` closes the sockets."""

    def __init__(self, delay=0.05):
        self.delay, self.hung, self.sockets = delay, False, []
        self.server_thread = LoopThread("fake-chrome")
        self.server = self.server_thread.run(self._serve())
        self.url = f"ws://127.0.0.1:{self.server.sockets[0].getsockname()[1]}/devtools/page/T1"

    async def _serve(self):
        return await websockets.serve(self._handler, "127.0.0.1", 0)

    async def _handler(self, ws):
        self.sockets.append(ws)
        async for raw in ws:
            if self.hung:
                continue
            await asyncio.sleep(self.delay)
            await ws.send(json.dumps({"id": json.loads(raw)["id"],
                                      "result": {"result": {"type": "number", "value": 1}}}))

    def drop(self):
        async def close_all():
            for ws in self.sockets:
                await ws.close()
        self.server_thread.run(close_all())

    def stop(self):
        self.server.close()
        self.server_thread.stop()


@pytest.fixture
def world():
    chrome, bg = Chrome(), LoopThread("arena-bg-loop")
    main = StrictLoop()
    yield chrome, bg, main
    main.close()
    bg.stop()
    chrome.stop()


def _watch_sends(client, threads):
    real = client._ws.send
    async def send(payload):
        threads.append(threading.current_thread().name)
        return await real(payload)
    client._ws.send = send


def test_calls_from_the_qt_loop_run_on_the_connections_own_loop(world):
    chrome, bg, main = world
    client = CDPClient(host="127.0.0.1", port=1)
    assert bg.run(client.connect(chrome.url))
    send_threads = []
    _watch_sends(client, send_threads)

    async def like_the_watcher():
        values = [await client.evaluate("1", timeout=5) for _ in range(3)]
        await client.disconnect()
        return values

    assert main.run_until_complete(like_the_watcher()) == [1, 1, 1]
    assert set(send_threads) == {"arena-bg-loop"}          # the socket is written by its own loop only
    assert main.cross_thread == [] and bg.loop.cross_thread == []
    assert client._receive_task is None and not client.is_connected


def test_a_connection_lost_under_a_qt_loop_waiter_fails_it_now_without_crossing_threads(world):
    chrome, bg, main = world
    client = CDPClient(host="127.0.0.1", port=1)
    assert bg.run(client.connect(chrome.url))
    chrome.hung = True

    async def waiter_then_drop():
        task = asyncio.ensure_future(client.send("Runtime.evaluate", {}, timeout=20))
        await asyncio.sleep(0.2)
        chrome.drop()
        return await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 5)

    (outcome,) = main.run_until_complete(waiter_then_drop())
    assert isinstance(outcome, ConnectionError)             # failed at once, not after 20 s
    assert main.cross_thread == [] and bg.loop.cross_thread == []


def test_fail_pending_settles_each_waiter_on_its_own_loop():
    owner = LoopThread("owner")
    try:
        fut = owner.run(_make_future())
        holder = type("T", (), {})()
        holder._pending = {1: fut}
        tr._fail_pending(holder, "CDP connection lost")      # called from THIS thread, like a GC finalizer
        owner.run(asyncio.sleep(0.05))
        assert isinstance(fut.exception(), ConnectionError)
        assert owner.loop.cross_thread == []
    finally:
        owner.stop()


async def _make_future():
    """A reply future with a task awaiting it — as `send` leaves one while Chrome is silent."""
    fut = asyncio.get_running_loop().create_future()
    asyncio.ensure_future(asyncio.gather(fut, return_exceptions=True))
    await asyncio.sleep(0)
    return fut


def test_a_waiter_whose_loop_is_gone_is_skipped_not_a_crash():
    dead = asyncio.new_event_loop()
    fut = dead.create_future()
    dead.close()
    holder = type("T", (), {})()
    holder._pending = {1: fut}
    tr._fail_pending(holder, "CDP connection lost")          # no exception escapes
    assert holder._pending == {}


class Thing:
    """A transport stand-in: the decorator only needs an object to remember its home on."""

    @hl.on_home_loop
    async def where(self, fail=False):
        await asyncio.sleep(0)
        if fail:
            raise ValueError("boom")
        return threading.current_thread().name


def test_the_first_caller_claims_home_and_others_hop_to_it():
    home = LoopThread("home")
    try:
        thing = Thing()
        assert home.run(thing.where()) == "home"
        assert asyncio.run(thing.where()) == "home"
        with pytest.raises(ValueError, match="boom"):
            asyncio.run(thing.where(fail=True))
    finally:
        home.stop()


def test_a_home_loop_that_stopped_is_replaced_by_the_callers():
    thing = Thing()
    home = LoopThread("home")
    assert home.run(thing.where()) == "home"
    home.stop()
    assert asyncio.run(thing.where()) == threading.current_thread().name


def test_cancelling_the_caller_cancels_the_hopped_call_on_its_home_loop():
    home = LoopThread("home")
    try:
        seen = []

        class Slow:
            @hl.on_home_loop
            async def ping(self):
                return None

            @hl.on_home_loop
            async def wait(self):
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    seen.append(threading.current_thread().name)
                    raise

        slow = Slow()
        home.run(slow.ping())                               # the first caller's loop becomes home

        async def caller():
            task = asyncio.ensure_future(slow.wait())
            await asyncio.sleep(0.1)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await asyncio.sleep(0.1)

        asyncio.run(caller())
        assert seen == ["home"]
    finally:
        home.stop()
