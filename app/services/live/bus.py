"""LiveBus — the one wake event between queue writers and the live loop (S4).

Writers (`feed.commit_queue`, URL commits, pool emits) call `wake(reason)`
from any thread; the loop (S5 `run_live`) awaits `wait(timeout_s)` on its
own asyncio loop and receives the drained reasons. `throttle(key, ms)` is
the loop's "one line per window" gate for repeated wait states.

No Qt, no panels. `wake` before `attach` is safe: the reason is kept and
the first `wait` after `attach` returns immediately.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Callable, List, Optional


class LiveBus:
    """Thread-safe wake + reasons + per-key throttle for one bridge."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._reasons: List[str] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._event: Optional[asyncio.Event] = None
        self._last: dict = {}

    def attach(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind to the loop that will `wait` (called by the loop itself)."""
        self._loop = loop
        self._event = asyncio.Event()
        if self._reasons:
            self._event.set()

    def wake(self, reason: str) -> None:
        """Record a reason and release the waiter — from any thread, never raises."""
        with self._lock:
            self._reasons.append(str(reason))
        loop, event = self._loop, self._event
        if loop is None or event is None:
            return
        try:
            loop.call_soon_threadsafe(event.set)
        except RuntimeError:
            pass  # the loop is closed; the reason stays for the next attach

    async def wait(self, timeout_s: float) -> str:
        """Block until a wake or `timeout_s`; returns the drained reasons joined, '' on timeout."""
        if self._event is None or self._loop is not asyncio.get_running_loop():
            self.attach(asyncio.get_running_loop())
        try:
            await asyncio.wait_for(self._event.wait(), timeout_s)
        except asyncio.TimeoutError:
            pass
        self._event.clear()
        with self._lock:
            reasons, self._reasons = self._reasons, []
        return "+".join(reasons)

    def reasons(self) -> List[str]:
        """Pending (not yet drained) reasons — for tests and the debug window."""
        with self._lock:
            return list(self._reasons)

    def throttle(self, key: str, window_ms: int) -> bool:
        """True once per `window_ms` per key (the first call always passes)."""
        now = self._clock()
        with self._lock:
            last = self._last.get(key)
            if last is not None and (now - last) * 1000.0 < window_ms:
                return False
            self._last[key] = now
            return True


def live_bus(bridge) -> LiveBus:
    """The one bus of this bridge (created on first use; `init_run_state` pre-creates it)."""
    bus = getattr(bridge, "_live_bus", None)
    if bus is None:
        bus = LiveBus()
        bridge._live_bus = bus
    return bus
