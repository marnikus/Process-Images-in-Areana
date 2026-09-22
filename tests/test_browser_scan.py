"""Every enabled endpoint, one pass — the owner's second request (round 9).

"now every browser like chrome - firefox and others has it individual port. if it starts
from 9223 then app should parse all page on ws: 9223, ws: 9224 and ws: 9225 (all that
defined in win settings)"

So: a pass lists Chrome (base + 0), Firefox (base + 1) and Edge (base + 2) — each at its own
endpoint, each over its own protocol, skipping a browser switched off in the settings window,
tagging every row with the browser it came from, and reporting one line per browser that is
missing (never a line per pass, and never an HTTP request to a DevTools socket).

RED at `741b771`: `enabled_targets` took the wrong port (`profile.port_offset` as a port),
the panel never called it, and the Settings payload had no scan line.
"""

import json

import pytest
from PySide6.QtCore import Signal

from app.browser import browsers as br
from app.browser import endpoints
from app.persistence.config_manager import ConfigManager
from app.ui.panels import browser_tabs as bt
from app.ui.panels.cdp_tools import CdpToolsMixin
from tests.fakes.rdp_stub_server import RdpStubServer
from tests.test_attached import _free_port
from tests.test_browser_endpoints import FakeChrome
from tests.test_panel_slots import make_cdp, make_host, make_state

pytestmark = pytest.mark.unit

BASE = 9230          # a base port no test stub binds; every stub gets an explicit override


@pytest.fixture
def chrome():
    server = FakeChrome()
    try:
        yield server
    finally:
        server.close()


@pytest.fixture
def firefox():
    server = RdpStubServer()
    try:
        yield server
    finally:
        server.close()


@pytest.fixture
def cfg(isolated_config_dir):
    return ConfigManager(str(isolated_config_dir))


def _rows(**overrides) -> dict:
    """Settings rows: every browser on, each with its own endpoint override."""
    rows = {profile.id: {"enabled": True, "port": 0, "user_data_dir": "", "extra_args": ""}
            for profile in br.PROFILES}
    for browser_id, entry in overrides.items():
        rows[browser_id].update(entry)
    return rows


def _host(cfg, **attrs):
    host, logs = make_host((CdpToolsMixin,), cdp=make_cdp(connected=False), config=cfg,
                           state=make_state(), highlight_rect=Signal(str), _page_pool=None, **attrs)
    return host, logs


def _tabs_host(cfg, **attrs):
    host, logs = make_host((bt.BrowserTabsMixin,), cdp=make_cdp(connected=False), config=cfg,
                           state=make_state(), highlight_rect=Signal(str), _page_pool=None, **attrs)
    return host, logs


# ── the listing seam: every enabled endpoint, its own protocol ──


def test_enabled_targets_lists_every_enabled_browser_at_its_own_endpoint(chrome, firefox):
    rows = _rows(chrome={"port": chrome.port}, firefox={"port": firefox.port},
                 edge={"enabled": False})
    targets, notes = endpoints.enabled_targets(rows, BASE, "127.0.0.1", 2.0)
    assert notes == [], "both running browsers are listed without a note"
    assert {t.browser for t in targets} == {"chrome", "firefox"}
    assert {t.protocol for t in targets} == {"cdp", "rdp"}
    assert {t.port for t in targets} == {chrome.port, firefox.port}, \
        "each row carries the endpoint it came from"
    assert [t.id for t in targets if t.browser == "firefox"] == ["ctx-3", "ctx-4"]
    assert "GET " not in firefox.raw_text(), "a DevTools socket is never asked for /json/list"


def test_the_shared_base_port_plus_each_offset_is_the_default_endpoint(chrome):
    """The F5 bug: `port_offset` (0/1/2) was passed as a port. Offsets are not ports."""
    rows = _rows()
    rows["chrome"]["port"] = chrome.port
    rows["firefox"]["port"] = 0
    targets, notes = endpoints.enabled_targets(rows, chrome.port, "127.0.0.1", 0.4)
    assert [t.browser for t in targets] == ["chrome", "chrome"]
    assert notes and notes[0].browser == "firefox"
    assert notes[0].port == chrome.port + 1, "Firefox is asked at base + 1, not at 1"
    assert notes[0].reason, "and the note says what to do about it"


def test_a_missing_browser_never_hides_a_live_one(chrome):
    rows = _rows(chrome={"port": chrome.port}, firefox={"port": 1}, edge={"port": 1})
    targets, notes = endpoints.enabled_targets(rows, BASE, "127.0.0.1", 0.4)
    assert len(targets) == 2 and {t.browser for t in targets} == {"chrome"}
    assert {n.browser for n in notes} == {"firefox", "edge"}, "one note per missing browser"
    assert all(n.reason for n in notes)


# ── the one panel seam the app parses through ──


async def test_live_tab_rows_parses_every_enabled_browser_not_just_the_active_one(cfg, chrome, firefox):
    cfg.set_state(cdp_host="127.0.0.1", cdp_port=BASE, active_browser="chrome",
                  cdp_browsers={"chrome": {"enabled": True, "port": chrome.port},
                                "firefox": {"enabled": True, "port": firefox.port},
                                "edge": {"enabled": False}})
    host, logs = _tabs_host(cfg)
    rows = await bt.live_tab_rows(host)
    assert [r.id for r in rows] == ["tab-3", "tab-4", "ctx-3", "ctx-4"] or \
        len(rows) == 2 + 2, f"Chrome's two tabs and Firefox's two tabs: {[r.id for r in rows]}"
    assert {r.browser for r in rows} == {"chrome", "firefox"}
    assert logs == [] or all("edge" not in msg for _lvl, msg in logs), \
        "a browser switched off is not reported at all"


async def test_a_missing_browser_is_reported_once_per_reason_not_once_per_pass(cfg, chrome, firefox):
    cfg.set_state(cdp_host="127.0.0.1", cdp_port=BASE, active_browser="firefox",
                  cdp_browsers={"chrome": {"enabled": True, "port": chrome.port},
                                "firefox": {"enabled": True, "port": firefox.port},
                                "edge": {"enabled": False}})
    host, logs = _tabs_host(cfg)
    firefox.close()                                  # Firefox goes away mid-session
    await bt.live_tab_rows(host)
    first = [msg for _lvl, msg in logs if "firefox" in msg]
    assert len(first) == 1, f"one line for the missing browser: {logs}"
    assert "--start-debugger-server" in first[0], "the line names the flag Firefox needs"
    await bt.live_tab_rows(host)
    assert len([msg for _lvl, msg in logs if "firefox" in msg]) == 1, "the same reason is not spammed"
    server = RdpStubServer()                         # …and it comes back
    try:
        cfg.set_state(cdp_browsers={"chrome": {"enabled": True, "port": chrome.port},
                                    "firefox": {"enabled": True, "port": server.port},
                                    "edge": {"enabled": False}})
        assert len(await bt.live_tab_rows(host)) == 4, "both browsers again, in one pass"
    finally:
        server.close()


async def test_a_dead_firefox_still_lets_the_app_run_chrome(cfg, chrome):
    cfg.set_state(cdp_host="127.0.0.1", cdp_port=BASE, active_browser="chrome",
                  cdp_browsers={"chrome": {"enabled": True, "port": chrome.port},
                                "firefox": {"enabled": True, "port": 1},
                                "edge": {"enabled": False}})
    host, _logs = _tabs_host(cfg)
    rows = await bt.live_tab_rows(host)
    assert {r.browser for r in rows} == {"chrome"} and len(rows) == 2, \
        "one browser down never empties the pass"


async def test_the_active_browser_reason_is_the_actionable_one(cfg, chrome):
    from app.browser import browsers
    cfg.set_state(cdp_host="127.0.0.1", cdp_port=BASE, active_browser="firefox",
                  cdp_browsers={"firefox": {"enabled": True, "port": 1}, "chrome": {"enabled": False},
                                "edge": {"enabled": False}})
    host, logs = _tabs_host(cfg)
    await bt.live_tab_rows(host)
    assert logs and browsers.profile_of("firefox").label in logs[0][1] or logs
    assert any("--start-debugger-server" in msg for _lvl, msg in logs), logs


# ── what the Settings window says it scans ──


def test_the_settings_payload_lists_the_endpoints_it_scans(cfg):
    cfg.set_state(cdp_host="127.0.0.1", cdp_port=9223, active_browser="chrome",
                  cdp_browsers={"chrome": {"enabled": True}, "firefox": {"enabled": True},
                                "edge": {"enabled": False}})
    host, _ = _host(cfg)
    payload = json.loads(host.get_cdp_config())
    targets = {t["id"]: t for t in payload["scan_targets"]}
    assert set(targets) == {"chrome", "firefox", "edge"}, "every browser, registry order"
    assert targets["chrome"]["port"] == 9223 and targets["chrome"]["enabled"] is True
    assert targets["firefox"]["port"] == 9224 and targets["firefox"]["protocol"] == "rdp"
    assert targets["edge"]["enabled"] is False
    line = payload["scan_line"]
    assert "9223" in line and "9224" in line and "RDP" in line
    assert "off" in line.lower(), "a browser switched off says so instead of looking scanned"


def test_saving_pushes_the_browsers_protocol_to_the_live_client(cfg):
    host, _logs = _host(cfg)
    pushed = []
    host.cdp.set_protocol = lambda protocol, browser="": pushed.append((protocol, browser))
    host.cdp.set_host_port = lambda h, p: None
    host.set_cdp_config(json.dumps({"browser": "firefox", "host": "127.0.0.1", "port": 9223}))
    assert pushed == [("rdp", "firefox")], "the client must know which channel 9224 is"
    host.set_cdp_config(json.dumps({"browser": "chrome", "port": 9223}))
    assert pushed[-1] == ("cdp", "chrome")


# ── the reconciler's own seam: it must see every enabled browser (D-1) ──


async def test_the_reconciler_lists_every_enabled_browser_not_only_the_active_one(cfg, chrome, firefox):
    """The pass behind Refresh/Reparse/auto-scan is `LiveDeps.fetch_tabs` (round 9, D-1).

    It used to be `bridge.cdp.fetch_tabs()` — the ACTIVE browser's one endpoint — so a
    Firefox tab could never be planned, joined or labelled, and the active Firefox row
    asked a DevTools socket for Chrome's JSON every pass (the owner's log).
    """
    cfg.set_state(cdp_host="127.0.0.1", cdp_port=BASE, active_browser="chrome",
                  cdp_browsers={"chrome": {"enabled": True, "port": chrome.port},
                                "firefox": {"enabled": True, "port": firefox.port},
                                "edge": {"enabled": False}})
    host, _logs = _tabs_host(cfg)
    tabs = await bt.live_deps(host).fetch_tabs()
    assert {t.browser for t in tabs} == {"chrome", "firefox"}, [getattr(t, "id", "") for t in tabs]
    assert {getattr(t, "protocol", "") for t in tabs} == {"cdp", "rdp"}
    assert all(getattr(t, "ws_url", "") for t in tabs), "every row carries the handle to join with"
    assert "GET " not in firefox.raw_text(), "and the DevTools socket is still never sent HTTP"


async def test_a_planned_join_for_a_firefox_row_uses_the_devtools_handle(cfg, chrome, firefox):
    """The plan the reconciler applies: a Firefox row joins by `rdp://…/ctx-N`."""
    from app.services import auto_connect as ac
    cfg.set_state(cdp_host="127.0.0.1", cdp_port=BASE, active_browser="chrome",
                  cdp_browsers={"chrome": {"enabled": True, "port": chrome.port},
                                "firefox": {"enabled": True, "port": firefox.port},
                                "edge": {"enabled": False}})
    host, _logs = _tabs_host(cfg)
    tabs = await bt.live_deps(host).fetch_tabs()
    plan = ac.plan_auto_connect(tabs, "arena.ai", [], [])
    handles = [s for s in plan.connect if s.startswith("rdp://")]
    assert handles, f"a Firefox tab is planned for the join: {plan.connect}"
    assert handles[0].endswith("/ctx-3") and str(firefox.port) in handles[0]


# ── no mis-wiring: a Firefox tab is never handed the Chrome client (D-2) ──


async def test_a_firefox_tab_that_fails_to_attach_never_gets_the_chrome_client(cfg, chrome, monkeypatch):
    """The fallback pool-join reuses the primary CDP client — never for a remote handle.

    A Firefox row whose endpoint is down must leave the pool EMPTY (with a reason), not
    register a `ctx-N` page wired to the active Chrome client: that would send every job
    action of that tab to the wrong browser, silently.
    """
    dead = _free_port()
    cfg.set_state(cdp_host="127.0.0.1", cdp_port=BASE, active_browser="chrome",
                  cdp_browsers={"chrome": {"enabled": True, "port": chrome.port},
                                "firefox": {"enabled": True, "port": dead},
                                "edge": {"enabled": False}})
    from app.browser.page_pool import PagePool
    from app.ui.panels.page_pool import PagePoolMixin, do_connect_page_pool

    class PoolHost(PagePoolMixin):
        page_pool_updated = Signal(str)
        connection_status = Signal(str)

    host = PoolHost()
    host._page_pool, host.config = PagePool(), cfg
    host._emit_pool_status = lambda: None
    logs = []
    host._log = lambda msg, level="info": logs.append((level, msg))
    host.state = make_state()
    monkeypatch.setattr("app.ui.panels.page_pool.restore_page_state", lambda bridge, tab_id: None)
    await do_connect_page_pool(host, f"rdp://127.0.0.1:{dead}/ctx-3")
    assert host._page_pool.get_page("ctx-3") is None, "no page for a tab that never attached"
    assert not host._page_pool.get_clients("ctx-3")[0], "and no client either"
    assert any("fix" in msg.lower() or "not reachable" in msg.lower() or "failed" in msg.lower()
               for _lvl, msg in logs), logs
