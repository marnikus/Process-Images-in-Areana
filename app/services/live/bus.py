"""LiveBus — one wake event per bridge (S4).

The (S5) loop waits on this bus; every queue mutation funnels a `wake(reason)`
through it (`live/feed.commit_queue`). Wakes made before the loop attaches are
recorded and delivered on first wait — a slot may fire before the loop exists.
No Qt, no panels (layered services ✓ core); the lock is never held across an
`await` (thread-safe wake via `loop.call_soon_threadsafe`).
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque


class LiveBus:
    """Bounded wake/reason queue bound lazily to the consumer's event loop."""

    def __init__(self):
        self._lock = threading.Lock()
        self._reasons = deque()
        self._loop = None
        self._event = None
        self._throttle = {}

    def attach(self, loop) -> None:
        """Bind to the consumer's loop (once per loop lifetime)."""
        with self._lock:
            self._loop = loop
            self._event = asyncio.Event()

    def wake(self, reason: str) -> None:
        """Record a reason and release any waiter; safe from any thread."""
        with self._lock:
            self._reasons.append(str(reason))
            loop, event = self._loop, self._event
        if loop is not None and event is not None:
            try:
                loop.call_soon_threadsafe(event.set)
            except Exception:
                pass                                    # loop is closing; the reason stays queued

    async def wait(self, timeout_s: float) -> str:
        """One reason, or "" on timeout. No sticky wakes, no busy poll."""
        with self._lock:
            if self._reasons:
                return self._reasons.popleft()
            event = self._event
            loop = self._loop or _running_loop()
            if event is None and loop is not None:
                self._loop, self._event = loop, asyncio.Event()
                event = self._event
        if event is None:
            await asyncio.sleep(timeout_s)              # detached bridge: sleep, then drain once
            return self._drain_one()
        try:
            await asyncio.wait_for(event.wait(), timeout_s)
        except asyncio.TimeoutError:
            return ""
        with self._lock:
            event.clear()
        return self._drain_one()

    def throttle(self, key: str, window_ms: int) -> bool:
        """True at most once per key per window (idle-line rate limiting)."""
        with self._lock:
            now = time.monotonic()
            last = self._throttle.get(key, 0.0)
            if (now - last) * 1000 < window_ms:
                return False
            self._throttle[key] = now
            return True

    def reasons(self) -> list:
        """Drain recorded reasons without waiting (debug window, tests)."""
        with self._lock:
            out = list(self._reasons)
            self._reasons.clear()
            return out

    def _drain_one(self) -> str:
        with self._lock:
            return self._reasons.popleft() if self._reasons else ""


def _running_loop():
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def live_bus(bridge) -> LiveBus:
    """The bridge's single bus, created on first use (init_run_state sets it)."""
    bus = getattr(bridge, "_live_bus", None)
    if bus is None:
        bus = LiveBus()
        bridge._live_bus = bus
    return bus
