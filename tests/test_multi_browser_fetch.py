"""The fetch seam scans every declared browser, not just Chrome (I-63)."""

import pytest

from app.browser import browser_scan
from app.browser.endpoints import CHROME, FIREFOX
from app.ui.panels.browser_tabs import browser_settings, fetch_all_tabs

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class _Config:
    def __init__(self, **state):
        self._state = state

    def get_state(self, key, default=None):
        return self._state.get(key, default)


class _Bridge:
    def __init__(self, config=None, cdp_tabs=None):
        self.config = config
        self.logs = []
        self.cdp = type("C", (), {"fetch_tabs": lambda _s: _async(cdp_tabs or [])})()

    def _log(self, msg, level="info"):
        self.logs.append((msg, level))


async def _async(value):
    return value


def _bridge_with(endpoints):
    return _Bridge(_Config(cdp_host="127.0.0.1", cdp_port=9222,
                           browser_base_port=9223, browser_endpoints=endpoints))


async def test_with_no_declared_endpoints_the_legacy_chrome_path_is_used():
    """Backward compatibility: an existing install must not change behaviour."""
    bridge = _Bridge(_Config(cdp_host="127.0.0.1", cdp_port=9222), cdp_tabs=["legacy"])
    assert await fetch_all_tabs(bridge) == ["legacy"]


async def test_declared_endpoints_are_all_scanned(monkeypatch):
    async def fake_chrome(endpoint, timeout):
        return [f"chrome:{endpoint.port}"]

    async def fake_firefox(endpoint, timeout):
        return [f"firefox:{endpoint.port}"]

    monkeypatch.setitem(browser_scan.SCANNERS, CHROME, fake_chrome)
    monkeypatch.setitem(browser_scan.SCANNERS, FIREFOX, fake_firefox)
    bridge = _bridge_with([{"kind": "chrome"}, {"kind": "firefox"}])
    assert await fetch_all_tabs(bridge) == ["chrome:9223", "firefox:9224"]


async def test_a_failing_firefox_is_logged_by_name_and_chrome_still_returns(monkeypatch):
    async def fake_chrome(endpoint, timeout):
        return ["chrome-tab"]

    async def dead_firefox(endpoint, timeout):
        raise ConnectionRefusedError("connection refused")

    monkeypatch.setitem(browser_scan.SCANNERS, CHROME, fake_chrome)
    monkeypatch.setitem(browser_scan.SCANNERS, FIREFOX, dead_firefox)
    bridge = _bridge_with([{"kind": "chrome"}, {"kind": "firefox"}])
    assert await fetch_all_tabs(bridge) == ["chrome-tab"]
    messages = " ".join(m for m, _ in bridge.logs)
    assert "Firefox 127.0.0.1:9224" in messages
    assert "--start-debugger-server 9224" in messages


async def test_settings_are_read_from_the_app_config():
    bridge = _bridge_with([{"kind": "firefox"}])
    settings = browser_settings(bridge)
    assert settings["browser_base_port"] == 9223
    assert settings["browser_endpoints"] == [{"kind": "firefox"}]


async def test_a_bridge_without_config_reads_no_settings():
    """RULE 4: no config is empty, and the legacy path still runs."""
    assert browser_settings(_Bridge(None)) == {}
