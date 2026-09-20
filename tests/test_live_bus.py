# ideal-size: ~130 lines reason=S4 RED budget — one assertion per spec'd LiveBus behavior (tdd-interfaces rev-3, 6 tests)
"""LiveBus (S4) — the ONE wake event queue mutations ring.

Spec: `app/services/live/bus.py` — `attach(loop)`, `wake(reason)`,
`wait(timeout_s)`, `throttle(key, ms)`, `reasons()`; `live_bus(bridge)`
gives one bus per bridge. Reasons parked before a waiter arms are never
lost; `wait` drains them all at once and then reports nothing.
"""

import asyncio

from app.services.live.bus import LiveBus, live_bus  # noqa: F401  (import path is the assertion)
from app.services.live import LiveBus as LiveBusReexport  # facade re-exports


def _run(main_coro_factory):
    """Run one async main on a fresh loop (tests own their loops)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(main_coro_factory(loop))
    finally:
        loop.close()


def test_live_bus_exists_and_reexports():
    bus = LiveBus()
    assert bus is not None
    assert LiveBusReexport is LiveBus
    assert LiveBus.__module__ == "app.services.live.bus"


def test_wake_then_wait_returns_reason():
    async def main(loop):
        bus = LiveBus()
        bus.attach(loop)

        async def waiter():
            return await bus.wait(1.0)

        task = asyncio.ensure_future(waiter())
        await asyncio.sleep(0.02)  # let the waiter arm its event
        bus.wake("queue")
        return await asyncio.wait_for(task, 2.0)

    assert _run(main) == "queue"


def test_sticky_wake_no_reason_lost():
    async def main(loop):
        bus = LiveBus()
        bus.attach(loop)
        bus.wake("reset_all")
        bus.wake("scan")
        first = await bus.wait(0.5)
        second = await bus.wait(0.05)
        return first, second

    first, second = _run(main)
    assert "reset_all" in first and "scan" in first  # one wait drains both
    assert second == ""  # ...and nothing is reported twice


def test_throttle_one_line_per_window_one_per_change(monkeypatch):
    now = {"t": 0.0}
    bus = LiveBus()
    bus._clock = lambda: now["t"]
    assert bus.throttle("no tab", 300) is True
    assert bus.throttle("no tab", 300) is False   # inside the window
    now["t"] = 0.4
    assert bus.throttle("no tab", 300) is True    # window elapsed
    assert bus.throttle("other tab", 300) is True  # a changed key always passes


def test_wake_before_attach_survives():
    bus = LiveBus()
    bus.wake("scan")  # nobody listens yet

    async def main(loop):
        bus.attach(loop)
        return await bus.wait(0.5)

    assert _run(main) == "scan"


def test_wait_timeout_returns_empty():
    async def main(loop):
        bus = LiveBus()
        bus.attach(loop)
        return await bus.wait(0.03)

    assert _run(main) == ""
