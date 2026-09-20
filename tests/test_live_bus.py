"""S4 · `app/services/live/bus.LiveBus` — the one wake event between queue
writers (slots, scan workers, pool emits) and the live loop (S5).

RED at base: `ModuleNotFoundError: app.services.live`.
"""

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from app.services.live.bus import LiveBus, live_bus

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_wake_from_another_thread_releases_wait():
    bus = LiveBus()
    bus.attach(asyncio.get_running_loop())
    threading.Timer(0.02, lambda: bus.wake("queue")).start()
    t0 = time.monotonic()
    reason = await asyncio.wait_for(bus.wait(5), 2)
    assert reason == "queue"
    assert time.monotonic() - t0 < 1.0  # released by the wake, not by the 5 s timeout


@pytest.mark.asyncio
async def test_wait_times_out_with_an_empty_reason():
    bus = LiveBus()
    assert await bus.wait(0.05) == ""


@pytest.mark.asyncio
async def test_reasons_drain_once():
    bus = LiveBus()
    bus.wake("queue")
    bus.wake("urls")
    assert bus.reasons() == ["queue", "urls"]
    first = await bus.wait(0.05)
    assert "queue" in first and "urls" in first
    assert await bus.wait(0.01) == ""  # no sticky wake
    assert bus.reasons() == []


def test_throttle_allows_one_line_per_window_and_one_per_change():
    now = {"t": 100.0}
    bus = LiveBus(clock=lambda: now["t"])
    assert bus.throttle("no tab", 300) is True
    assert bus.throttle("no tab", 300) is False
    now["t"] += 0.1
    assert bus.throttle("no tab", 300) is False
    now["t"] += 0.25
    assert bus.throttle("no tab", 300) is True
    assert bus.throttle("all cooling", 300) is True  # another key has its own window


@pytest.mark.asyncio
async def test_wake_without_an_attached_loop_is_safe():
    bus = LiveBus()
    bus.wake("early")  # a slot fired before the loop existed
    assert bus.reasons() == ["early"]
    bus.attach(asyncio.get_running_loop())
    assert await bus.wait(0.05) == "early"  # nothing lost


def test_one_bus_per_bridge():
    a, b = SimpleNamespace(), SimpleNamespace()
    assert live_bus(a) is live_bus(a)
    assert live_bus(a) is not live_bus(b)
    assert isinstance(live_bus(a), LiveBus)
