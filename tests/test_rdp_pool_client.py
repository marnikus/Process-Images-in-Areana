"""`FirefoxPoolClient`: the pool's client vocabulary, spoken over RDP (I-63)."""

import json

import pytest

from app.browser.rdp.pool_client import FirefoxPoolClient
from app.browser.rdp.transport import RDPClosed
from tests.rdp_fake_firefox import FakeFirefox

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


@pytest.fixture
async def firefox():
    server = FakeFirefox()
    await server.start()
    yield server
    await server.stop()


def _locator(server, actor="server1.conn1.tabDescriptor1"):
    return f"rdp://127.0.0.1:{server.port}/{actor}"


async def test_it_connects_by_locator_and_binds_the_tab(firefox):
    client = FirefoxPoolClient()
    assert await client.connect(_locator(firefox))
    assert client.is_connected and client.tab_url == "https://arena.ai/chat"
    await client.disconnect()


async def test_a_websocket_url_is_refused_with_a_clear_reason(firefox):
    """A Chrome locator must never be silently accepted by the Firefox client."""
    client = FirefoxPoolClient()
    assert not await client.connect("ws://127.0.0.1:9223/devtools/page/AB")
    assert "not a Firefox RDP locator" in client.last_error


async def test_an_unreachable_port_fails_cleanly(firefox):
    client = FirefoxPoolClient(timeout=2)
    assert not await client.connect("rdp://127.0.0.1:1/actor1")
    assert client.last_error and not client.is_connected


async def test_a_missing_tab_is_reported_not_faked(firefox):
    client = FirefoxPoolClient()
    assert not await client.connect(_locator(firefox, "no-such-actor"))
    assert "tab not found" in client.last_error


async def test_it_clicks_through_the_console(firefox):
    firefox.eval_answer = json.dumps({"ok": True, "reason": "", "tag": "button"})
    client = FirefoxPoolClient()
    await client.connect(_locator(firefox))
    result = await client.click("#send")
    assert result.ok and "#send" in firefox.evaluated[-1]
    await client.disconnect()


async def test_a_missing_element_is_a_reason_not_an_exception(firefox):
    firefox.eval_answer = json.dumps({"ok": False, "reason": "not found"})
    client = FirefoxPoolClient()
    await client.connect(_locator(firefox))
    result = await client.click("#gone")
    assert not result.ok and result.reason == "not found"
    await client.disconnect()


async def test_probe_and_evaluate_reach_the_page(firefox):
    firefox.eval_answer = json.dumps({"ok": True, "reason": "", "visible": True})
    client = FirefoxPoolClient()
    await client.connect(_locator(firefox))
    assert (await client.probe("#a")).ok
    assert json.loads(await client.evaluate("1+1"))["ok"] is True
    await client.disconnect()


async def test_it_reports_the_sites_view_of_automation(firefox):
    firefox.eval_answer = json.dumps({"ok": True, "webdriver": False, "hasCdc": False})
    client = FirefoxPoolClient()
    await client.connect(_locator(firefox))
    assert await client.automation_signals() == {"webdriver": False, "hasCdc": False}
    await client.disconnect()


async def test_reconnect_rebinds_the_tab_by_url_after_actors_renumber(firefox):
    """The core requirement: reattach without restarting the browser."""
    client = FirefoxPoolClient()
    await client.connect(_locator(firefox))
    firefox.tabs = [{"actor": "server1.conn2.tabDescriptor9", "title": "Arena",
                     "url": "https://arena.ai/chat", "selected": True}]
    firefox.console_actor = "server1.conn2.consoleActor7"
    assert await client.reconnect()
    firefox.eval_answer = json.dumps({"ok": True, "reason": ""})
    assert (await client.click("#send")).ok
    assert firefox.connections == 2
    await client.disconnect()


async def test_a_reconnect_after_the_tab_closed_fails_honestly(firefox):
    client = FirefoxPoolClient()
    await client.connect(_locator(firefox))
    firefox.tabs = []
    assert not await client.reconnect()
    assert "tab not found" in client.last_error


async def test_using_a_disconnected_client_raises_rather_than_no_op(firefox):
    client = FirefoxPoolClient()
    await client.connect(_locator(firefox))
    await client.disconnect()
    assert not client.is_connected
    with pytest.raises(RDPClosed):
        await client.click("#send")


async def test_disconnect_is_idempotent(firefox):
    client = FirefoxPoolClient()
    await client.connect(_locator(firefox))
    await client.disconnect()
    await client.disconnect()
    assert not client.is_connected
