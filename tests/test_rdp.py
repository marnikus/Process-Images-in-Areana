"""Firefox DevTools RDP — stealth attach to a running Firefox (2026-09-22).

RDP speaks `length:JSON` over plain TCP (`--start-debugger-server`), loads no
Marionette and creates no WebDriver session, so `navigator.webdriver` stays
`false`. The client's world per operation: greeting → `listTabs` → `getTarget`
→ `evaluateJSAsync` (ack + `evaluationResult` event) / `navigateTo`.

This suite runs a real fake debugger server over TCP — length-prefixed frames,
an interleaved event before replies, the two-packet eval — so the client is
exercised against the transport, not against a stub.

RED at `464185a`: `app.browser.rdp` did not exist.
"""

import json
import socket
import socketserver
import threading

import pytest

from app.browser import rdp

pytestmark = pytest.mark.unit

GREETING = {"from": "root", "applicationType": "browser",
            "testConnectionPrefix": "server1.conn1."}
TABS = [
    {"actor": "server1.conn1.tabDescriptor1", "browserId": 11,
     "browsingContextID": 101, "selected": True,
     "title": "Arena A", "url": "https://arena.ai/c/1"},
    {"actor": "server1.conn1.tabDescriptor2", "browserId": 12,
     "browsingContextID": 102, "selected": False,
     "title": "Arena B", "url": "https://arena.ai/c/2"},
]


def target(port: int) -> "rdp.Endpoint":
    """The fake server as the client sees it."""
    return rdp.Endpoint("127.0.0.1", port)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _send_frame(conn, payload: dict) -> None:
    raw = json.dumps(payload).encode("utf-8")
    conn.sendall(str(len(raw)).encode() + b":" + raw)


def _recv_frame(fp):
    """One `length:JSON` frame; ConnectionError on a closed socket."""
    prefix = b""
    while True:
        digit = fp.read(1)
        if not digit:
            raise ConnectionError("socket closed")
        if digit == b":":
            break
        prefix += digit
    return json.loads(fp.read(int(prefix)).decode("utf-8"))


class FakeDebuggerServer:
    """TCP `length:JSON` like Firefox's `--start-debugger-server` endpoint."""

    def __init__(self, tabs=None, greeting=None):
        self.tabs = TABS if tabs is None else tabs
        self.greeting = GREETING if greeting is None else greeting
        self.seen = []
        self._result_no = 0
        agent = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                _send_frame(self.request, agent.greeting)
                fp = self.request.makefile("rb")
                try:
                    while True:
                        msg = _recv_frame(fp)
                        agent.seen.append(msg)
                        for reply in agent.replies(msg):
                            _send_frame(self.request, reply)
                except Exception:
                    return

        self._server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._server.agent = self
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()

    def replies(self, msg):
        """Scripted packets for one request, events interleaved like Firefox."""
        to, rtype = msg.get("to", ""), msg.get("type", "")
        if to == "root" and rtype == "listTabs":
            first = self.tabs[0] if self.tabs else {}
            event = {"from": first.get("actor", ""), "type": "tabNavigated",
                     "state": "stop", "url": first.get("url", ""),
                     "title": first.get("title", "")}
            return [event, {"from": "root", "tabs": self.tabs}]
        if rtype == "getTarget":
            for tab in self.tabs:
                if tab.get("actor") == to:
                    navigated = {"from": to, "type": "tabNavigated",
                                 "state": "stop", "url": tab.get("url", ""),
                                 "title": tab.get("title", "")}
                    if tab.get("broken"):
                        return [navigated, {"from": to, "frame": {}}]
                    return [navigated, {"from": to, "frame": {
                        "actor": f"{to}/target1", "consoleActor": f"{to}/console1"}}]
            return [{"from": to, "error": "noSuchActor"}]
        if rtype == "evaluateJSAsync":
            return self._eval_replies(to, msg.get("text", ""))
        if rtype == "navigateTo":
            return [{"from": to}]
        if rtype == "substring":
            return [{"from": to, "substring": "hello world"}]
        return [{"from": to, "error": "unknownMethod",
                 "message": f"{rtype} is not implemented"}]

    def _eval_replies(self, console: str, text: str):
        """The two-packet eval: ack, one console event, then the result event."""
        self._result_no += 1
        rid = f"r{self._result_no}"
        ack = {"from": console, "resultID": rid}
        noise = {"from": console, "type": "consoleAPICall", "message": "hi"}
        if "NAVIGATE" in text:
            gone = {"from": console, "type": "tabNavigated",
                    "state": "start", "url": "https://else.example/"}
            return [ack, gone]
        if "STRAY" in text:
            stray = {"from": "someone.else", "type": "evaluationResult",
                     "resultID": rid, "result": "stray"}
            stale = {"from": console, "type": "evaluationResult",
                     "resultID": "older-result", "result": "stale"}
            fresh = {"from": console, "type": "evaluationResult",
                     "resultID": rid, "result": "kept"}
            return [ack, stray, stale, fresh]
        if "BOOM" in text:
            return [ack, {"from": console, "type": "evaluationResult",
                           "resultID": rid, "hasException": True,
                           "exceptionMessage": "boom happened"}]
        if "NOMSG" in text:
            return [ack, {"from": console, "type": "evaluationResult",
                           "resultID": rid, "hasException": True}]
        if "PREVIEW" in text:
            return [ack, {"from": console, "type": "evaluationResult",
                           "resultID": rid, "exception": {
                               "preview": {"message": "preview boom"}}}]
        if "UNDEF" in text:
            return [ack, {"from": console, "type": "evaluationResult",
                           "resultID": rid, "result": {"type": "undefined"}}]
        if "NULL" in text:
            return [ack, {"from": console, "type": "evaluationResult",
                           "resultID": rid, "result": None}]
        if "NONUMLEN" in text:
            return [ack, {"from": console, "type": "evaluationResult",
                           "resultID": rid, "result": {
                               "type": "longString", "actor": f"{console}/long9",
                               "length": "xx", "initial": "part"}}]
        if "NUM" in text:
            return [ack, {"from": console, "type": "evaluationResult",
                           "resultID": rid, "result": 42}]
        if "BADLONG" in text:
            return [ack, {"from": console, "type": "evaluationResult",
                           "resultID": rid, "result": {
                               "type": "longString", "initial": "part"}}]
        if "LONG" in text:
            grip = {"type": "longString", "actor": f"{console}/long1",
                    "length": 11, "initial": "hello"}
            return [ack, noise, {"from": console, "type": "evaluationResult",
                                  "resultID": rid, "result": grip}]
        return [ack, noise, {"from": console, "type": "evaluationResult",
                              "resultID": rid, "result": f"ran:{text}"}]

    def close(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


@pytest.fixture
def agent():
    server = FakeDebuggerServer()
    try:
        yield server
    finally:
        server.close()


# ---- probing: the greeting only, no session --------------------------------


def test_probe_reads_the_greeting_without_sending_anything(agent):
    assert rdp.probe(target(agent.port), timeout=3.0) is True
    assert agent.seen == [], "detection creates no session and sends nothing"


def test_a_dead_port_never_raises(agent):
    dead = _free_port()
    assert rdp.probe(target(dead), timeout=0.5) is False
    assert rdp.list_tabs(target(dead), timeout=0.5)[0] == []
    assert rdp.evaluate(target(dead), "11", "1+1", timeout=0.5)[0] is None
    assert rdp.navigate(target(dead), "11", "https://arena.ai/", timeout=0.5)[0] is False


# ---- tabs, JS, navigation ---------------------------------------------------


def test_list_tabs_returns_stable_ids_and_skips_the_interleaved_event(agent):
    rows, err = rdp.list_tabs(target(agent.port), timeout=3.0)
    assert err == ""
    assert [(r["id"], r["title"], r["url"]) for r in rows] == [
        ("11", "Arena A", "https://arena.ai/c/1"),
        ("12", "Arena B", "https://arena.ai/c/2")]
    assert agent.seen == [{"to": "root", "type": "listTabs"}]


def test_evaluate_resolves_the_tab_and_returns_the_js_value(agent):
    value, err = rdp.evaluate(target(agent.port), "11", "document.title", timeout=3.0)
    assert err == ""
    assert value.startswith("ran:(async()=>{"), value[:60]
    assert "document.title" in value
    kinds = [(m["to"], m["type"]) for m in agent.seen]
    assert kinds[0] == ("root", "listTabs")
    assert kinds[1] == ("server1.conn1.tabDescriptor1", "getTarget")
    sent = agent.seen[-1]
    assert sent["type"] == "evaluateJSAsync"
    assert sent["to"] == "server1.conn1.tabDescriptor1/console1"
    assert sent["mapped"] == {"await": True}, "promises resolve before return"


def test_a_long_string_result_is_dereferenced_through_substring(agent):
    value, err = rdp.evaluate(target(agent.port), "12", "LONG document.body", timeout=3.0)
    assert (value, err) == ("hello world", "")
    sub = [m for m in agent.seen if m["type"] == "substring"][-1]
    assert (sub["start"], sub["end"]) == (0, 11)


def test_navigate_resolves_the_tab_and_reports_the_url(agent):
    ok, err = rdp.navigate(target(agent.port), "12", "https://arena.ai/c/9", timeout=3.0)
    assert (ok, err) == (True, "")
    sent = [m for m in agent.seen if m["type"] == "navigateTo"][-1]
    assert sent["to"] == "server1.conn1.tabDescriptor2/target1"
    assert sent["url"] == "https://arena.ai/c/9"


# ---- errors and shape -------------------------------------------------------


def test_a_js_exception_becomes_a_js_error_with_the_page_text(agent):
    value, err = rdp.evaluate(target(agent.port), "11", "BOOM oops", timeout=3.0)
    assert value is None
    assert err.startswith("js:") and "boom happened" in err


def test_a_navigation_mid_eval_is_reported_not_hung(agent):
    value, err = rdp.evaluate(target(agent.port), "11", "NAVIGATE away", timeout=3.0)
    assert value is None
    assert err.startswith("navigated:")


def test_an_unknown_tab_is_reported_by_its_stable_id(agent):
    value, err = rdp.evaluate(target(agent.port), "999", "1+1", timeout=3.0)
    assert value is None
    assert err.startswith("no-tab:") and "999" in err


def test_a_protocol_error_becomes_a_typed_error_with_the_server_text(agent):
    conn = rdp.RdpConnection(target(agent.port), timeout=3.0)
    conn.connect()
    try:
        with pytest.raises(rdp.RdpError) as exc:
            conn.request("root", "no.such.command")
        assert "not implemented" in str(exc.value)
        assert exc.value.code == "unknownMethod"
    finally:
        conn.close()


def test_helpers_never_raise_on_a_hostile_server():
    """Garbage bytes instead of a greeting must not throw."""

    class _Garbage(socketserver.BaseRequestHandler):
        def handle(self):
            try:
                self.request.sendall(b"not-a-frame")
            except OSError:
                pass

    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Garbage)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        assert rdp.probe(target(port), timeout=1.0) is False
        rows, err = rdp.list_tabs(target(port), timeout=1.0)
        assert rows == [] and err
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# ---- the transport degrades, never hangs or raises ---------------------------


class RawScript:
    """A scripted byte server: greeting, then one canned answer per test."""

    def __init__(self, answer: bytes, delay: float = 0.0, rst: bool = False):
        self.answer, self.delay, self.rst = answer, delay, rst
        script = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                try:
                    _send_frame(self.request, GREETING)
                    self.request.settimeout(5.0)
                    self.request.recv(65536)  # the client's first request
                    if script.rst:
                        import struct
                        linger = struct.pack("ii", 1, 0)
                        self.request.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger)
                        self.request.close()  # RST: the client's read dies, not EOFs
                        return
                    if script.delay:
                        import time
                        time.sleep(script.delay)
                    if script.answer:
                        self.request.sendall(script.answer)
                except OSError:
                    pass

        self._server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()

    def close(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


@pytest.fixture
def raw():
    servers = []

    def make(answer: bytes, delay: float = 0.0, rst: bool = False):
        srv = RawScript(answer, delay, rst)
        servers.append(srv)
        return srv

    try:
        yield make
    finally:
        for srv in servers:
            srv.close()


def test_a_close_mid_frame_is_a_transport_error(raw):
    srv = raw(b"10:xx")  # prefix promises 10 bytes, the socket dies after 2
    rows, err = rdp.list_tabs(target(srv.port), timeout=2.0)
    assert rows == [] and err.startswith("transport:")


def test_a_reset_connection_is_a_transport_error_not_an_eof(raw):
    srv = raw(b"", rst=True)
    rows, err = rdp.list_tabs(target(srv.port), timeout=2.0)
    assert rows == [] and err.startswith("transport: connection lost")


def test_a_silent_server_times_out_instead_of_hanging(raw):
    srv = raw(b"", delay=5.0)
    rows, err = rdp.list_tabs(target(srv.port), timeout=0.2)
    assert rows == [] and "timed out" in err


def test_an_oversized_frame_is_refused_without_reading_it(raw):
    srv = raw(b"40000000:")  # no body follows; the client must not wait for it
    rows, err = rdp.list_tabs(target(srv.port), timeout=2.0)
    assert rows == [] and "too large" in err


def test_a_non_json_frame_is_a_protocol_error(raw):
    srv = raw(b"5:xxxxx")
    rows, err = rdp.list_tabs(target(srv.port), timeout=2.0)
    assert rows == [] and err.startswith("protocol:") and "non-JSON" in err


def test_a_greeting_from_a_non_root_actor_is_rejected():
    srv = FakeDebuggerServer(greeting={"from": "nope"})
    try:
        assert rdp.probe(target(srv.port), timeout=2.0) is False
        rows, err = rdp.list_tabs(target(srv.port), timeout=2.0)
        assert rows == [] and "not a Firefox debugger server" in err
    finally:
        srv.close()


def test_sending_on_a_dead_socket_is_a_transport_error(agent):
    conn = rdp.RdpConnection(target(agent.port), timeout=3.0)
    conn.connect()
    conn._fp.close()
    conn._sock.close()  # the fd is fully gone; the client notices on send
    try:
        with pytest.raises(rdp.RdpError) as exc:
            conn.request("root", "listTabs")
        assert exc.value.code == "transport"
    finally:
        conn.close()


def test_requests_before_connect_are_transport_errors(agent):
    conn = rdp.RdpConnection(target(agent.port), timeout=3.0)
    with pytest.raises(rdp.RdpError) as exc:
        conn.request("root", "listTabs")
    assert exc.value.code == "transport" and "not connected" in str(exc.value)
    with pytest.raises(rdp.RdpError) as exc:
        conn._recv()
    assert exc.value.code == "transport"


def test_close_swallows_a_failing_stream(agent):
    conn = rdp.RdpConnection(target(agent.port), timeout=3.0)
    conn.connect()

    class _Boom:
        def close(self):
            raise OSError("already gone")

    conn._fp = _Boom()
    conn.close()  # must not raise


def test_an_unexpected_callback_in_run_is_returned_never_raised(agent):
    rows, err = rdp._run(target(agent.port), 3.0, lambda c: 1 / 0)
    assert rows is None and err.startswith("ZeroDivisionError:")


# ---- broken shapes degrade to named errors -----------------------------------


def test_a_tab_without_any_identity_is_skipped(agent):
    srv = FakeDebuggerServer(tabs=[{"title": "ghost"}])
    try:
        rows, err = rdp.list_tabs(target(srv.port), timeout=3.0)
        assert (rows, err) == ([], "")
    finally:
        srv.close()


def test_a_tab_without_an_actor_is_a_protocol_error():
    srv = FakeDebuggerServer(tabs=[{"browserId": 7, "title": "ghost",
                                    "url": "https://ghost.example/"}])
    try:
        value, err = rdp.evaluate(target(srv.port), "7", "1+1", timeout=3.0)
        assert value is None and "without an actor" in err
    finally:
        srv.close()


def test_a_target_without_a_console_is_a_protocol_error():
    tabs = [{"actor": "server1.conn1.tabDescriptor9", "browserId": 9,
             "title": "broken", "url": "https://broken.example/", "broken": True}]
    srv = FakeDebuggerServer(tabs=tabs)
    try:
        value, err = rdp.evaluate(target(srv.port), "9", "1+1", timeout=3.0)
        assert value is None and "no target" in err
    finally:
        srv.close()


def test_stray_packets_and_stale_results_are_skipped(agent):
    value, err = rdp.evaluate(target(agent.port), "11", "STRAY poll", timeout=3.0)
    assert (value, err) == ("kept", "")


def test_result_shapes_degrade_to_json_strings(agent):
    assert rdp.evaluate(target(agent.port), "11", "UNDEF x", timeout=3.0) == ("null", "")
    assert rdp.evaluate(target(agent.port), "11", "NULL x", timeout=3.0) == ("null", "")
    assert rdp.evaluate(target(agent.port), "11", "NUM 40+2", timeout=3.0) == ("42", "")


def test_exceptions_carry_preview_text_or_a_fallback(agent):
    value, err = rdp.evaluate(target(agent.port), "11", "PREVIEW fail", timeout=3.0)
    assert value is None and "preview boom" in err
    value, err = rdp.evaluate(target(agent.port), "11", "NOMSG fail", timeout=3.0)
    assert value is None and err == "js: JS exception"


def test_a_broken_longstring_falls_back_to_its_initial_text(agent):
    assert rdp.evaluate(target(agent.port), "11", "BADLONG big", timeout=3.0) == ("part", "")
    assert rdp.evaluate(target(agent.port), "11", "NONUMLEN big", timeout=3.0) == ("part", "")
