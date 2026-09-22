"""Multi-browser scan: every port, its own protocol, failures named (I-63).

The regression under test is the reported bug — Firefox on 9224 was asked for
`http://…/json/list`, answered `Not Found`, and the failure was logged as a
"Chrome connection error".
"""

import pytest

from app.browser import browser_scan
from app.browser.browser_scan import EndpointResult, ScanReport, scan_endpoint, scan_endpoints
from app.browser.endpoints import CHROME, FIREFOX, BrowserEndpoint

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

CHROME_EP = BrowserEndpoint("127.0.0.1", 9223, CHROME)
FIREFOX_EP = BrowserEndpoint("127.0.0.1", 9224, FIREFOX)


class _Tab:
    def __init__(self, tid):
        self.id, self.title, self.url, self.ws_url, self.type = tid, tid, "u", tid, "page"


@pytest.fixture
def scanners(monkeypatch):
    """Replace both protocol scanners; each test declares what its browser does."""
    calls = {}

    def install(kind, result):
        async def fake(endpoint, timeout):
            calls[kind] = endpoint
            if isinstance(result, Exception):
                raise result
            return result
        monkeypatch.setitem(browser_scan.SCANNERS, kind, fake)

    return type("S", (), {"install": staticmethod(install), "calls": calls})


async def test_firefox_is_never_asked_for_json_list(scanners):
    """The bug: the Chrome scanner must not be used for a Firefox endpoint."""
    scanners.install(CHROME, [_Tab("chrome-tab")])
    scanners.install(FIREFOX, [_Tab("ff-tab")])
    await scan_endpoints([FIREFOX_EP])
    assert CHROME not in scanners.calls and scanners.calls[FIREFOX] is FIREFOX_EP


async def test_every_declared_port_is_scanned(scanners):
    scanners.install(CHROME, [_Tab("a")])
    scanners.install(FIREFOX, [_Tab("b"), _Tab("c")])
    report = await scan_endpoints([CHROME_EP, FIREFOX_EP])
    assert [t.id for t in report.tabs] == ["a", "b", "c"]
    assert len(report.results) == 2


async def test_one_dead_browser_does_not_hide_a_working_one(scanners):
    scanners.install(CHROME, [_Tab("a")])
    scanners.install(FIREFOX, ConnectionRefusedError("connection refused"))
    report = await scan_endpoints([CHROME_EP, FIREFOX_EP])
    assert [t.id for t in report.tabs] == ["a"]
    assert report.any_ok and len(report.errors) == 1


async def test_a_failure_is_reported_against_the_real_browser_name(scanners):
    """Never "Chrome connection error" for a Firefox port."""
    scanners.install(FIREFOX, ConnectionRefusedError("connection refused"))
    report = await scan_endpoints([FIREFOX_EP])
    assert report.errors[0].startswith("Firefox 127.0.0.1:9224:")
    assert "Chrome" not in report.errors[0]


async def test_an_unreachable_firefox_is_told_the_exact_flag_to_use(scanners):
    scanners.install(FIREFOX, ConnectionRefusedError("connection refused"))
    report = await scan_endpoints([FIREFOX_EP])
    assert "--start-debugger-server 9224" in report.errors[0]


async def test_a_protocol_level_failure_is_reported_verbatim(scanners):
    """A reachable port that answers wrongly needs its own message, not the flag hint."""
    scanners.install(FIREFOX, ValueError("bad length prefix"))
    report = await scan_endpoints([FIREFOX_EP])
    assert "bad length prefix" in report.errors[0]
    assert "--start-debugger-server" not in report.errors[0]


async def test_an_unknown_kind_is_reported_not_guessed(scanners):
    result = await scan_endpoint(BrowserEndpoint("127.0.0.1", 9225, "safari"))
    assert not result.ok and "unknown browser kind" in result.error


async def test_a_browser_with_no_tabs_is_ok_not_broken(scanners):
    """RULE 4: an empty browser answered; a refused port did not."""
    scanners.install(FIREFOX, [])
    report = await scan_endpoints([FIREFOX_EP])
    assert report.any_ok and report.tabs == [] and report.errors == []


async def test_no_endpoints_scans_nothing_and_says_so():
    report = await scan_endpoints([])
    assert report.tabs == [] and not report.any_ok
    assert report.summary() == "no browser endpoints configured"


async def test_the_summary_names_each_browser_and_its_tab_count(scanners):
    scanners.install(CHROME, [_Tab("a")])
    scanners.install(FIREFOX, ConnectionRefusedError("refused"))
    report = await scan_endpoints([CHROME_EP, FIREFOX_EP])
    assert report.summary() == "Chrome 127.0.0.1:9223 1 tab(s) · Firefox 127.0.0.1:9224 ✗"


async def test_cancellation_is_not_swallowed_as_a_scan_failure(monkeypatch):
    """A cancelled scan must propagate, not be logged as a dead browser (RULE 7)."""
    import asyncio

    async def cancelled(endpoint, timeout):
        raise asyncio.CancelledError()

    monkeypatch.setitem(browser_scan.SCANNERS, FIREFOX, cancelled)
    with pytest.raises(asyncio.CancelledError):
        await scan_endpoint(FIREFOX_EP)


async def test_a_result_with_an_error_is_not_ok():
    assert EndpointResult(FIREFOX_EP, error="boom").ok is False
    assert EndpointResult(FIREFOX_EP, tabs=[]).ok is True
    assert ScanReport([]).errors == []


async def test_the_real_chrome_scanner_reports_a_dead_port():
    """The default CDP adapter, exercised end to end against a closed port."""
    from app.browser.browser_scan import _scan_chrome
    with pytest.raises(ConnectionError):
        await _scan_chrome(BrowserEndpoint("127.0.0.1", 1, CHROME), 1.0)


async def test_the_real_chrome_scanner_returns_parsed_tabs(monkeypatch):
    from app.browser import browser_scan as bs
    from app.browser.cdp import tabs as cdp_tabs
    monkeypatch.setattr(cdp_tabs, "fetch_tabs_sync",
                        lambda host, port, timeout: ([_Tab("t1")], "", []))
    got = await bs._scan_chrome(CHROME_EP, 1.0)
    assert [t.id for t in got] == ["t1"]


async def test_the_real_firefox_scanner_speaks_rdp():
    """The default RDP adapter, against a real socket speaking the real protocol."""
    from app.browser.browser_scan import _scan_firefox
    from tests.rdp_fake_firefox import FakeFirefox
    server = FakeFirefox()
    await server.start()
    try:
        endpoint = BrowserEndpoint("127.0.0.1", server.port, FIREFOX)
        tabs = await _scan_firefox(endpoint, 3.0)
        assert [t.url for t in tabs] == ["https://arena.ai/chat"]
    finally:
        await server.stop()
