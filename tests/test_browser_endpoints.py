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
    assert targets[0].ws_url == f"rdp://127.0.0.1:{firefox.port}#11", "per-tab handle, not the bare endpoint"


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
    pool.add_page(PageInfo(tab_id="tab-1", ws_url="rdp://127.0.0.1:9223#tab-1",
                           title="Arena", url="https://arena.ai/c/1"))
    row = pool.status_snapshot()["pages"][0]
    assert row["browser"] == "firefox" and row["tab_id"] == "tab-1"
    chrome, _ = PagePool(), None
    chrome.add_page(PageInfo(tab_id="AAA111", ws_url="ws://127.0.0.1:9222/devtools/page/AAA111"))
    assert chrome.status_snapshot()["pages"][0]["browser"] == "chrome"


# ---- one connection per endpoint per cycle (2026-09-22) -----------------------
#
# Every TCP connection to the debugger server raises Firefox's "Incoming
# Connection" dialog. Re-detecting the protocol on every cycle (a CDP probe
# plus an RDP probe) plus a fresh listing socket therefore re-prompts every
# few seconds. `list_targets` now goes straight to the registry's protocol on
# a pooled socket, measures only when that fails, and remembers the answer:
# positive for minutes, negative for seconds (a restarted browser must come
# back at once, and a dead port probes silently — nothing listens to prompt).
# RED: cold listing probes CDP first and re-detects every call.


def _counting(monkeypatch, module, name):
    calls = []
    real = getattr(module, name)

    def counted(*args, **kwargs):
        calls.append((args, kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, counted)
    return calls


def test_a_cold_firefox_listing_skips_the_cdp_probe(firefox, monkeypatch):
    http_calls = _counting(monkeypatch, endpoints, "_get_json")
    detects = _counting(monkeypatch, endpoints, "detect_protocol")
    targets, err = endpoints.list_targets("firefox", "127.0.0.1", firefox.port, timeout=2.0)
    assert err == "" and len(targets) == 2
    assert http_calls == [], "no HTTP knock on a debugger-server port"
    assert detects == [], "the registry's protocol is tried first, not measured"


def test_a_second_listing_reuses_the_answer_and_the_socket(firefox, monkeypatch):
    detects = _counting(monkeypatch, endpoints, "detect_protocol")
    first, err1 = endpoints.list_targets("firefox", "127.0.0.1", firefox.port, timeout=2.0)
    second, err2 = endpoints.list_targets("firefox", "127.0.0.1", firefox.port, timeout=2.0)
    assert err1 == err2 == "" and len(first) == len(second) == 2
    assert detects == [] and firefox.connections == 1
    firefox.close()
    targets, err = endpoints.list_targets("firefox", "127.0.0.1", firefox.port, timeout=1.0)
    assert targets == [] and "not reachable" in err
    assert len(detects) == 1, "only a failure re-measures"


def test_a_cdp_only_port_behind_a_firefox_entry_falls_back_and_is_remembered(chrome, monkeypatch):
    from app.browser import rdp
    monkeypatch.setattr(rdp, "APPROVAL_WAIT", 0.5)
    real_list_tabs = rdp.list_tabs
    rdp_calls = []

    def counted_list(target, timeout=3.0):
        rdp_calls.append(target)
        return real_list_tabs(target, timeout)

    monkeypatch.setattr(rdp, "list_tabs", counted_list)
    detects = _counting(monkeypatch, endpoints, "detect_protocol")
    targets, err = endpoints.list_targets("firefox", "127.0.0.1", chrome.port, timeout=2.0)
    assert err == "" and len(targets) == 2, "an ESR-style endpoint still lists"
    assert len(detects) == 1 and len(rdp_calls) == 1
    targets, err = endpoints.list_targets("firefox", "127.0.0.1", chrome.port, timeout=2.0)
    assert err == "" and len(targets) == 2
    assert len(rdp_calls) == 1, "the fallback answer sticks — no RDP knock per cycle"


def test_a_dead_port_reprobes_within_seconds_not_cycles(monkeypatch):
    port = _free_port()
    detects = _counting(monkeypatch, endpoints, "detect_protocol")
    _, err1 = endpoints.list_targets("firefox", "127.0.0.1", port, timeout=0.5)
    _, err2 = endpoints.list_targets("firefox", "127.0.0.1", port, timeout=0.5)
    assert "not reachable" in err1 and "not reachable" in err2
    assert len(detects) == 1, "one probe, then quiet — nothing listens to prompt"


def test_a_dead_port_is_forgiven_once_its_short_memory_expires(monkeypatch):
    port = _free_port()
    monkeypatch.setattr(endpoints, "_NEG_TTL", 0.0)  # the memory expires instantly
    detects = _counting(monkeypatch, endpoints, "detect_protocol")
    _, err1 = endpoints.list_targets("firefox", "127.0.0.1", port, timeout=0.5)
    _, err2 = endpoints.list_targets("firefox", "127.0.0.1", port, timeout=0.5)
    assert "not reachable" in err1 and "not reachable" in err2
    assert len(detects) == 2, "an expired memory re-measures"


def test_an_empty_but_answering_endpoint_stays_trusted(monkeypatch):
    from app.browser import rdp
    monkeypatch.setattr(rdp, "APPROVAL_WAIT", 0.5)
    empty = FakeChrome(tabs=[])
    try:
        rdp_calls = _counting(monkeypatch, rdp, "list_tabs")
        detects = _counting(monkeypatch, endpoints, "detect_protocol")
        first, err1 = endpoints.list_targets("firefox", "127.0.0.1", empty.port, timeout=2.0)
        second, err2 = endpoints.list_targets("firefox", "127.0.0.1", empty.port, timeout=2.0)
        assert first == second == [] and err1 == err2 != ""
        assert "not reachable" not in err2, "an answering endpoint is never buried"
        assert len(rdp_calls) == 1, "the cache directs CDP — no RDP knock per cycle"
        assert len(detects) == 2, "an empty listing is still a failure, so it re-measures"
    finally:
        empty.close()


def test_a_confirmed_failure_reports_the_attempt_not_a_second_guess(firefox, monkeypatch):
    first, err1 = endpoints.list_targets("firefox", "127.0.0.1", firefox.port, timeout=2.0)
    assert err1 == "" and len(first) == 2
    firefox.kill_clients()  # the pooled socket dies; the server lives on
    seen_before, conns_before = len(firefox.seen), firefox.connections
    targets, err = endpoints.list_targets("firefox", "127.0.0.1", firefox.port, timeout=2.0)
    assert targets == [] and err != "" and "not reachable" not in err
    assert firefox.connections == conns_before + 2, "only the HTTP knock + the re-probe redial"
    assert len(firefox.seen) == seen_before, "no second listing attempt"
