"""Settings → endpoints → scan, and the log that names the right browser (I-63)."""

import pytest

from app.browser import browser_scan
from app.browser.browser_scan import EndpointResult, ScanReport
from app.browser.endpoints import CHROME, FIREFOX, BrowserEndpoint
from app.services.browser_connect import endpoints_from_settings, log_scan_report, scan_all

pytestmark = pytest.mark.unit


def test_declared_endpoints_are_used_when_present():
    settings = {"cdp_host": "127.0.0.1", "browser_base_port": 9223,
                "browser_endpoints": [{"kind": "chrome"}, {"kind": "firefox"}]}
    found = endpoints_from_settings(settings)
    assert [(e.port, e.kind) for e in found] == [(9223, CHROME), (9224, FIREFOX)]


def test_the_legacy_single_chrome_setup_still_works():
    """An upgrade with no new settings must behave exactly as before."""
    found = endpoints_from_settings({"cdp_host": "127.0.0.1", "cdp_port": 9222})
    assert [(e.port, e.kind) for e in found] == [(9222, CHROME)]


def test_an_all_invalid_endpoint_list_falls_back_rather_than_scanning_nothing():
    settings = {"cdp_host": "127.0.0.1", "cdp_port": 9222,
                "browser_endpoints": [{"kind": "safari"}]}
    assert [e.port for e in endpoints_from_settings(settings)] == [9222]


def test_settings_may_be_an_attribute_object_not_only_a_dict():
    settings = type("S", (), {"cdp_host": "127.0.0.1", "cdp_port": 9222})()
    assert [e.port for e in endpoints_from_settings(settings)] == [9222]


def test_no_settings_at_all_yields_no_endpoints():
    assert endpoints_from_settings(None) == []
    assert endpoints_from_settings({}) == []


@pytest.mark.asyncio
async def test_scan_all_reads_every_declared_browser(monkeypatch):
    async def fake_chrome(endpoint, timeout):
        return ["chrome-tab"]

    async def fake_firefox(endpoint, timeout):
        return ["ff-tab"]

    monkeypatch.setitem(browser_scan.SCANNERS, CHROME, fake_chrome)
    monkeypatch.setitem(browser_scan.SCANNERS, FIREFOX, fake_firefox)
    settings = {"cdp_host": "127.0.0.1", "browser_base_port": 9223,
                "browser_endpoints": [{"kind": "chrome"}, {"kind": "firefox"}]}
    report = await scan_all(settings)
    assert report.tabs == ["chrome-tab", "ff-tab"]


def test_the_log_names_the_failing_browser():
    firefox = BrowserEndpoint("127.0.0.1", 9224, FIREFOX)
    report = ScanReport([EndpointResult(firefox, error="connection refused")])
    lines = []
    log_scan_report(report, lambda msg, level="info": lines.append((msg, level)))
    assert any("Firefox 127.0.0.1:9224" in m for m, _ in lines)
    assert not any("Chrome" in m for m, _ in lines)
    assert ("error" in [lvl for _, lvl in lines])


def test_a_healthy_scan_logs_one_info_summary():
    chrome = BrowserEndpoint("127.0.0.1", 9223, CHROME)
    report = ScanReport([EndpointResult(chrome, tabs=["t"])])
    lines = []
    log_scan_report(report, lambda msg, level="info": lines.append((msg, level)))
    assert len(lines) == 1 and lines[0][1] == "info"


def test_logging_without_a_logger_is_harmless():
    log_scan_report(ScanReport([]), None)


def test_the_connection_prompt_is_explained_once_not_every_scan():
    """The user saw a dialog per scan; the hint must not become spam too (I-64)."""
    import app.services.browser_connect as bc
    bc._hinted.clear()
    firefox = BrowserEndpoint("127.0.0.1", 9224, FIREFOX)
    lines = []
    log = lambda msg, level="info": lines.append(msg)
    assert bc.log_firefox_hint(firefox, log) is True
    first = len(lines)
    assert bc.log_firefox_hint(firefox, log) is False
    assert len(lines) == first
    assert any("prompt-connection" in m for m in lines)
    assert any("9224" in m for m in lines)


def test_chrome_gets_no_firefox_prompt_hint():
    import app.services.browser_connect as bc
    bc._hinted.clear()
    lines = []
    chrome = BrowserEndpoint("127.0.0.1", 9223, CHROME)
    assert bc.log_firefox_hint(chrome, lambda m, l="info": lines.append(m)) is False
    assert lines == []


def test_the_hint_is_silent_without_a_logger():
    import app.services.browser_connect as bc
    bc._hinted.clear()
    assert bc.log_firefox_hint(BrowserEndpoint("127.0.0.1", 9224, FIREFOX), None) is False


def test_the_user_js_snippet_turns_the_prompt_off():
    from app.browser.rdp.prefs_help import user_js_snippet
    text = user_js_snippet()
    assert 'user_pref("devtools.debugger.prompt-connection", false);' in text
    assert 'user_pref("devtools.debugger.remote-enabled", true);' in text
