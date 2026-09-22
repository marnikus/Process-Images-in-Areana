"""Handles, attach and protocol routing — the fix for "cannot connect Firefox" (round 9).

The owner's log (`CDP error: URLError http://localhost:9224/json/list: Not Found`, every
reconcile pass) had one cause: the execution client asked every endpoint for Chrome's HTTP
tab list. These tests pin the opposite contract:

* a **handle** names its own endpoint and channel — `ws://…/devtools/page/<id>` (CDP),
  `rdp://host:port/ctx-N` (Firefox DevTools), `ws://host:port/session#<ctx>` (BiDi);
* an RDP endpoint is **never** asked for `/json/list` (the fake server is byte-recorded);
* attach verifies the tab exists and says so by name when it does not;
* `evaluate` over RDP keeps B8's `last_error`/`last_error_kind` contract;
* the operations the DevTools protocol cannot do refuse **by name** (never silently).

RED at `741b771`: `app.browser.attached` did not exist.
"""

import socket

import pytest

from app.browser import attached
from app.browser.rdp.wire import PROTOCOL as RDP_PROTOCOL
from tests.fakes.rdp_stub_server import RdpStubServer

pytestmark = pytest.mark.unit

RDP_HANDLE = "rdp://127.0.0.1:{port}/ctx-3"
CDP_HANDLE = "ws://127.0.0.1:9223/devtools/page/AAA111"
BIDI_HANDLE = "ws://127.0.0.1:9224/session#ctx-a"


@pytest.fixture
def stub():
    server = RdpStubServer()
    try:
        yield server
    finally:
        server.close()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── the handle grammar (one parser for every channel) ──


def test_an_rdp_handle_names_its_endpoint_and_its_tab(stub):
    handle = attached.parse_handle(RDP_HANDLE.format(port=stub.port))
    assert handle.channel == RDP_PROTOCOL
    assert (handle.host, handle.port) == ("127.0.0.1", stub.port)
    assert handle.tab_id == "ctx-3"
    assert attached.is_remote(handle) is True


def test_a_cdp_handle_is_read_from_the_devtools_page_path():
    handle = attached.parse_handle(CDP_HANDLE)
    assert handle.channel == "cdp" and handle.tab_id == "AAA111"
    assert (handle.host, handle.port) == ("127.0.0.1", 9223)
    assert attached.is_remote(handle) is False


def test_a_bidi_handle_carries_its_context_not_just_the_session_socket():
    """`ws://host:port/session` alone is the SAME url for every context (round-8 gap)."""
    handle = attached.parse_handle(BIDI_HANDLE)
    assert handle.channel == "bidi" and handle.tab_id == "ctx-a"
    bare = attached.parse_handle("ws://127.0.0.1:9224/session")
    assert bare.channel == "bidi" and bare.tab_id == "", "a contextless session socket says so"
    assert attached.is_remote(bare) is True


def test_a_handle_falls_back_to_the_pool_endpoint_and_an_empty_url_is_still_valid():
    handle = attached.parse_handle("", "10.0.0.5", 9333)
    assert (handle.channel, handle.host, handle.port, handle.tab_id) == ("cdp", "10.0.0.5", 9333, "")
    assert handle.ws_url == ""
    endpoint = attached.endpoint_handle("127.0.0.1", 9224, RDP_PROTOCOL, "firefox")
    assert (endpoint.channel, endpoint.port, endpoint.tab_id, endpoint.browser) == \
        (RDP_PROTOCOL, 9224, "", "firefox")
    assert endpoint.ws_url == "rdp://127.0.0.1:9224/", "an endpoint handle lists, it does not attach"


# ── attach (the browser keeps running; we only open its socket) ──


def test_attach_verifies_the_tab_exists_over_the_rdp_socket(stub):
    handle = attached.parse_handle(RDP_HANDLE.format(port=stub.port))
    ok, reason = attached.attach(handle, 3.0)
    assert (ok, reason) == (True, "")
    assert stub.connections == 1, "one attach = one socket, and it is closed again immediately"


def test_attach_names_an_unknown_tab_and_says_what_is_open(stub):
    handle = attached.parse_handle(f"rdp://127.0.0.1:{stub.port}/ctx-99")
    ok, reason = attached.attach(handle, 3.0)
    assert ok is False
    assert "ctx-99" in reason and "ctx-3" in reason, f"the reason lists what Firefox has: {reason}"


def test_attach_to_a_dead_port_is_a_reason_not_an_exception():
    handle = attached.parse_handle(f"rdp://127.0.0.1:{_free_port()}/ctx-3")
    ok, reason = attached.attach(handle, 0.4)
    assert ok is False and reason


def test_a_bidi_session_socket_cannot_be_attached_by_name():
    ok, reason = attached.attach(attached.parse_handle("ws://127.0.0.1:9224/session"), 0.3)
    assert ok is False
    assert "BIDI" in reason.upper() and "session" in reason.lower(), reason


# ── listing and evaluate over the attach channel ──


def test_list_rows_reads_the_rdp_tab_list_with_its_browser_id(stub):
    handle = attached.endpoint_handle("127.0.0.1", stub.port, RDP_PROTOCOL, "firefox")
    rows, err = attached.list_rows(handle, 3.0)
    assert err == ""
    assert [r.id for r in rows] == ["ctx-3", "ctx-4"]
    assert all(r.browser == "firefox" and r.protocol == RDP_PROTOCOL for r in rows)
    assert rows[0].ws_url == f"rdp://127.0.0.1:{stub.port}/ctx-3"


def test_the_rdp_endpoint_is_never_asked_for_chrome_http(stub):
    """The regression guard for the owner's log: no `GET /json/list` on a DevTools socket."""
    handle = attached.endpoint_handle("127.0.0.1", stub.port, RDP_PROTOCOL, "firefox")
    attached.list_rows(handle, 3.0)
    attached.diagnose(handle, 3.0)
    attached.evaluate(attached.parse_handle(RDP_HANDLE.format(port=stub.port)), "1+1", 3.0)
    seen = stub.raw_text()
    assert "GET " not in seen and "/json" not in seen, f"the DevTools socket saw HTTP: {seen[:200]!r}"


def test_evaluate_returns_the_value_and_keeps_the_error_contract(stub):
    handle = attached.parse_handle(RDP_HANDLE.format(port=stub.port))
    answer = attached.evaluate(handle, "JSON.stringify(document.title)", 3.0)
    assert (answer.value, answer.error, answer.kind) == ("Arena", "", "")
    failed = attached.evaluate(handle, "boom()", 3.0)
    assert failed.value is None and "boom" in failed.error and failed.kind == "js", \
        "a page exception is the page's answer (kind 'js'), not a transport failure"


def test_evaluate_on_a_dead_endpoint_is_a_transport_failure():
    handle = attached.parse_handle(f"rdp://127.0.0.1:{_free_port()}/ctx-3")
    answer = attached.evaluate(handle, "1+1", 0.4)
    assert answer.value is None and answer.kind in ("transport", "timeout") and answer.error


def test_diagnose_reports_the_rdp_session_facts(stub):
    handle = attached.endpoint_handle("127.0.0.1", stub.port, RDP_PROTOCOL, "firefox")
    diag = attached.diagnose(handle, 3.0)
    assert diag["summary"].startswith("✅")
    assert "RDP" in diag["summary"] and str(stub.port) in diag["summary"]
    assert diag["checks"][0]["port_open"] is True and diag["checks"][0]["list_count"] == 2
    assert [t["id"] for t in diag["tabs"]] == ["ctx-3", "ctx-4"], "the shape the panel already renders"


# ── capability refusals (D-4: named, never silent) ──


def test_every_cdp_only_operation_refuses_by_name_on_an_rdp_handle(stub):
    handle = attached.parse_handle(RDP_HANDLE.format(port=stub.port))
    for op in ("DOM.getDocument", "DOM.setFileInputFiles", "Page.captureScreenshot", "Input.dispatchMouseEvent"):
        reason = attached.refusal(handle, op)
        assert op in reason and "CDP" in reason.upper(), reason
        assert handle.channel.upper() in reason.upper(), "the reason names the channel it is on"


def test_a_cdp_handle_has_nothing_to_refuse():
    assert attached.refusal(attached.parse_handle(CDP_HANDLE), "DOM.getDocument") == ""
    assert attached.block(None, "DOM.getDocument") == "", "a plain CDP transport is never blocked"


def test_block_records_the_reason_on_the_transport_it_refuses():
    class Fake:
        last_error = ""
        last_error_kind = ""
        _attachment = attached.parse_handle(RDP_HANDLE.format(port=9224))

    fake = Fake()
    reason = attached.block(fake, "DOM.setFileInputFiles")
    assert "DOM.setFileInputFiles" in reason
    assert fake.last_error == reason and fake.last_error_kind == "capability", \
        "a refused operation is rememberable like any other failure (B8 contract)"
    assert attached.block(fake, "Runtime.evaluate") == "", "evaluate is the one op every channel has"


# ── honest classification of the wrong Firefox channel (D-7) ──


def test_a_firefox_answering_http_but_not_rdp_is_named_as_the_flagged_remote_agent():
    """Exactly the owner's log: 9224 answers HTTP, `/json/list` is gone."""
    from tests.test_browser_endpoints import FakeChrome

    from app.browser import browsers

    http_only = FakeChrome(tabs=[], version=False)     # /json/version → 404
    try:
        handle = attached.endpoint_handle("127.0.0.1", http_only.port, RDP_PROTOCOL, "firefox")
        reason = attached.explain_failure(handle, browsers.profile_of("firefox"), 0.5)
        assert "--start-debugger-server" in reason, reason
        assert "remote-debugging-port" in reason, "the flag that caused it is named"
        assert "webdriver" in reason, "and why it must not be used"
        assert "Fix:" in reason
    finally:
        http_only.close()


def test_a_dead_firefox_port_is_told_to_be_started_with_the_devtools_flag():
    from app.browser import browsers

    handle = attached.endpoint_handle("127.0.0.1", _free_port(), RDP_PROTOCOL, "firefox")
    reason = attached.explain_failure(handle, browsers.profile_of("firefox"), 0.3)
    assert "--start-debugger-server" in reason and "not reachable" in reason
    chrome_reason = attached.explain_failure(
        attached.endpoint_handle("127.0.0.1", _free_port(), "cdp", "chrome"),
        browsers.profile_of("chrome"), 0.3)
    assert "--remote-debugging-port" in chrome_reason, "each browser is told its own flag"


def test_a_chrome_answering_like_a_devtools_socket_is_classified_not_guessed():
    from app.browser import browsers

    stub = RdpStubServer()
    try:
        handle = attached.endpoint_handle("127.0.0.1", stub.port, "cdp", "chrome")
        reason = attached.explain_failure(handle, browsers.profile_of("chrome"), 0.4)
        assert "DevTools" in reason and "RDP" in reason.upper(), reason
        assert "not reachable" not in reason.lower(), "it IS reachable — as another channel"
    finally:
        stub.close()


# ── honest diagnose per channel (D-7) ──


def test_diagnose_names_the_session_of_a_devtools_socket(stub):
    """The panel's Diagnose button reads this — the greeting facts, not a guess."""
    handle = attached.endpoint_handle("127.0.0.1", stub.port, RDP_PROTOCOL, "firefox")
    diag = attached.diagnose(handle, 3.0)
    assert diag["summary"].startswith("✅") and "browser" in diag["summary"], diag["summary"]
    assert "2 tab" in diag["summary"]
