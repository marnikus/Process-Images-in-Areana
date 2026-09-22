"""RDP session: actor resolution, the two-step evaluate, and click outcomes."""

import json

import pytest

from app.browser.rdp.session import FirefoxTab, RDPSession
from app.browser.rdp.transport import RDPClosed, RDPTransport
from tests.rdp_fake_firefox import FakeFirefox

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


@pytest.fixture
async def firefox():
    server = FakeFirefox()
    await server.start()
    yield server
    await server.stop()


@pytest.fixture
async def session(firefox):
    s = RDPSession(RDPTransport(host="127.0.0.1", port=firefox.port, timeout=3))
    await s.attach()
    yield s
    await s.detach()


async def test_tabs_are_listed_from_the_root_actor(session):
    tabs = await session.list_tabs()
    assert [t.url for t in tabs] == ["https://arena.ai/chat"]
    assert tabs[0].selected and tabs[0].title == "Arena"


async def test_tabs_without_an_actor_are_skipped(firefox):
    firefox.tabs = [{"title": "half-open", "url": "about:blank"},
                    {"actor": "a1", "title": "real", "url": "https://x.test"}]
    s = RDPSession(RDPTransport(port=firefox.port, timeout=3))
    await s.attach()
    assert [t.actor for t in await s.list_tabs()] == ["a1"]
    await s.detach()


async def test_no_tabs_is_empty_not_an_error(firefox):
    """RULE 4: a browser with nothing open is empty; a broken link raises."""
    firefox.tabs = []
    s = RDPSession(RDPTransport(port=firefox.port, timeout=3))
    await s.attach()
    assert await s.list_tabs() == []
    await s.detach()


async def test_the_console_actor_is_resolved_then_reused_within_a_connection(session, firefox):
    tab = (await session.list_tabs())[0]
    assert await session.console_actor(tab) == firefox.console_actor
    assert await session.console_actor(tab) == firefox.console_actor


async def test_a_target_without_a_console_actor_is_broken(firefox):
    firefox.console_actor = ""
    s = RDPSession(RDPTransport(port=firefox.port, timeout=3))
    await s.attach()
    with pytest.raises(RDPClosed):
        await s.console_actor((await s.list_tabs())[0])
    await s.detach()


async def test_evaluate_returns_the_event_result_not_the_ack(session, firefox):
    """The ack only carries `resultID`; reading it as the value is the classic bug."""
    firefox.eval_answer = json.dumps({"ok": True, "reason": "", "tag": "button"})
    tab = (await session.list_tabs())[0]
    assert json.loads(await session.evaluate(tab, "1+1"))["tag"] == "button"


async def test_evaluate_accepts_an_inline_result_when_there_is_no_result_id(session, firefox):
    firefox.no_result_id = True
    firefox.eval_answer = "42"
    assert await session.evaluate((await session.list_tabs())[0], "x") == "42"


async def test_a_grip_value_is_unwrapped(session, firefox):
    firefox.no_result_id = True
    firefox.eval_answer = {"type": "string", "value": "unwrapped"}
    assert await session.evaluate((await session.list_tabs())[0], "x") == "unwrapped"


async def test_an_undefined_grip_becomes_none(session, firefox):
    firefox.no_result_id = True
    firefox.eval_answer = {"type": "undefined"}
    assert await session.evaluate((await session.list_tabs())[0], "x") is None


async def test_a_click_reports_success(session, firefox):
    firefox.eval_answer = json.dumps({"ok": True, "reason": "", "x": 10, "y": 20})
    result = await session.click((await session.list_tabs())[0], "#go")
    assert result.ok and result.detail["x"] == 10
    assert "#go" in firefox.evaluated[-1]


async def test_a_missing_element_is_a_reason_not_an_exception(session, firefox):
    firefox.eval_answer = json.dumps({"ok": False, "reason": "not found"})
    result = await session.click((await session.list_tabs())[0], "#gone")
    assert not result.ok and result.reason == "not found"


async def test_an_unparsable_page_answer_is_broken_not_silently_ok(session, firefox):
    firefox.eval_answer = "<html>oops"
    result = await session.click((await session.list_tabs())[0], "#go")
    assert not result.ok and "unparsable" in result.reason


async def test_a_non_string_page_answer_is_broken(session, firefox):
    firefox.no_result_id = True
    firefox.eval_answer = {"type": "undefined"}
    result = await session.probe((await session.list_tabs())[0], "#go")
    assert not result.ok and "no answer" in result.reason


async def test_probe_reports_layout_without_clicking(session, firefox):
    firefox.eval_answer = json.dumps({"ok": True, "reason": "", "visible": True, "tag": "a"})
    result = await session.probe((await session.list_tabs())[0], "#link")
    assert result.ok and result.detail["visible"]
    assert "dispatchEvent" not in firefox.evaluated[-1]


async def test_the_session_reports_the_sites_view_of_automation(session, firefox):
    firefox.eval_answer = json.dumps({"ok": True, "webdriver": False, "hasCdc": False})
    signals = await session.automation_signals((await session.list_tabs())[0])
    assert signals == {"webdriver": False, "hasCdc": False}
    assert "navigator.webdriver" in firefox.evaluated[-1]


async def test_a_tripped_signal_is_surfaced(session, firefox):
    firefox.eval_answer = json.dumps({"ok": True, "webdriver": True, "hasCdc": False})
    signals = await session.automation_signals((await session.list_tabs())[0])
    assert signals["webdriver"] is True


async def test_actor_ids_are_never_reused_across_a_reconnect(firefox):
    """Firefox renumbers actors per connection — caching them breaks the reattach."""
    s = RDPSession(RDPTransport(port=firefox.port, timeout=3))
    await s.attach()
    tab = (await s.list_tabs())[0]
    assert await s.console_actor(tab) == "server1.conn1.consoleActor4"
    await s.detach()

    firefox.console_actor = "server1.conn2.consoleActor9"  # a fresh connection renumbers
    await s.attach()
    tab2 = (await s.list_tabs())[0]
    assert await s.console_actor(tab2) == "server1.conn2.consoleActor9"
    await s.detach()


async def test_attach_state_is_visible_to_callers(firefox):
    s = RDPSession(RDPTransport(port=firefox.port, timeout=3))
    assert not s.is_attached
    await s.attach()
    assert s.is_attached
    await s.detach()
    assert not s.is_attached


async def test_a_session_builds_its_own_transport_by_default():
    assert RDPSession().transport.port == 6000


async def test_a_missing_evaluation_result_times_out_rather_than_hanging(session, firefox):
    tab = (await session.list_tabs())[0]
    await session.console_actor(tab)
    session.transport.timeout = 0.3
    firefox.silent = True
    with pytest.raises(RDPClosed):
        await session.evaluate(tab, "1")


async def test_clicking_a_tab_value_object_needs_no_live_handle():
    """FirefoxTab is data, so the pool can hold it across a detach."""
    tab = FirefoxTab(actor="a", title="t", url="u")
    assert (tab.actor, tab.selected) == ("a", False)
