"""Firefox tab discovery and the `rdp://` locator that routes protocol (I-63)."""

import asyncio

import pytest

from app.browser.rdp.discovery import (build_locator, find_tab_by_url, is_rdp_locator,
                                       list_firefox_tabs, parse_locator)
from app.browser.rdp.session import RDPSession
from app.browser.rdp.session_cache import shared_cache
from app.browser.rdp.transport import RDPClosed, RDPTransport
from tests.rdp_fake_firefox import FakeFirefox

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def clean_cache():
    """The shared session cache is process-wide; never leak one test into the next."""
    await shared_cache.close_all()
    yield
    await shared_cache.close_all()


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


async def test_repeated_scans_reuse_one_connection(firefox):
    """The popup fix (I-64): Firefox prompts per *connection*, so scans share one.

    Ten passes of the reconciler used to mean ten "Incoming Connection" dialogs.
    """
    for _ in range(10):
        await list_firefox_tabs("127.0.0.1", firefox.port, timeout=3)
    assert firefox.connections == 1


async def test_a_dropped_connection_is_re_established_once(firefox):
    """The browser really going away is the one case that may reconnect."""
    assert await list_firefox_tabs("127.0.0.1", firefox.port, timeout=3)
    session = shared_cache.peek("127.0.0.1", firefox.port)
    await session.transport.close()          # the link dies under us
    assert await list_firefox_tabs("127.0.0.1", firefox.port, timeout=3)
    assert firefox.connections == 2


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


async def test_a_stale_cached_session_is_retried_transparently(firefox):
    """A connection that dies between scans must not surface as a scan failure."""
    await list_firefox_tabs("127.0.0.1", firefox.port, timeout=3)
    session = shared_cache.peek("127.0.0.1", firefox.port)

    async def dead_list():
        raise RDPClosed("connection went away")

    session.list_tabs = dead_list          # the cached link is stale
    tabs = await list_firefox_tabs("127.0.0.1", firefox.port, timeout=3)
    assert [t.url for t in tabs] == ["https://arena.ai/chat"]
    assert firefox.connections == 2        # exactly one reconnect, not a storm


async def test_a_browser_that_really_died_still_raises(firefox):
    """RULE 4: after the retry also fails, the caller must hear about it."""
    await list_firefox_tabs("127.0.0.1", firefox.port, timeout=3)
    await shared_cache.close_all()
    await firefox.stop()
    with pytest.raises(OSError):
        await list_firefox_tabs("127.0.0.1", firefox.port, timeout=2)
