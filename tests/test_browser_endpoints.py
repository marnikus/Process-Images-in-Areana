"""One listing seam for every browser — both poolable at the same time (2026-09-21).

`endpoints.list_targets(browser_id, host, port)` is what the pool, the URL
reconciler and the panel ask; it detects which protocol the endpoint speaks
(CDP answers `GET /json/version`, Firefox's debugger server answers the RDP
greeting on plain TCP) and returns the same `TargetRef` rows either way, each
carrying its browser id.

RED at `bce5a01`: `app.browser.endpoints` did not exist.
Stealth fix 2026-09-22: the Firefox fixture is the RDP `FakeDebuggerServer`.
"""

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.browser import browsers as br
from app.browser import endpoints
from tests.test_rdp import FakeDebuggerServer

pytestmark = pytest.mark.unit

CDP_TABS = [
    {"id": "AAA111", "title": "Arena A", "url": "https://arena.ai/c/1", "type": "page",
     "webSocketDebuggerUrl": "ws://127.0.0.1:{port}/devtools/page/AAA111"},
    {"id": "BBB222", "title": "Arena B", "url": "https://arena.ai/c/2", "type": "page",
     "webSocketDebuggerUrl": "ws://127.0.0.1:{port}/devtools/page/BBB222"},
]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeChrome:
    """The CDP HTTP surface the app lists tabs from."""

    def __init__(self, tabs=CDP_TABS, version=True):
        self.tabs, self.version = tabs, version
        self.port = _free_port()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path.startswith("/json/version"):
                    if not fake.version:
                        self.send_error(404)
                        return
                    self._json({"Browser": "Chrome/140", "webSocketDebuggerUrl":
                                f"ws://127.0.0.1:{fake.port}/devtools/browser/x"})
                elif self.path.startswith("/json/list"):
                    self._json([{**t, "webSocketDebuggerUrl":
                                 t["webSocketDebuggerUrl"].format(port=fake.port)} for t in fake.tabs])
                else:
                    self.send_error(404)

            def _json(self, payload):
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()

    def close(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


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


# ---- protocol detection ----------------------------------------------------


def test_detect_protocol_reads_the_endpoint(chrome, firefox):
    assert endpoints.detect_protocol("127.0.0.1", chrome.port, timeout=1.0) == "cdp"
    assert endpoints.detect_protocol("127.0.0.1", firefox.port, timeout=1.0) == "rdp"
    assert endpoints.detect_protocol("127.0.0.1", _free_port(), timeout=0.5) == ""


def test_detect_prefers_cdp_when_a_browser_answers_both(firefox):
    """An ESR Firefox with CDP enabled answers /json/version: CDP wins (full matrix)."""
    cdp_like = FakeChrome(tabs=[])
    both = _free_port()
    assert endpoints.detect_protocol("127.0.0.1", cdp_like.port) == "cdp"
    cdp_like.close()
    assert endpoints.detect_protocol("127.0.0.1", firefox.port) == "rdp"
    assert endpoints.detect_protocol("127.0.0.1", both) == ""


# ---- listing ---------------------------------------------------------------


def test_chrome_targets_carry_the_browser_and_the_protocol(chrome):
    targets, err = endpoints.list_targets("chrome", "127.0.0.1", chrome.port, timeout=2.0)
    assert err == ""
    assert [t.id for t in targets] == ["AAA111", "BBB222"]
    assert all(t.browser == "chrome" and t.protocol == "cdp" for t in targets)
    assert targets[0].title == "Arena A"
    assert targets[0].ws_url.endswith("/devtools/page/AAA111")
    assert targets[0].port == chrome.port


def test_firefox_targets_come_from_the_rdp_tree(firefox):
    targets, err = endpoints.list_targets("firefox", "127.0.0.1", firefox.port, timeout=2.0)
    assert err == ""
    assert [t.id for t in targets] == ["11", "12"], "numeric browserIds, stringified"
    assert all(t.browser == "firefox" and t.protocol == "rdp" for t in targets)
    assert targets[0].url == "https://arena.ai/c/1"
    assert targets[0].ws_url == f"rdp://127.0.0.1:{firefox.port}"


def test_both_browsers_list_at_once_so_both_can_be_pooled(chrome, firefox):
    """The acceptance: Chrome and Firefox connectable in the same pass."""
    chrome_targets, _ = endpoints.list_targets("chrome", "127.0.0.1", chrome.port)
    ff_targets, _ = endpoints.list_targets("firefox", "127.0.0.1", firefox.port)
    both = chrome_targets + ff_targets
    assert {t.browser for t in both} == {"chrome", "firefox"}
    assert len(both) == 4, "2 Chrome tabs + the 2 Firefox tabs, in one pass"
    assert len({(t.browser, t.id) for t in both}) == 4, "identities never collide across browsers"


# ---- honesty ---------------------------------------------------------------


def test_an_unknown_browser_is_refused_by_name():
    targets, err = endpoints.list_targets("netscape", "127.0.0.1", 9222)
    assert targets == []
    assert "netscape" in err and "unknown browser" in err


def test_a_dead_endpoint_reports_why_and_returns_nothing():
    targets, err = endpoints.list_targets("chrome", "127.0.0.1", _free_port(), timeout=0.5)
    assert targets == [] and err


def test_list_targets_carries_the_resolved_endpoint_port(chrome):
    """The pool needs the port back so it knows which endpoint a page belongs to."""
    port = br.resolve_port(9999, br.profile_of("chrome"))
    assert port == 9999
    targets, _ = endpoints.list_targets("chrome", "127.0.0.1", chrome.port)
    assert {t.port for t in targets} == {chrome.port}


def test_pool_rows_name_the_browser_of_their_endpoint():
    """Two browsers pooled side by side must tell their rows apart (D-3)."""
    from app.browser.page_pool import PagePool
    from app.browser.page_status import PageInfo

    assert PageInfo().browser == "", "a page alone does not know its browser — the pool does"
    pool = PagePool()
    pool._browser = "firefox"   # what apply_cdp_config sets when Firefox is the active browser
    pool.add_page(PageInfo(tab_id="tab-1", ws_url="rdp://127.0.0.1:9223",
                           title="Arena", url="https://arena.ai/c/1"))
    row = pool.status_snapshot()["pages"][0]
    assert row["browser"] == "firefox" and row["tab_id"] == "tab-1"
    chrome, _ = PagePool(), None
    chrome.add_page(PageInfo(tab_id="AAA111", ws_url="ws://127.0.0.1:9222/devtools/page/AAA111"))
    assert chrome.status_snapshot()["pages"][0]["browser"] == "chrome"
