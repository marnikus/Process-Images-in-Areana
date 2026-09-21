"""WebDriver BiDi — the protocol a current Firefox actually speaks (2026-09-21).

Firefox's Remote Agent serves BOTH the HTTP entry point and the session socket
on ONE port: `POST /session` answers with `capabilities.webSocketUrl`, and the
socket requires `session.new` as its first command (BiDi spec). This suite runs a
real fake Remote Agent on one port — plain HTTP for `POST /session`, a hand-rolled
WebSocket upgrade + frame loop for the session socket — so the client is
exercised against the transport, not against a stub.

RED at `bce5a01`: `app.browser.bidi` did not exist.
"""

import base64
import hashlib
import json
import socket
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.browser import bidi

pytestmark = pytest.mark.unit

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
CONTEXTS = [
    {"context": "ctx-a", "url": "https://arena.ai/c/1", "children": []},
    {"context": "ctx-b", "url": "https://arena.ai/c/2",
     "children": [{"context": "ctx-b-1", "url": "https://arena.ai/c/2/frame", "children": []}]},
]


def target(port: int) -> "bidi.Endpoint":
    """The fake agent as the client sees it."""
    return bidi.Endpoint("127.0.0.1", port)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---- minimal RFC 6455 server side (text frames, no extensions) --------------


def _accept_key(key: str) -> str:
    digest = hashlib.sha1((key + WS_GUID).encode()).digest()
    return base64.b64encode(digest).decode()


def _read_exactly(rfile, size: int) -> bytes:
    data = rfile.read(size)
    if data is None or len(data) != size:
        raise ConnectionError("socket closed mid-frame")
    return data


def _read_message(rfile) -> str:
    """One client text frame: header, mask, payload (client frames are masked)."""
    head = _read_exactly(rfile, 2)
    opcode, length = head[0] & 0x0F, head[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", _read_exactly(rfile, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _read_exactly(rfile, 8))[0]
    mask = _read_exactly(rfile, 4) if head[1] & 0x80 else b""
    payload = bytearray(_read_exactly(rfile, length))
    for i in range(len(payload)):
        payload[i] ^= mask[i % 4]
    if opcode == 0x8:
        raise ConnectionError("client closed the socket")
    if opcode == 0x9:                                    # ping → pong
        return ""
    return payload.decode("utf-8")


def _write_message(rfile, wfile, text: str) -> None:
    """One unmasked server text frame."""
    payload = text.encode("utf-8")
    header = bytes([0x81])
    if len(payload) < 126:
        header += bytes([len(payload)])
    elif len(payload) < 65536:
        header += bytes([126]) + struct.pack("!H", len(payload))
    else:
        header += bytes([127]) + struct.pack("!Q", len(payload))
    wfile.write(header + payload)
    wfile.flush()


class FakeRemoteAgent:
    """One port: `POST /session` + the BiDi session socket, like Firefox's agent."""

    def __init__(self, contexts=None, session_id="sess-1", require_session_new=True):
        self.contexts = CONTEXTS if contexts is None else contexts
        self.session_id = session_id
        self.require_session_new = require_session_new
        self.port = _free_port()
        self.seen = []
        self._session_new = False
        agent = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_POST(self):
                if not self.path.startswith("/session"):
                    self.send_error(404)
                    return
                self._read_body()
                agent._json(self, {"value": {"sessionId": agent.session_id,
                                             "capabilities": {
                                                 "webSocketUrl":
                                                     f"ws://127.0.0.1:{agent.port}/session"}}})

            def do_GET(self):
                if "websocket" not in self.headers.get("Upgrade", "").lower():
                    self.send_error(404)
                    return
                accept = _accept_key(self.headers.get("Sec-WebSocket-Key", ""))
                self.wfile.write(
                    b"HTTP/1.1 101 Switching Protocols\r\n"
                    b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                    b"Sec-WebSocket-Accept: " + accept.encode() + b"\r\n\r\n")
                self.wfile.flush()
                self._serve_socket()

            def _serve_socket(self):
                try:
                    while True:
                        raw = _read_message(self.rfile)
                        if raw:
                            agent.seen.append(json.loads(raw))
                            _write_message(self.rfile, self.wfile,
                                           json.dumps(agent._reply(agent.seen[-1])))
                except Exception:
                    self.close_connection = True

            def _read_body(self):
                size = int(self.headers.get("Content-Length", 0) or 0)
                if size:
                    self.rfile.read(size)

        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()

    @staticmethod
    def _json(handler, payload):
        body = json.dumps(payload).encode()
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _reply(self, msg):
        """BiDi reply for one command, incl. the `session.new`-first rule."""
        mid, method = msg.get("id", 0), msg.get("method", "")
        if method == "session.new":
            self._session_new = True
            return {"id": mid, "result": {"sessionId": self.session_id, "capabilities": {}}}
        if self.require_session_new and not self._session_new:
            return {"id": mid, "error": "invalid argument", "message": "session not started"}
        if method == "browsingContext.getTree":
            return {"id": mid, "result": {"contexts": self.contexts}}
        if method == "script.evaluate":
            expr = (msg.get("params") or {}).get("expression", "")
            return {"id": mid, "result": {"type": "success",
                                          "result": {"type": "string", "value": f"ran:{expr}"}}}
        if method == "browsingContext.navigate":
            return {"id": mid, "result": {"navigation": None,
                                          "url": (msg.get("params") or {}).get("url", "")}}
        return {"id": mid, "error": "unknown command", "message": f"{method} is not implemented"}

    def close(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


@pytest.fixture
def agent():
    a = FakeRemoteAgent()
    try:
        yield a
    finally:
        a.close()


# ---- session bootstrap ------------------------------------------------------


def test_open_session_reads_the_websocket_url_from_the_http_endpoint(agent):
    session = bidi.open_session(target(agent.port), timeout=3.0)
    assert session is not None
    assert session.ws_url == f"ws://127.0.0.1:{agent.port}/session"
    assert session.session_id == "sess-1"


def test_a_dead_port_returns_none_with_an_error_never_raises():
    dead = _free_port()
    assert bidi.open_session(target(dead), timeout=0.5) is None
    assert bidi.list_contexts(target(dead), timeout=0.5) == ([], "no BiDi session")
    assert bidi.evaluate(target(dead), "ctx-a", "1+1", timeout=0.5)[0] is None


# ---- tabs, JS, navigation ---------------------------------------------------


def test_list_contexts_flattens_the_browser_tree_into_target_rows(agent):
    contexts, err = bidi.list_contexts(target(agent.port), timeout=3.0)
    assert err == ""
    assert [c["id"] for c in contexts] == ["ctx-a", "ctx-b", "ctx-b-1"]
    assert contexts[1]["url"] == "https://arena.ai/c/2"
    assert agent.seen[0]["method"] == "session.new", "BiDi requires session.new first"
    assert agent.seen[1]["method"] == "browsingContext.getTree"


def test_evaluate_returns_the_js_value_as_json(agent):
    value, err = bidi.evaluate(target(agent.port), "ctx-a", "document.title", timeout=3.0)
    assert err == ""
    assert json.loads(value) == "ran:document.title"
    sent = [m for m in agent.seen if m["method"] == "script.evaluate"][-1]
    assert sent["params"]["target"] == {"context": "ctx-a"}
    assert sent["params"]["awaitPromise"] is True


def test_navigate_asks_the_context_and_reports_the_url(agent):
    ok, err = bidi.navigate(target(agent.port), "ctx-b", "https://arena.ai/c/9", timeout=3.0)
    assert (ok, err) == (True, "")
    sent = [m for m in agent.seen if m["method"] == "browsingContext.navigate"][-1]
    assert sent["params"]["context"] == "ctx-b"
    assert sent["params"]["url"] == "https://arena.ai/c/9"


# ---- errors and shape -------------------------------------------------------


def test_a_protocol_error_becomes_a_typed_error_with_the_agent_text(agent):
    session = bidi.open_session(target(agent.port), timeout=3.0)
    with pytest.raises(bidi.BidiError) as exc:
        session.command("no.such.command", {})
    assert "not implemented" in str(exc.value)
    assert exc.value.code == "unknown command"
    session.close()


def test_a_session_socket_that_demands_session_new_first_is_satisfied(agent):
    session = bidi.open_session(target(agent.port), timeout=3.0)
    result = session.command("browsingContext.getTree", {})
    assert "contexts" in result
    assert session.session_new_sent is True
    session.close()


def test_helpers_never_raise_on_a_hostile_agent():
    """A socket that closes immediately / a garbage HTTP body must not throw."""
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), _GarbageHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert bidi.open_session(target(port), timeout=1.0) is None
        assert bidi.list_contexts(target(port), timeout=1.0) == ([], "no BiDi session")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class _GarbageHandler(BaseHTTPRequestHandler):
    """`POST /session` → a 200 whose body is not JSON, socket then closed."""

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = b"not json"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
