"""S4 — LiveBus: one wake event per bridge — thread-safe, drained once, throttled."""

import threading
import time

import pytest

from app.services.live.bus import LiveBus, live_bus

pytestmark = pytest.mark.unit


class SpyLoop:
    def __init__(self):
        self.calls = []

    def call_soon_threadsafe(self, fn):
        self.calls.append(fn)


class Clock(dict):
    def set_state(self, **kw):
        self.update(kw)


def test_wake_from_another_thread_releases_the_waiter(event_loop):
    bus = LiveBus()
    out = {}

    async def scenario():
        bus.attach(__import__("asyncio").get_running_loop())
        threading.Thread(target=lambda: bus.wake("queue"), daemon=True).start()
        wall = time.monotonic()
        out["reason"] = await bus.wait(5.0)
        out["wall_s"] = time.monotonic() - wall

    event_loop.run_until_complete(scenario())
    assert out["reason"] == "queue"
    assert out["wall_s"] < 1.0          # no bounded-poll granularity


def test_wait_times_out_with_an_empty_reason(event_loop):
    bus = LiveBus()

    async def scenario():
        bus.attach(__import__("asyncio").get_running_loop())
        assert await bus.wait(0.05) == ""

    event_loop.run_until_complete(scenario())


def test_reasons_drain_once_and_do_not_stick(event_loop):
    bus = LiveBus()
    bus.wake("reset_all")               # before any loop attaches — must not be lost
    bus.wake("scan")

    async def scenario():
        bus.attach(__import__("asyncio").get_running_loop())
        first = await bus.wait(0.2)
        second = await bus.wait(0.2)
        third = await bus.wait(0.05)
        return first, second, third

    assert event_loop.run_until_complete(scenario()) == ("reset_all", "scan", "")


def test_throttle_one_per_window(monkeypatch):
    tick = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: tick[0])
    bus = LiveBus()
    assert bus.throttle("no tab", 300) is True
    assert bus.throttle("no tab", 300) is False     # inside the window
    tick[0] += 0.4
    assert bus.throttle("no tab", 300) is True      # window passed
    assert bus.throttle("other key", 300) is True   # keys are independent


def test_wake_without_a_loop_is_safe_but_queue_calls_the_loop():
    bus = LiveBus()
    bus.wake("anything")                # no loop attached: records only, never raises
    spy = SpyLoop()
    bus.attach(spy)
    bus.wake("reset_all")
    assert spy.calls and callable(spy.calls[0])     # wake pokes the loop


def test_reasons_snapshot_drains_non_destructively_for_the_debug_window():
    bus = LiveBus()
    bus.wake("reset_all")
    assert bus.reasons() == ["reset_all"]
    assert bus.reasons() == []                      # drained


def test_one_bus_per_bridge():
    class B:
        pass

    first, second = B(), B()
    assert live_bus(first) is live_bus(first)
    assert live_bus(first) is not live_bus(second)
