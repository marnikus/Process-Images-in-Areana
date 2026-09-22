"""Pool join routes each tab to its own protocol client (I-63).

The reported bug in one sentence: a Firefox tab was handed to the CDP client,
which asked for a WebSocket that Firefox does not serve.
"""

import pytest

from app.ui.panels.page_pool import connect_pool_client, pool_tab_id

pytestmark = pytest.mark.unit


class _Bridge:
    def __init__(self):
        self.logs = []
        self._page_pool = None

    def _log(self, msg, level="info"):
        self.logs.append((msg, level))


def test_a_chrome_locator_keeps_its_page_id_as_the_pool_key():
    assert pool_tab_id("ws://127.0.0.1:9223/devtools/page/AB12") == "AB12"


def test_a_firefox_locator_is_its_own_pool_key():
    """Firefox actors renumber per connection, so the locator is the stable handle."""
    locator = "rdp://127.0.0.1:9224/server1.conn1.tabDescriptor1"
    assert pool_tab_id(locator) == locator


def test_an_unrecognised_locator_is_used_whole():
    assert pool_tab_id("something-else") == "something-else"


@pytest.mark.asyncio
async def test_a_firefox_tab_gets_the_rdp_client_not_the_cdp_one(monkeypatch):
    built = {}

    class FakeFirefoxClient:
        def __init__(self, *a, **kw):
            self.last_error = ""

        async def connect(self, locator):
            built["locator"] = locator
            return True

    import app.browser.rdp.pool_client as pc
    monkeypatch.setattr(pc, "FirefoxPoolClient", FakeFirefoxClient)

    import app.browser.cdp_client as cdp

    class Exploding:
        def __init__(self, *a, **kw):
            raise AssertionError("a Firefox tab must never reach the CDP client")

    monkeypatch.setattr(cdp, "CDPClient", Exploding)

    locator = "rdp://127.0.0.1:9224/server1.conn1.tabDescriptor1"
    client = await connect_pool_client(_Bridge(), locator)
    assert isinstance(client, FakeFirefoxClient) and built["locator"] == locator


@pytest.mark.asyncio
async def test_a_chrome_tab_still_gets_the_cdp_client(monkeypatch):
    seen = {}

    class FakeCDP:
        def __init__(self, host="127.0.0.1", port=9222):
            seen["port"] = port

        async def connect(self, ws_url):
            seen["ws"] = ws_url
            return True

    import app.browser.cdp_client as cdp
    monkeypatch.setattr(cdp, "CDPClient", FakeCDP)

    ws = "ws://127.0.0.1:9223/devtools/page/AB12"
    client = await connect_pool_client(_Bridge(), ws)
    assert isinstance(client, FakeCDP) and seen["ws"] == ws


@pytest.mark.asyncio
async def test_a_refused_firefox_join_logs_the_rdp_reason(monkeypatch):
    class FailingClient:
        def __init__(self, *a, **kw):
            self.last_error = "connection refused"

        async def connect(self, locator):
            return False

    import app.browser.rdp.pool_client as pc
    monkeypatch.setattr(pc, "FirefoxPoolClient", FailingClient)

    bridge = _Bridge()
    assert await connect_pool_client(bridge, "rdp://127.0.0.1:9224/a1") is None
    assert any("Firefox pool connect failed" in m and "connection refused" in m
               for m, _ in bridge.logs)


@pytest.mark.asyncio
async def test_a_firefox_tab_joins_without_a_cdp_arena_controller(monkeypatch):
    """A click-only RDP tab must not be handed a CDP controller (I-63)."""
    import app.ui.panels.page_pool as pp
    joined = {}

    async def fake_finish(bridge, info, client, ctrl):
        joined["ctrl"] = ctrl
        joined["info"] = info

    class FakeFirefoxClient:
        last_error = ""
        tab_url = "https://arena.ai/chat"

        async def connect(self, locator):
            return True

    import app.browser.rdp.pool_client as pc
    monkeypatch.setattr(pc, "FirefoxPoolClient", lambda *a, **kw: FakeFirefoxClient())
    monkeypatch.setattr(pp, "finish_pool_join", fake_finish)

    locator = "rdp://127.0.0.1:9224/server1.conn1.tabDescriptor1"
    await pp.do_connect_page_pool(_Bridge(), locator)
    assert joined["ctrl"] is None
    assert joined["info"].tab_id == locator
    assert joined["info"].url == "https://arena.ai/chat"


@pytest.mark.asyncio
async def test_a_chrome_tab_still_gets_its_arena_controller(monkeypatch):
    import app.ui.panels.page_pool as pp
    joined = {}

    async def fake_finish(bridge, info, client, ctrl):
        joined["ctrl"] = ctrl

    async def fake_resolve(bridge, tab_id, ws_url):
        return "Arena", "https://arena.ai/"

    class FakeCDP:
        def __init__(self, *a, **kw):
            pass

        async def connect(self, ws_url):
            return True

    import app.browser.cdp_client as cdp
    import app.browser.cdp_arena as arena
    monkeypatch.setattr(cdp, "CDPClient", FakeCDP)
    monkeypatch.setattr(arena, "CDPArenaController", lambda *a, **kw: "the-controller")
    monkeypatch.setattr(pp, "finish_pool_join", fake_finish)
    monkeypatch.setattr(pp, "resolve_tab_info", fake_resolve)

    bridge = _Bridge()
    bridge._page_pool = None
    await pp.do_connect_page_pool(bridge, "ws://127.0.0.1:9223/devtools/page/AB12")
    assert joined["ctrl"] == "the-controller"
