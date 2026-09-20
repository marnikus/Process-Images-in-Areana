"""S4: one wake event per bridge — threads release the loop's wait (live/bus).

No fake clock: `tests/conftest.py:fake_clock` is a PagePool event helper, not a
monotonic patch (S3 finding), and these tests need none — a thread wake proves
the release, and the throttle window uses a real short sleep (RULE 16).
"""

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from app.services.live.bus import LiveBus, live_bus


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wake_from_another_thread_releases_wait():
    bus = LiveBus()
    bus.attach(asyncio.get_running_loop())
    thread = threading.Thread(target=lambda: (time.sleep(0.05), bus.wake("queue")),
                              daemon=True)
    thread.start()
    t0 = time.monotonic()
    reason = await bus.wait(5)
    dt = time.monotonic() - t0
    thread.join(timeout=5)
    assert reason == "queue"
    assert 0.03 < dt < 1.0  # blocked first, then released — not the 5 s timeout


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wait_times_out_with_an_empty_reason():
    assert await LiveBus().wait(0.05) == ""


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reasons_drain_once():
    bus = LiveBus()
    bus.wake("a")
    bus.wake("b")
    assert bus.reasons() == ["a", "b"]  # peek, no drain
    assert await bus.wait(5) == "a+b"  # one wait takes both, joined
    assert bus.reasons() == []
    assert await bus.wait(0.02) == ""  # no sticky wake


@pytest.mark.unit
def test_throttle_allows_one_line_per_window_and_one_per_change():
    bus = LiveBus()
    assert bus.throttle("no tab", 100) is True
    assert bus.throttle("no tab", 100) is False
    assert bus.throttle("other key", 100) is True  # windows are per key
    time.sleep(0.12)  # real window expiry (fake_clock cannot advance monotonic)
    assert bus.throttle("no tab", 100) is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wake_without_an_attached_loop_is_safe():
    bus = LiveBus()
    bus.wake("early")  # a slot may fire before the loop starts — never raises
    assert bus.reasons() == ["early"]  # and the reason is not lost
    bus.attach(asyncio.get_running_loop())
    assert await bus.wait(0.5) == "early"


@pytest.mark.unit
def test_wake_with_a_closed_loop_keeps_the_reason_and_never_raises():
    bus = LiveBus()
    loop = asyncio.new_event_loop()
    loop.close()
    bus.attach(loop)
    bus.wake("x")  # call_soon_threadsafe raises on a closed loop — swallowed
    assert bus.reasons() == ["x"]


@pytest.mark.unit
def test_one_bus_per_bridge():
    first, second = SimpleNamespace(), SimpleNamespace()
    assert live_bus(first) is live_bus(first)
    assert isinstance(live_bus(first), LiveBus)
    assert live_bus(second) is not live_bus(first)
