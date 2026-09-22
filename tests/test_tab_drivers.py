"""Tab handles route to the right driver (2026-09-22).

Every join/connect path receives one string — a CDP `ws://…/devtools/page/…`
socket or an RDP `rdp://host:port#tab` handle — and must (a) read the tab id
out of it, (b) drive it with the matching protocol, (c) stamp the pool row
with the browser that owns the endpoint, and (d) name the browser when it
fails. The acceptance is a Firefox tab connecting and pool-joining over a
real fake debugger server.

RED at `a58f617`: `tab_id_from_ws` / `make_driver` / `use_tab_driver` did
not exist.
"""

import pytest

from app.browser.page_pool import PagePool
from app.persistence.config_manager import ConfigManager
from tests.test_panel_slots import make_host
from tests.test_rdp import FakeDebuggerServer

pytestmark = pytest.mark.unit


class FakeSignal:
    """A Qt-signal-shaped recorder (connect + emit)."""

    def __init__(self):
        self.slots, self.emitted = [], []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self, *args):
        self.emitted.append(args[0] if args else None)
        for slot in self.slots:
            slot(*args)


@pytest.fixture
def firefox():
    srv = FakeDebuggerServer()
    try:
        yield srv
    finally:
        srv.close()


@pytest.fixture
def cfg(isolated_config_dir):
    return ConfigManager(str(isolated_config_dir))


def _bridge(cfg, firefox=None):
    from app.browser.cdp_client import CDPClient
    if firefox is not None:
        cfg.set_state(cdp_host="127.0.0.1", cdp_port=9223, cdp_browsers={
            "chrome": {"enabled": True, "port": 9223},
            "firefox": {"enabled": True, "port": firefox.port},
            "edge": {"enabled": False},
        })
    host, logs = make_host((), cdp=CDPClient(host="127.0.0.1", port=9224),
                           config=cfg, _page_pool=PagePool(),
                           connection_status=FakeSignal(),
                           _connect_in_progress=False,
                           _last_connect_ws="", _last_connect_ts=0.0)
    return host, logs


def _handle(port, tab="11"):
    return f"rdp://127.0.0.1:{port}#{tab}"


# ---- the handle --------------------------------------------------------------


def test_tab_id_from_ws_reads_cdp_rdp_and_garbage():
    from app.ui.panels.browser_fetch import tab_id_from_ws
    assert tab_id_from_ws("ws://127.0.0.1:9223/devtools/page/AAA111") == "AAA111"
    assert tab_id_from_ws("rdp://127.0.0.1:9224#11") == "11"
    assert tab_id_from_ws("rdp://127.0.0.1:9224") == ""
    assert tab_id_from_ws("garbage") == ""


def test_make_driver_builds_cdp_or_rdp_by_scheme():
    from app.browser.cdp_client import CDPClient
    from app.browser.rdp_driver import RdpDriver
    from app.ui.panels.browser_fetch import make_driver
    assert isinstance(make_driver("127.0.0.1", 9223, "ws://127.0.0.1:9223/devtools/page/A"), CDPClient)
    assert isinstance(make_driver("127.0.0.1", 9224, _handle(9224)), RdpDriver)


# ---- adoption ------------------------------------------------------------------


async def test_use_tab_driver_adopts_and_reuses_per_scheme(firefox, cfg):
    from app.browser.cdp_client import CDPClient
    from app.browser.rdp_driver import RdpDriver
    from app.ui.panels.browser_tabs import use_tab_driver
    bridge, _ = _bridge(cfg, firefox)
    first = bridge.cdp
    drv = await use_tab_driver(bridge, _handle(firefox.port))
    assert isinstance(drv, RdpDriver) and bridge.cdp is drv
    assert bridge.cdp is await use_tab_driver(bridge, _handle(firefox.port, "12")), "same scheme reuses"
    back = await use_tab_driver(bridge, "ws://127.0.0.1:9223/devtools/page/AAA111")
    assert isinstance(back, CDPClient) and back is first, "the CDP driver survives the round-trip"


async def test_firefox_tab_connects_and_joins_the_pool(firefox, cfg):
    from app.ui.panels.browser_tabs import do_connect_tab
    bridge, logs = _bridge(cfg, firefox)
    await do_connect_tab(bridge, _handle(firefox.port))
    page = bridge._page_pool.get_page("11")
    assert page is not None and page.browser == "firefox"
    assert page.title == "Arena A" and page.url == "https://arena.ai/c/1"
    client, ctrl = bridge._page_pool.get_clients("11")
    assert client is not None and client.is_connected and ctrl is not None
    assert "connected" in bridge.connection_status.emitted
    assert any("Firefox" in msg for _lvl, msg in logs)


async def test_firefox_connect_failure_names_the_browser_and_the_flag(cfg):
    from app.ui.panels.browser_tabs import do_connect_tab
    bridge, logs = _bridge(cfg)
    await do_connect_tab(bridge, _handle(1))
    assert bridge._page_pool.get_page("11") is None
    assert "error" in bridge.connection_status.emitted
    text = " ".join(msg for _lvl, msg in logs)
    assert "Firefox" in text and "--start-debugger-server" in text and "tcp://" in text


async def test_pool_join_constructs_the_matching_driver(firefox, cfg):
    from app.browser.rdp_driver import RdpDriver
    from app.ui.panels.page_pool import connect_pool_client
    bridge, _ = _bridge(cfg, firefox)
    client = await connect_pool_client(bridge, _handle(firefox.port))
    assert isinstance(client, RdpDriver) and client.is_connected
    assert await connect_pool_client(bridge, "ws://127.0.0.1:1/devtools/page/x") is None
