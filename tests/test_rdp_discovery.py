"""Firefox tab discovery and the `rdp://` locator that routes protocol (I-63)."""

import asyncio

import pytest

from app.browser.rdp.discovery import (build_locator, find_tab_by_url, is_rdp_locator,
                                       list_firefox_tabs, parse_locator)
from app.browser.rdp.session import RDPSession
from app.browser.rdp.transport import RDPTransport
from tests.rdp_fake_firefox import FakeFirefox

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


@pytest.fixture
async def firefox():
    server = FakeFirefox()
    await server.start()
    yield server
    await server.stop()


async def test_a_locator_round_trips():
    locator = build_locator("127.0.0.1", 9224, "server1.conn1.tabDescriptor1")
    assert locator == "rdp://127.0.0.1:9224/server1.conn1.tabDescriptor1"
    assert parse_locator(locator) == ("127.0.0.1", 9224, "server1.conn1.tabDescriptor1")


async def test_a_websocket_url_is_not_an_rdp_locator():
    """The one predicate that keeps Firefox tabs away from the CDP client."""
    assert not is_rdp_locator("ws://127.0.0.1:9223/devtools/page/AB12")
    assert not is_rdp_locator(None) and not is_rdp_locator("")
    assert is_rdp_locator("rdp://127.0.0.1:9224/actor1")


async def test_a_malformed_locator_parses_to_none_rather_than_guessing():
    assert parse_locator("rdp://127.0.0.1:notaport/actor") is None
    assert parse_locator("ws://127.0.0.1:9223/x") is None


async def test_firefox_tabs_arrive_in_the_app_wide_tab_shape(firefox):
    tabs = await list_firefox_tabs("127.0.0.1", firefox.port, timeout=3)
    assert len(tabs) == 1
    tab = tabs[0]
    assert tab.url == "https://arena.ai/chat" and tab.title == "Arena"
    assert is_rdp_locator(tab.ws_url) and tab.id == tab.ws_url and tab.type == "page"


async def test_discovery_detaches_and_leaves_the_browser_running(firefox):
    """Each listing opens and closes its own connection; the server stays up."""
    await list_firefox_tabs("127.0.0.1", firefox.port, timeout=3)
    await list_firefox_tabs("127.0.0.1", firefox.port, timeout=3)
    assert firefox.connections == 2
    for _ in range(100):  # the server notices EOF asynchronously
        if firefox.disconnections == 2:
            break
        await asyncio.sleep(0.01)
    assert firefox.disconnections == 2


async def test_a_browser_with_no_tabs_lists_empty(firefox):
    firefox.tabs = []
    assert await list_firefox_tabs("127.0.0.1", firefox.port, timeout=3) == []


async def test_a_closed_port_raises_rather_than_reporting_no_tabs():
    """RULE 4: unreachable is broken, not empty."""
    with pytest.raises(OSError):
        await list_firefox_tabs("127.0.0.1", 1, timeout=2)


async def test_a_tab_is_re_resolved_by_url_after_a_reconnect(firefox):
    """Actor ids renumber, so URL is the stable handle across connections."""
    session = RDPSession(RDPTransport("127.0.0.1", firefox.port, 3))
    await session.attach()
    found = await find_tab_by_url(session, "https://arena.ai/chat")
    assert found is not None and found.actor == "server1.conn1.tabDescriptor1"
    assert await find_tab_by_url(session, "https://nowhere.test") is None
    assert await find_tab_by_url(session, "") is None
    await session.detach()
