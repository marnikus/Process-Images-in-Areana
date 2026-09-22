"""One listing seam for every browser — both poolable at the same time (2026-09-21).

`endpoints.list_targets(browser_id, host, port)` is what the pool, the URL
reconciler and the panel ask; it detects which protocol the endpoint speaks
(CDP answers `GET /json/version`, Firefox's Remote Agent answers `POST /session`)
and returns the same `TargetRef` rows either way, each carrying its browser id.

RED at `bce5a01`: `app.browser.endpoints` did not exist.
"""

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.browser import browsers as br
from app.browser import endpoints
from tests.fakes.rdp_stub_server import RdpStubServer

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
    """A Firefox DevTools server — the stealth channel (round 8)."""
    server = RdpStubServer()
    try:
        yield server
    finally:
        server.close()


@pytest.fixture
def bidi_only():
    """A Firefox that only speaks WebDriver BiDi (a `--remote-debugging-port` launch)."""
    from tests.test_bidi import FakeRemoteAgent
    agent = FakeRemoteAgent()
    try:
        yield agent
    finally:
        agent.close()


# ---- protocol detection ----------------------------------------------------


def test_detect_protocol_reads_the_endpoint(chrome, firefox, bidi_only):
    assert endpoints.detect_protocol("127.0.0.1", chrome.port, timeout=1.0) == "cdp"
    assert endpoints.detect_protocol("127.0.0.1", firefox.port, timeout=1.0) == "rdp"
    assert endpoints.detect_protocol("127.0.0.1", bidi_only.port, timeout=1.0) == "bidi"
    assert endpoints.detect_protocol("127.0.0.1", _free_port(), timeout=0.5) == ""


def test_detect_prefers_cdp_then_rdp_then_bidi(chrome, firefox, bidi_only):
    """One probe order for every browser: CDP (ESR), RDP (DevTools), BiDi (Remote Agent)."""
    assert endpoints.detect_protocol("127.0.0.1", chrome.port) == "cdp"
    assert endpoints.detect_protocol("127.0.0.1", firefox.port) == "rdp"
    assert endpoints.detect_protocol("127.0.0.1", bidi_only.port) == "bidi", \
        "a --remote-debugging-port Firefox is still reachable — and the panel says it is flagged"
    assert endpoints.detect_protocol("127.0.0.1", _free_port()) == ""


# ---- listing ---------------------------------------------------------------


def test_chrome_targets_carry_the_browser_and_the_protocol(chrome):
    targets, err = endpoints.list_targets("chrome", "127.0.0.1", chrome.port, timeout=2.0)
    assert err == ""
    assert [t.id for t in targets] == ["AAA111", "BBB222"]
    assert all(t.browser == "chrome" and t.protocol == "cdp" for t in targets)
    assert targets[0].title == "Arena A"
    assert targets[0].ws_url.endswith("/devtools/page/AAA111")
    assert targets[0].port == chrome.port


def test_firefox_targets_come_from_the_rdp_tab_list(firefox):
    targets, err = endpoints.list_targets("firefox", "127.0.0.1", firefox.port, timeout=2.0)
    assert err == ""
    assert [t.id for t in targets] == ["ctx-3", "ctx-4"]
    assert all(t.browser == "firefox" and t.protocol == "rdp" for t in targets)
    assert targets[0].url == "https://arena.ai/c/1"
    assert targets[0].ws_url == f"rdp://127.0.0.1:{firefox.port}/ctx-3", \
        "RDP has one socket for the whole browser; the tab gets a stable handle"


def test_both_browsers_list_at_once_so_both_can_be_pooled(chrome, firefox):
    """The acceptance: Chrome and Firefox connectable in the same pass."""
    chrome_targets, _ = endpoints.list_targets("chrome", "127.0.0.1", chrome.port)
    ff_targets, _ = endpoints.list_targets("firefox", "127.0.0.1", firefox.port)
    both = chrome_targets + ff_targets
    assert {t.browser for t in both} == {"chrome", "firefox"}
    assert len(both) == 4, "2 Chrome tabs + the 2 Firefox tabs, in one pass"
    assert len({(t.browser, t.id) for t in both}) == 4, "identities never collide across browsers"
    assert {t.protocol for t in both} == {"cdp", "rdp"}


def test_evaluate_and_click_are_dispatched_by_protocol(chrome, firefox, bidi_only):
    """One seam, three protocols: the operation runs, or the reason names the protocol."""
    ff, _ = endpoints.list_targets("firefox", "127.0.0.1", firefox.port, timeout=2.0)
    assert endpoints.evaluate(ff[0], "JSON.stringify(document.title)", 2.0) == ('"Arena"', ""), \
        "a JSON string, like the CDP path answers"
    assert endpoints.click(ff[0], "#send", 2.0) == (True, ""), "the click-only action runs over RDP"
    bidi_ref = endpoints.TargetRef(id="ctx-a", title="Arena", url="https://arena.ai/c/1",
                                   ws_url="ws://127.0.0.1/session", browser="firefox",
                                   port=bidi_only.port, protocol="bidi")
    value, err = endpoints.evaluate(bidi_ref, "1+1", 2.0)
    assert err == "" and json.loads(value) == "ran:1+1", \
        "BiDi evaluates too — it just has no click primitive"
    ok, err = endpoints.click(bidi_ref, "#send", 2.0)
    assert ok is False and "BIDI" in err.upper(), "a missing operation is named, never a silent timeout"
    cdp_ref = endpoints.TargetRef(id="AAA111", title="Arena", url="https://arena.ai/c/1",
                                  ws_url="ws://127.0.0.1/devtools/page/AAA111",
                                  port=chrome.port, protocol="cdp")
    ok, err = endpoints.click(cdp_ref, "#send", 1.0)
    assert ok is False and "CDP" in err.upper(), \
        "Chrome clicks run through the connected CDP client, not this listing seam"


def test_an_rdp_firefox_is_not_poolable_through_a_tab_socket(chrome, firefox):
    """connect_tab must refuse an rdp:// handle by name — there is no per-tab socket."""
    from app.ui.panels.browser_tabs import connect_refusal
    assert connect_refusal(f"rdp://127.0.0.1:{firefox.port}/ctx-3") != ""
    assert connect_refusal(f"ws://127.0.0.1:{chrome.port}/devtools/page/AAA111") == ""


# ---- honesty ---------------------------------------------------------------


def test_an_unknown_browser_is_refused_by_name():
    targets, err = endpoints.list_targets("netscape", "127.0.0.1", 9222)
    assert targets == []
    assert "netscape" in err and "unknown browser" in err


def test_a_dead_endpoint_reports_why_and_returns_nothing():
    targets, err = endpoints.list_targets("chrome", "127.0.0.1", _free_port(), timeout=0.5)
    assert targets == [] and err


def test_a_bidi_firefox_is_listed_too_with_its_session_socket(bidi_only):
    """The detected fallback stays reachable — and the panel says what it costs."""
    targets, err = endpoints.list_targets("firefox", "127.0.0.1", bidi_only.port, timeout=2.0)
    assert err == ""
    assert [t.id for t in targets] == ["ctx-a", "ctx-b", "ctx-b-1"]
    assert all(t.protocol == "bidi" and t.browser == "firefox" for t in targets)
    assert targets[0].ws_url == f"ws://127.0.0.1:{bidi_only.port}/session"


def test_an_unusable_port_is_refused_with_the_value_it_got(chrome):
    targets, err = endpoints.list_targets("chrome", "127.0.0.1", "9222x")
    assert targets == [] and "invalid port" in err and "9222x" in err


def test_enabled_targets_asks_every_enabled_browser_at_its_own_port(chrome, firefox, bidi_only):
    """The multi-browser call the reconciler makes: one browser down never hides another."""
    settings = {"chrome": {"enabled": True, "port": chrome.port},
                "firefox": {"enabled": False, "port": firefox.port},
                "edge": {"enabled": False, "port": 9225}}
    refs, errors = endpoints.enabled_targets(settings, "127.0.0.1", timeout=2.0)
    assert [t.browser for t in refs] == ["chrome", "chrome"] and errors == []
    settings["firefox"] = {"enabled": True, "port": firefox.port}
    refs, errors = endpoints.enabled_targets(settings, "127.0.0.1", timeout=2.0)
    assert {t.browser for t in refs} == {"chrome", "firefox"}, "both browsers, one pass"
    assert errors == []
    settings["firefox"] = {"enabled": True, "port": _free_port()}
    refs, errors = endpoints.enabled_targets(settings, "127.0.0.1", timeout=0.5)
    assert [t.browser for t in refs] == ["chrome", "chrome"], "a down Firefox hides nothing"
    assert errors and "firefox" in errors[0] and "start-debugger-server" in errors[0], \
        "and the reason names the flag that opens its channel"


def test_evaluate_on_a_cdp_ref_is_named_not_timed_out(chrome):
    ref = endpoints.TargetRef(id="AAA111", title="Arena", url="https://arena.ai/c/1",
                              ws_url="ws://127.0.0.1/devtools/page/AAA111",
                              port=chrome.port, protocol="cdp")
    value, err = endpoints.evaluate(ref, "1+1", 1.0)
    assert value is None and "CDP" in err.upper()


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
    pool.add_page(PageInfo(tab_id="ctx-a", ws_url="ws://127.0.0.1:9223/session",
                           title="Arena", url="https://arena.ai/c/1"))
    row = pool.status_snapshot()["pages"][0]
    assert row["browser"] == "firefox" and row["tab_id"] == "ctx-a"
    chrome, _ = PagePool(), None
    chrome.add_page(PageInfo(tab_id="AAA111", ws_url="ws://127.0.0.1:9222/devtools/page/AAA111"))
    assert chrome.status_snapshot()["pages"][0]["browser"] == "chrome"
