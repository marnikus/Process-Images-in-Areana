"""LiveBus — any thread wakes, one coroutine waits (S4, I-49).

Real threads, real asyncio; the only fake is the clock handed to `throttle`.
The bus is the one wake event every queue write (`feed.commit_queue`) ends in,
so the (S5) live loop never polls.
"""

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from app.services.live.bus import LiveBus, live_bus

pytestmark = pytest.mark.unit


async def test_wake_from_another_thread_releases_wait():
    bus = LiveBus()
    loop = asyncio.get_running_loop()
    bus.attach(loop)
    threading.Timer(0.02, lambda: bus.wake("queue")).start()
    t0 = time.monotonic()
    reason = await asyncio.wait_for(bus.wait(5), timeout=2)
    assert reason == "queue"
    assert time.monotonic() - t0 < 1.0   # released by the wake, not by the 5 s timeout


async def test_wait_times_out_with_an_empty_reason():
    bus = LiveBus()
    assert await bus.wait(0.02) == ""
    assert bus.reasons() == []


async def test_reasons_drain_once():
    bus = LiveBus()
    bus.wake("reset_all")
    bus.wake("urls")
    assert bus.reasons() == ["reset_all", "urls"]
    assert await bus.wait(1) == "reset_all,urls"   # both delivered together, in order
    assert await bus.wait(0.02) == ""              # no sticky wake
    assert bus.reasons() == []


def test_throttle_allows_one_line_per_window():
    now = {"t": 100.0}
    bus = LiveBus(clock=lambda: now["t"])
    assert bus.throttle("no tab", 300) is True
    assert bus.throttle("no tab", 300) is False     # inside the window
    assert bus.throttle("other", 300) is True       # keys are independent
    now["t"] += 0.31
    assert bus.throttle("no tab", 300) is True      # window passed


async def test_wake_without_an_attached_loop_is_safe():
    bus = LiveBus()
    bus.wake("early")                                # before any loop exists: no raise, no loss
    assert bus.reasons() == ["early"]
    assert await bus.wait(1) == "early"              # `wait` attaches itself to the running loop


def test_one_bus_per_bridge():
    a, b = SimpleNamespace(), SimpleNamespace()
    assert live_bus(a) is live_bus(a)
    assert live_bus(a) is not live_bus(b)
    assert isinstance(a._live_bus, LiveBus)
