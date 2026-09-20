"""One wake event per bridge (S4): slots/workers release the loop's wait.

One waiter (S5's loop), many wakers (panel slots on the loop thread, scan
workers on threads). Reasons buffer under a mutex; the event is only the
doorbell, so a wake before `attach` is kept, never lost.
"""

from __future__ import annotations

import asyncio
import threading
import time


class LiveBus:
    """Wake reasons + throttle windows; `wake` is thread-safe, never raises."""

    def __init__(self) -> None:
        self._loop = None
        self._event = asyncio.Event()
        self._reasons: list = []
        self._throttle_at: dict = {}
        self._mutex = threading.Lock()

    def attach(self, loop) -> None:
        """Bind the loop that owns waiting (thread wakes deliver here)."""
        self._loop = loop

    def wake(self, reason: str) -> None:
        """Buffer a reason and release the waiter (thread-safe, never raises)."""
        try:
            with self._mutex:
                self._reasons.append(reason)
            loop = self._loop
            if loop is not None:
                loop.call_soon_threadsafe(self._event.set)
        except Exception:
            pass

    async def wait(self, timeout_s: float) -> str:
        """Next wake reason(s), joined with `+`; `""` on timeout (drains once)."""
        with self._mutex:
            if self._reasons:
                pending = "+".join(self._reasons)
                self._reasons.clear()
                self._event.clear()
                return pending
        try:
            await asyncio.wait_for(self._event.wait(), timeout_s)
        except TimeoutError:
            return ""
        with self._mutex:
            pending = "+".join(self._reasons)
            self._reasons.clear()
            self._event.clear()
            return pending

    def throttle(self, key: str, ms: int) -> bool:
        """True once per window per key (monotonic; thread-safe)."""
        now = time.monotonic()
        with self._mutex:
            last = self._throttle_at.get(key, 0.0)
            if now - last < ms / 1000.0:
                return False
            self._throttle_at[key] = now
            return True

    def reasons(self) -> list:
        """Pending reasons (peek; `wait` drains)."""
        with self._mutex:
            return list(self._reasons)


def live_bus(bridge) -> LiveBus:
    """The bridge's bus, created on first use (one per bridge)."""
    bus = getattr(bridge, "_live_bus", None)
    if bus is None:
        bus = LiveBus()
        bridge._live_bus = bus
    return bus
