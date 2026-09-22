"""One long-lived RDP connection per Firefox, reused across scans.

Firefox asks the user to authorise **every incoming debugger connection**. The
scan used to attach and detach on each pass, so a reconciler running every few
seconds produced an "Incoming Connection" dialog every few seconds.

The cure is to stop reconnecting: hold one session per `host:port` and reuse it
for every later scan. A connection is opened only when there is none, or when
the previous one died — so the prompt appears **once per browser run**, not
once per pass. (Setting `devtools.debugger.prompt-connection=false` removes it
entirely; this module means the app behaves well even when it is still on.)

Reusing a live connection is also correct protocol-wise: actor ids stay valid
for the lifetime of the connection that issued them. It is precisely *new*
connections that renumber, which is why the cache hands back the same session
rather than re-enumerating.

Layer: browser leaf — rdp only; no Qt, no services, no UI.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, Optional, Tuple

from .session import RDPSession
from .transport import RDPClosed, RDPTransport

log = logging.getLogger("arena")

__all__ = ["SessionCache", "shared_cache"]


class SessionCache:
    """Keeps one attached `RDPSession` per endpoint, reconnecting only when dead."""

    def __init__(self) -> None:
        self._sessions: Dict[Tuple[str, int], RDPSession] = {}
        self._lock = asyncio.Lock()

    def peek(self, host: str, port: int) -> Optional[RDPSession]:
        """The cached session for this endpoint, attached or not (None if absent)."""
        return self._sessions.get((host, int(port)))

    async def acquire(self, host: str, port: int, timeout: float = 5.0) -> RDPSession:
        """The live session for this endpoint, attaching only when necessary.

        Serialised, so two concurrent scans of one browser cannot each open a
        connection — which would show the user two dialogs.
        """
        async with self._lock:
            key = (host, int(port))
            session = self._sessions.get(key)
            if session is not None and session.is_attached:
                return session
            return await self._attach_fresh(key, timeout)

    async def _attach_fresh(self, key: Tuple[str, int], timeout: float) -> RDPSession:
        """Replace a missing/dead session with a newly attached one."""
        host, port = key
        await self._drop_locked(key)
        session = RDPSession(RDPTransport(host=host, port=port, timeout=timeout))
        await session.attach()
        self._sessions[key] = session
        log.debug("rdp session attached %s:%s", host, port)
        return session

    async def release(self, host: str, port: int) -> None:
        """Detach and forget one endpoint (its next scan will reconnect)."""
        async with self._lock:
            await self._drop_locked((host, int(port)))

    async def close_all(self) -> None:
        """Detach every cached session — for app shutdown."""
        async with self._lock:
            for key in list(self._sessions):
                await self._drop_locked(key)

    async def _drop_locked(self, key: Tuple[str, int]) -> None:
        """Detach and remove one entry; a failing detach still forgets it."""
        session = self._sessions.pop(key, None)
        if session is None:
            return
        try:
            await session.detach()
        except (RDPClosed, OSError) as exc:
            log.debug("rdp detach %s failed: %s", key, exc)


# The app-wide cache. One connection per Firefox, for the life of the process.
shared_cache = SessionCache()
