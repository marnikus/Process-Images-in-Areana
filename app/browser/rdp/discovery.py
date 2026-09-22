"""Firefox tab discovery — RDP tabs in the shape the rest of the app expects.

The pool, the URL rows and the worker table are all written against CDP's
`TabInfo` (`id`, `title`, `url`, `ws_url`, `type`). Firefox has no WebSocket
and no `/json/list`, so this module is the adapter: it attaches over RDP,
lists tabs, and returns the same record with an `rdp://` locator in place of
`ws_url`.

`rdp://host:port/<actor>` is deliberately **not** a URL anyone can dial. It is
an opaque pool key that says "this tab is reached by RDP, not WebSocket", and
`parse_locator` turns it back into its parts. The actor inside it is valid only
for the connection that produced it (Firefox renumbers per connection), so it
identifies a tab within a session and is re-resolved on reattach by *url*.

Layer: browser leaf — rdp + asyncio only; no Qt, no services, no UI.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from .session import FirefoxTab, RDPSession
from .transport import RDPTransport

__all__ = ["RDP_SCHEME", "build_locator", "parse_locator", "is_rdp_locator",
           "list_firefox_tabs", "find_tab_by_url"]

RDP_SCHEME = "rdp://"


def build_locator(host: str, port: Any, actor: str) -> str:
    """`rdp://127.0.0.1:9224/server1.conn1.tabDescriptor1` — an opaque pool key."""
    return f"{RDP_SCHEME}{host}:{port}/{actor}"


def is_rdp_locator(value: Any) -> bool:
    """True for a Firefox RDP key — the one test that routes protocol per tab."""
    return isinstance(value, str) and value.startswith(RDP_SCHEME)


def parse_locator(locator: Any) -> Optional[Tuple[str, int, str]]:
    """`rdp://host:port/actor` → (host, port, actor); None when it is not one."""
    if not is_rdp_locator(locator):
        return None
    body = str(locator)[len(RDP_SCHEME):]
    authority, _, actor = body.partition("/")
    host, _, port_text = authority.rpartition(":")
    try:
        return (host or "127.0.0.1"), int(port_text), actor
    except ValueError:
        return None


def _as_tab_info(tab: FirefoxTab, host: str, port: Any) -> Any:
    """One RDP tab as the app-wide `TabInfo` record."""
    from ..cdp.tabs import TabInfo
    return TabInfo(id=build_locator(host, port, tab.actor), title=tab.title,
                   url=tab.url, ws_url=build_locator(host, port, tab.actor), type="page")


async def list_firefox_tabs(host: str = "127.0.0.1", port: int = 6000,
                            timeout: float = 5.0) -> List[Any]:
    """Attach, list the tabs, detach — the browser is left running.

    Raises on a broken connection; an empty list means Firefox answered and
    genuinely has no tabs (RULE 4).
    """
    session = RDPSession(RDPTransport(host=host, port=port, timeout=timeout))
    await session.attach()
    try:
        return [_as_tab_info(tab, host, port) for tab in await session.list_tabs()]
    finally:
        await session.detach()


async def find_tab_by_url(session: RDPSession, url: str) -> Optional[FirefoxTab]:
    """Re-resolve a tab by URL after a reconnect, since actor ids are renumbered."""
    if not url:
        return None
    for tab in await session.list_tabs():
        if tab.url == url:
            return tab
    return None
