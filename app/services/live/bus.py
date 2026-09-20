# ideal-size: ~90 lines reason=S4 budget — the single wake event for the live queue; one class + one accessor, nothing else belongs here (RULE 18.2)
"""LiveBus (S4) — the ONE wake event queue mutations ring (I-49).

Every queue write ends in `commit_queue`, which rings `wake(reason)`
here; the S5 run loop sleeps on `wait` and re-plans on the next tick.
Reasons parked before any waiter arms are never lost, one `wait`
drains them all, and `throttle` keeps chatty reasons to one line per
window (one per changed key). Thread-safe by construction: workers may
`wake` from any thread (`call_soon_threadsafe`), and there is exactly
one bus per bridge (`live_bus`).
"""

from __future__ import annotations

import asyncio
import threading
import time


class LiveBus:
    """One wake event per bridge: park reasons, ring the waiter, drain on wake."""

    def __init__(self):
        self._lock = threading.Lock()
        self._reasons: list = []
        self._loop = None
        self._event = None
        self._throttle_ts: dict = {}
        self._clock = time.monotonic

    def attach(self, loop) -> None:
        """Bind the loop whose run-sleep waits here (S5); re-attach is safe."""
        with self._lock:
            self._loop = loop

    def wake(self, reason: str) -> None:
        """Park `reason` and ring the waiter; safe from any thread."""
        with self._lock:
            self._reasons.append(reason)
            event, loop = self._event, self._loop
        if event is None or loop is None:
            return  # parked — the next wait() drains it
        try:
            loop.call_soon_threadsafe(event.set)
        except RuntimeError:
            pass  # loop already closed — reason stays parked

    async def wait(self, timeout_s: float) -> str:
        """Drain pending reasons now; else sleep until woken or timed out."""
        with self._lock:  # drain-and-arm under ONE lock: no wake slips between
            if self._reasons:
                got, self._reasons = "+".join(self._reasons), []
                return got
            self._event = asyncio.Event()
            event = self._event
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            return ""
        finally:
            with self._lock:
                self._event = None
        with self._lock:
            got, self._reasons = "+".join(self._reasons), []
        return got

    def throttle(self, key: str, window_ms: int) -> bool:
        """One True per window per key; a changed key always passes."""
        now = self._clock()
        with self._lock:
            last = self._throttle_ts.get(key)
            if last is not None and now - last < window_ms / 1000.0:
                return False
            self._throttle_ts[key] = now
            return True

    def reasons(self) -> list:
        """Pending reasons snapshot (worker idle-row, S9)."""
        with self._lock:
            return list(self._reasons)


def live_bus(bridge) -> LiveBus:
    """The bridge's one bus; created on first use for bare hosts."""
    bus = getattr(bridge, "_live_bus", None)
    if bus is None:
        bus = LiveBus()
        try:
            bridge._live_bus = bus
        except Exception:
            pass  # frozen hosts: return a throwaway bus
    return bus
