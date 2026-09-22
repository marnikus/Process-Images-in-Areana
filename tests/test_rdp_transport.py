"""RDP transport against a real socket speaking the real protocol.

Covers the three behaviours that cost correctness: matching a reply while an
event is in flight, a timeout poisoning the link instead of desyncing it, and
detach leaving the browser alone so the app can reattach.
"""

import asyncio

import pytest

from app.browser.rdp.transport import RDPClosed, RDPTransport
from tests.rdp_fake_firefox import FakeFirefox

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


@pytest.fixture
async def firefox():
    server = FakeFirefox()
    await server.start()
    yield server
    await server.stop()


def _transport(server, **kw):
    return RDPTransport(host="127.0.0.1", port=server.port, **kw)


async def test_connect_consumes_the_unsolicited_root_greeting(firefox):
    transport = _transport(firefox)
    greeting = await transport.connect()
    assert greeting["from"] == "root" and greeting["applicationType"] == "browser"
    assert transport.is_connected
    await transport.close()


async def test_a_request_gets_its_own_reply(firefox):
    transport = _transport(firefox)
    await transport.connect()
    reply = await transport.request({"to": "root", "type": "listTabs"})
    assert reply["tabs"][0]["url"] == "https://arena.ai/chat"
    await transport.close()


async def test_an_event_arriving_first_does_not_become_the_reply(firefox):
    """A `consoleAPICall` between request and reply must not be read as the answer."""
    firefox.chatty = True
    transport = _transport(firefox)
    await transport.connect()
    reply = await transport.request({"to": "root", "type": "listTabs"})
    assert "tabs" in reply and "type" not in reply
    assert any(e.get("type") == "consoleAPICall" for e in transport.drain_events())
    await transport.close()


async def test_frames_split_across_reads_are_reassembled(firefox):
    firefox.split_frames = True
    transport = _transport(firefox)
    await transport.connect()
    assert "tabs" in await transport.request({"to": "root", "type": "listTabs"})
    await transport.close()


async def test_a_timeout_poisons_the_connection_instead_of_desyncing_it(firefox):
    """The abandoned reply is still coming; reusing the socket would return it later."""
    transport = _transport(firefox, timeout=0.2)
    await transport.connect()
    firefox.silent = True
    with pytest.raises(RDPClosed):
        await transport.request({"to": "root", "type": "listTabs"})
    assert not transport.is_connected and transport.last_error == "timeout"
    with pytest.raises(RDPClosed):
        await transport.request({"to": "root", "type": "listTabs"})


async def test_the_browser_closing_the_link_is_reported_as_closed(firefox):
    transport = _transport(firefox, timeout=2)
    await transport.connect()
    await firefox.stop()
    firefox.silent = True
    with pytest.raises(RDPClosed):
        await transport.request({"to": "root", "type": "listTabs"})
    assert not transport.is_connected


async def test_requesting_without_connecting_is_refused(firefox):
    with pytest.raises(RDPClosed):
        await RDPTransport(port=firefox.port).request({"to": "root", "type": "listTabs"})


async def test_detach_and_reattach_without_restarting_the_browser(firefox):
    """The core requirement: our socket goes away, the Firefox session does not."""
    transport = _transport(firefox)
    await transport.connect()
    await transport.close()
    assert not transport.is_connected
    await transport.connect()
    assert "tabs" in await transport.request({"to": "root", "type": "listTabs"})
    await transport.close()
    assert firefox.connections == 2


async def test_closing_twice_is_harmless(firefox):
    transport = _transport(firefox)
    await transport.connect()
    await transport.close()
    await transport.close()
    assert not transport.is_connected


async def test_concurrent_requests_are_serialised(firefox):
    """The protocol has no request ids, so two in flight would cross answers."""
    transport = _transport(firefox)
    await transport.connect()
    replies = await asyncio.gather(*[transport.request({"to": "root", "type": "listTabs"})
                                     for _ in range(4)])
    assert all("tabs" in r for r in replies)
    await transport.close()
