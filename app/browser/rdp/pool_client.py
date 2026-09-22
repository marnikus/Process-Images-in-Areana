"""`FirefoxPoolClient` — a Firefox tab that answers the pool's client calls.

The pool, controller and job runner speak one client vocabulary that grew up
around CDP (`connect`, `disconnect`, `evaluate`). Firefox reaches its tabs by a
different route entirely, so this adapter presents that vocabulary over RDP and
keeps every protocol difference on this side of the seam.

Two Firefox facts it has to absorb:

* **Actor ids die with the connection.** So the client remembers the tab's
  *URL*, not its actor, and re-resolves the tab after every attach
  (`discovery.find_tab_by_url`). That is what makes reconnect-without-restart
  work rather than silently addressing a dead actor.
* **There is no WebSocket.** `connect()` takes the `rdp://host:port/actor`
  locator the scan produced and dials a plain socket.

Scope is the shipped click-only surface: evaluate, click, probe. Anything the
CDP client offers beyond that is deliberately absent rather than faked.

Layer: browser leaf — rdp only; no Qt, no services, no UI.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .discovery import find_tab_by_url, parse_locator
from .session import ClickResult, FirefoxTab, RDPSession
from .transport import RDPClosed, RDPTransport

log = logging.getLogger("arena")

__all__ = ["FirefoxPoolClient"]


class FirefoxPoolClient:
    """One pooled Firefox tab, addressed over RDP instead of a WebSocket."""

    def __init__(self, host: str = "127.0.0.1", port: int = 6000, timeout: float = 15.0):
        self._host, self._port, self._timeout = host, int(port), float(timeout)
        self._session: Optional[RDPSession] = None
        self._tab: Optional[FirefoxTab] = None
        self._url = ""
        self.last_error = ""

    @property
    def is_connected(self) -> bool:
        return self._session is not None and self._session.is_attached

    @property
    def tab_url(self) -> str:
        """The URL this client re-resolves its tab by across reconnects."""
        return self._url

    async def connect(self, locator: str) -> bool:
        """Attach and resolve the tab named by an `rdp://host:port/actor` key."""
        parsed = parse_locator(locator)
        if parsed is None:
            self.last_error = f"not a Firefox RDP locator: {locator[:60]}"
            return False
        host, port, actor = parsed
        self._host, self._port = host or self._host, port or self._port
        return await self._attach(actor)

    async def reconnect(self) -> bool:
        """Reattach after a drop, re-resolving the tab by URL (actors renumber)."""
        await self.disconnect()
        return await self._attach("")

    async def disconnect(self) -> None:
        """Detach our socket; the Firefox tab and window keep running."""
        session, self._session = self._session, None
        if session is not None:
            await session.detach()

    async def evaluate(self, expression: str) -> Any:
        """Run JS in the tab and return its value."""
        session, tab = self._session_tab()
        return await session.evaluate(tab, expression)

    async def click(self, selector: str) -> ClickResult:
        """Click the first match — a miss is a reason, not an exception (RULE 4)."""
        session, tab = self._session_tab()
        return await session.click(tab, selector)

    async def probe(self, selector: str) -> ClickResult:
        """Report whether the element is present and laid out, without clicking."""
        session, tab = self._session_tab()
        return await session.probe(tab, selector)

    async def automation_signals(self) -> dict:
        """What the site sees — `{'webdriver': False, 'hasCdc': False}` when clean."""
        session, tab = self._session_tab()
        return await session.automation_signals(tab)

    async def _attach(self, actor: str) -> bool:
        """Open a session and bind a tab, by actor on first use, else by URL."""
        session = RDPSession(RDPTransport(self._host, self._port, self._timeout))
        try:
            await session.attach()
            tab = await self._resolve(session, actor)
        except (RDPClosed, OSError) as exc:
            self.last_error = str(exc)
            await session.detach()
            return False
        if tab is None:
            self.last_error = f"tab not found for {self._url or actor}"
            await session.detach()
            return False
        self._session, self._tab, self._url = session, tab, tab.url or self._url
        self.last_error = ""
        return True

    async def _resolve(self, session: RDPSession, actor: str) -> Optional[FirefoxTab]:
        """Find our tab: by actor while the connection that issued it lives, else by URL."""
        if self._url:
            return await find_tab_by_url(session, self._url)
        for tab in await session.list_tabs():
            if tab.actor == actor:
                return tab
        return None

    def _session_tab(self) -> tuple:
        """The live (session, tab) pair, or a clear failure — never a silent no-op."""
        if self._session is None or self._tab is None:
            raise RDPClosed("Firefox client is not connected")
        return self._session, self._tab
