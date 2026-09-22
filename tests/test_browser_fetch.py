"""One fetch for every browser, every cycle (2026-09-22).

The owner runs Chrome on 9223 AND Firefox on 9224: each reconcile/scan/find
cycle must list the tabs of EVERY enabled browser at its own resolved
endpoint — never just the active one. `browser_fetch.fetch_all_tabs(config)`
reads the live config (shared host + base port + per-browser rows), asks
each endpoint in its own protocol, and returns `TabInfo` rows carrying
`browser`/`protocol`, plus one error line per endpoint that failed.

RED at `a58f617`: `app.ui.panels.browser_fetch` did not exist.
"""

import pytest

from app.persistence.config_manager import ConfigManager
from tests.test_browser_endpoints import FakeChrome
from tests.test_rdp import FakeDebuggerServer

pytestmark = pytest.mark.unit


@pytest.fixture
def chrome():
    c = FakeChrome()
    try:
        yield c
    finally:
        c.close()


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


def _point(cfg, chrome=None, firefox=None, chrome_enabled=True, firefox_enabled=True):
    """Aim the browser rows at the fakes (hand-set ports, like session.json)."""
    cfg.set_state(cdp_host="127.0.0.1", cdp_port=9223, cdp_browsers={
        "chrome": {"enabled": chrome_enabled, "port": chrome.port if chrome else 1},
        "firefox": {"enabled": firefox_enabled, "port": firefox.port if firefox else 1},
        "edge": {"enabled": False},
    })


def test_fetch_lists_every_enabled_browser_with_identity(chrome, firefox, cfg):
    from app.ui.panels import browser_fetch
    _point(cfg, chrome, firefox)
    tabs, errors = browser_fetch.fetch_all_tabs(cfg, timeout=2.0)
    assert errors == []
    assert [(t.browser, t.id) for t in tabs] == [
        ("chrome", "AAA111"), ("chrome", "BBB222"),
        ("firefox", "11"), ("firefox", "12")]
    assert all(t.protocol == "cdp" for t in tabs[:2])
    assert all(t.protocol == "rdp" for t in tabs[2:])
    assert tabs[2].ws_url == f"rdp://127.0.0.1:{firefox.port}#11", \
        "the handle names the tab, not just the endpoint"
    assert tabs[0].title == "Arena A" and tabs[2].url == "https://arena.ai/c/1"


def test_a_dead_endpoint_reports_but_never_hides_the_other_browser(chrome, firefox, cfg):
    from app.ui.panels import browser_fetch
    firefox.close()  # Firefox down; Chrome still up
    _point(cfg, chrome, firefox)
    tabs, errors = browser_fetch.fetch_all_tabs(cfg, timeout=1.0)
    assert [t.id for t in tabs] == ["AAA111", "BBB222"]
    assert len(errors) == 1 and errors[0].startswith("firefox:")


def test_a_disabled_browser_is_skipped_silently(chrome, firefox, cfg):
    from app.ui.panels import browser_fetch
    _point(cfg, chrome, firefox, chrome_enabled=False)
    tabs, errors = browser_fetch.fetch_all_tabs(cfg, timeout=2.0)
    assert errors == []
    assert {t.browser for t in tabs} == {"firefox"}


def test_endpoint_browsers_maps_resolved_ports_to_browser_ids(chrome, firefox, cfg):
    from app.ui.panels import browser_fetch
    _point(cfg, chrome, firefox)
    assert browser_fetch.endpoint_browsers(cfg) == {
        chrome.port: "chrome", firefox.port: "firefox"}


def test_browser_for_ws_resolves_cdp_rdp_and_unknown(chrome, firefox, cfg):
    from app.ui.panels import browser_fetch
    _point(cfg, chrome, firefox)
    assert browser_fetch.browser_for_ws(
        cfg, f"ws://127.0.0.1:{chrome.port}/devtools/page/AAA111") == "chrome"
    assert browser_fetch.browser_for_ws(
        cfg, f"rdp://127.0.0.1:{firefox.port}#11") == "firefox"
    assert browser_fetch.browser_for_ws(cfg, "ws://127.0.0.1:1/devtools/page/x") == ""
    assert browser_fetch.browser_for_ws(cfg, "garbage") == ""


async def test_the_async_wrapper_returns_the_same_rows(chrome, firefox, cfg):
    from app.ui.panels import browser_fetch
    _point(cfg, chrome, firefox)
    tabs, errors = await browser_fetch.fetch_all_tabs_async(cfg, timeout=2.0)
    assert errors == []
    assert [(t.browser, t.id) for t in tabs] == [
        ("chrome", "AAA111"), ("chrome", "BBB222"),
        ("firefox", "11"), ("firefox", "12")]
