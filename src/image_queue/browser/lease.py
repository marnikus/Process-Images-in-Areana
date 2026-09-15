"""Extracted CdpLease ownership handoff from retained backend/cdp_client.py.

Only high-priority user operations exist now; retain cancellation-safe FIFO handoff.
"""

import asyncio
from collections import deque


class CdpLease:
    def __init__(self) -> None:
        self.busy = False
        self._waiters: deque[asyncio.Future[bool]] = deque()

    async def __aenter__(self) -> "CdpLease":
        if not self.busy and not self._waiters:
            self.busy = True
            return self
        future = asyncio.get_running_loop().create_future()
        self._waiters.append(future)
        try:
            await future
        except asyncio.CancelledError:
            if future.done() and not future.cancelled():
                self.release()
            raise
        return self

    async def __aexit__(self, *_: object) -> None:
        self.release()

    def release(self) -> None:
        while self._waiters:
            future = self._waiters.popleft()
            if not future.done():
                future.set_result(True)
                return
        self.busy = False
