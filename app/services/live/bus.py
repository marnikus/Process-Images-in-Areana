"""LiveBus — the one wake event of the live run (S4, I-49).

Any thread wakes (Qt slots, scan workers, pool emits); exactly one coroutine
waits (the S5 live loop, on the bg asyncio loop). A wake is a *reason*
("reset_all", "urls", "pool", "interval"), delivered once — the loop
drains them and never polls. `throttle` keeps repeated status lines to
one per window per key. No Qt, no panels; the lock is never held across
an `await` (there is no `await` under it).
"""
# ideal-size: ~85 lines reason=one primitive (wake / wait / throttle) shared by the run loop
# and the reconciler; merging it into feed.py would couple a queue rule to a threading tool.

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Callable, Dict, List, Optional


class LiveBus:
    """Thread-safe wake-ups for a single waiting coroutine."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._lock = threading.Lock()
        self._pending: List[str] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._event: Optional[asyncio.Event] = None
        self._clock = clock
        self._last_line: Dict[str, float] = {}

    def attach(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind to the loop that waits (`wait` does this itself when needed)."""
        self._loop = loop
        self._event = asyncio.Event()

    def wake(self, reason: str) -> None:
        """Record the reason and release the waiter — from any thread, safe before `attach`."""
        with self._lock:
            self._pending.append(str(reason or "wake"))
            loop, event = self._loop, self._event
        if loop is None or event is None:
            return
        try:
            loop.call_soon_threadsafe(event.set)
        except RuntimeError:  # the loop is closed: the reason stays queued for the next waiter
            pass

    async def wait(self, timeout_s: float) -> str:
        """Block until a wake or `timeout_s`; returns the drained reasons joined, "" on timeout."""
        if self._event is None or self._loop is not asyncio.get_running_loop():
            self.attach(asyncio.get_running_loop())
        if not self.reasons():
            try:
                await asyncio.wait_for(self._event.wait(), timeout_s)
            except asyncio.TimeoutError:
                pass
        self._event.clear()
        return ",".join(self._drain())

    def _drain(self) -> List[str]:
        with self._lock:
            reasons, self._pending = self._pending, []
        return reasons

    def reasons(self) -> List[str]:
        """Pending (undelivered) reasons, in arrival order."""
        with self._lock:
            return list(self._pending)

    def throttle(self, key: str, ms: int) -> bool:
        """True once per `ms` window per key — one status line per window, not one per poll."""
        now = self._clock()
        with self._lock:
            last = self._last_line.get(key)
            if last is not None and (now - last) * 1000.0 < ms:
                return False
            self._last_line[key] = now
        return True


def live_bus(bridge: Any) -> LiveBus:
    """The bridge's one bus (created by `bridge_context.init_run_state`; lazily for bare hosts)."""
    bus = getattr(bridge, "_live_bus", None)
    if bus is None:
        bus = bridge._live_bus = LiveBus()
    return bus
