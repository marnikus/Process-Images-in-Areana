"""Joining a Firefox tab into the pool — "i can not connect the Firefox browser" (round 9).

A pool join is what makes a tab *work*: the row gets its `{email}_{4 digits}` label, a worker
number, a cooldown timer, and a per-tab client the job path evaluates through. For Firefox
that client is an **RDP attachment** — the socket is opened for the join, the tab id is the
`ctx-N` handle, every action is JS in that tab, and detaching never touches the browser.

RED at `741b771`: `connect_tab` refused `rdp://` handles by name, and the join always built a
CDP client pointed at the pool's active endpoint.
"""

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo
from app.persistence.config_manager import ConfigManager
from app.ui.panels import page_pool as pp
from app.ui.panels.page_pool import PagePoolMixin, do_connect_page_pool
from tests.fakes.rdp_stub_server import RdpStubServer
from tests.test_panel_slots import make_state

pytestmark = pytest.mark.unit

BASE = 9240


class Emitter:
    """A Qt signal's only job in these tests: forward emit(*args) to a list."""

    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class Host(PagePoolMixin):
    """The pool panel on a bare host (same shape as the S1 join harness)."""

    def __init__(self, pool, cfg):
        self._page_pool = pool
        self.config = cfg
        self.state = make_state()
        self.logs = []
        self._log = lambda msg, level="info": self.logs.append((level, msg))
        self.page_pool_updated = Emitter()
        self.connection_status = Emitter()
        self.tabs_received = Emitter()
        self._emit_pool_status = lambda: None
        self._persist_cooldowns = lambda: None
        self._save_cooldowns = lambda: None


@pytest.fixture
def cfg(isolated_config_dir):
    return ConfigManager(str(isolated_config_dir))


@pytest.fixture
def stub():
    server = RdpStubServer()
    try:
        yield server
    finally:
        server.close()


def _bridge(cfg, stub, **overrides):
    cfg.set_state(cdp_host="127.0.0.1", cdp_port=BASE, active_browser="firefox",
                  cdp_browsers={"chrome": {"enabled": True, "port": 1},
                                "firefox": {"enabled": True, "port": stub.port},
                                "edge": {"enabled": False}})
    pool = PagePool()
    pool._host, pool._port, pool._browser = "127.0.0.1", BASE, "chrome"
    host = Host(pool, cfg)
    for key, value in overrides.items():
        setattr(host, key, value)
    return host


async def test_a_firefox_handle_joins_the_pool_and_names_its_browser(cfg, stub, monkeypatch):
    host = _bridge(cfg, stub)
    monkeypatch.setattr(pp, "restore_page_state", lambda bridge, tab_id: None)
    await do_connect_page_pool(host, f"rdp://127.0.0.1:{stub.port}/ctx-3")
    page = host._page_pool.get_page("ctx-3")
    assert page is not None and isinstance(page, PageInfo)
    assert page.browser == "firefox", "a pooled row says which browser it belongs to"
    assert page.title == "Arena" and page.url == "https://arena.ai/c/1", \
        "title/url come from the tab's own endpoint, not the active browser's"
    assert any("Pool added" in msg for _lvl, msg in host.logs)
    assert "GET " not in stub.raw_text(), "the join never speaks HTTP to a DevTools socket"


async def test_the_pooled_firefox_client_evaluates_over_rdp(cfg, stub, monkeypatch):
    host = _bridge(cfg, stub)
    monkeypatch.setattr(pp, "restore_page_state", lambda bridge, tab_id: None)
    await do_connect_page_pool(host, f"rdp://127.0.0.1:{stub.port}/ctx-4")
    client, controller = host._page_pool.get_clients("ctx-4")
    assert client is not None and client.is_connected
    assert await client.evaluate("JSON.stringify(document.title)") == "Проверка 🚀", \
        "the job path's one execution seam works on a Firefox tab"
    assert controller is not None, "the Arena controller is built the same way for both channels"


async def test_a_worker_badge_reaches_the_firefox_tab(cfg, stub, monkeypatch):
    """The badge/owner probes are the join's own JS — they must land on the RDP client."""
    host = _bridge(cfg, stub)
    monkeypatch.setattr(pp, "restore_page_state", lambda bridge, tab_id: None)
    await do_connect_page_pool(host, f"rdp://127.0.0.1:{stub.port}/ctx-3")
    assert stub.was_sent("evaluateJSAsync"), "JS reached the devtools socket"
    sent = [p for p in stub.received if p.get("type") == "evaluateJSAsync"]
    assert any("JSON.stringify" in p["text"] for p in sent), "the probe JS is a JSON answer"


async def test_the_join_attaches_to_the_handle_not_to_the_pools_endpoint(cfg, stub, monkeypatch):
    """Chrome is the pool's active browser on 9240; the Firefox handle is on another port."""
    host = _bridge(cfg, stub)
    monkeypatch.setattr(pp, "restore_page_state", lambda bridge, tab_id: None)
    await do_connect_page_pool(host, f"rdp://127.0.0.1:{stub.port}/ctx-3")
    client, _ctrl = host._page_pool.get_clients("ctx-3")
    assert (client._host, client._port) == ("127.0.0.1", stub.port)
    assert client.protocol() == "rdp"


async def test_an_unknown_firefox_tab_is_refused_with_the_reason_the_bridge_logs(cfg, stub, monkeypatch):
    host = _bridge(cfg, stub)
    monkeypatch.setattr(pp, "restore_page_state", lambda bridge, tab_id: None)
    await do_connect_page_pool(host, f"rdp://127.0.0.1:{stub.port}/ctx-99")
    assert host._page_pool.get_page("ctx-99") is None
    assert any("ctx-99" in msg for _lvl, msg in host.logs), host.logs


async def test_a_bidi_session_handle_is_refused_by_name(cfg, stub, monkeypatch):
    host = _bridge(cfg, stub)
    monkeypatch.setattr(pp, "restore_page_state", lambda bridge, tab_id: None)
    await do_connect_page_pool(host, "ws://127.0.0.1:9241/session#ctx-a")
    assert host._page_pool.get_page("ctx-a") is None
    assert any("BIDI" in msg.upper() for _lvl, msg in host.logs), \
        "the flagged channel is named, not attempted as a Chrome socket"


async def test_the_connect_button_pools_a_firefox_tab(cfg, stub, monkeypatch):
    """The header's Connect path (`do_connect_tab`) — "i can not connect the Firefox browser".

    It attaches the selected handle (`rdp://…/ctx-3`), announces it as the DevTools socket it
    is, and pool-joins the tab through the same dedicated per-tab client every other browser
    uses. Nothing here restarts Firefox: one socket, opened and closed.
    """
    from app.ui.panels import browser_tabs as bt
    host = _bridge(cfg, stub)
    host.cdp = _idle_client(stub.port)          # the active browser's client, not attached
    monkeypatch.setattr(pp, "restore_page_state", lambda bridge, tab_id: None)
    await bt.do_connect_tab(host, f"rdp://127.0.0.1:{stub.port}/ctx-3")
    page = host._page_pool.get_page("ctx-3")
    assert page is not None, host.logs
    assert page.browser == "firefox" and page.ws_url.startswith("rdp://")
    client, _ctrl = host._page_pool.get_clients("ctx-3")
    assert await client.evaluate("JSON.stringify(document.title)") == "Arena"
    assert "GET " not in stub.raw_text()


def _idle_client(port):
    """The active browser's client (concatenated for one endpoint), never attached."""
    from app.browser.cdp_client import CDPClient
    return CDPClient(host="127.0.0.1", port=port, protocol="rdp")
