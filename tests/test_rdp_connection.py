"""RDP connection — greeting, pairing, events, actor expiry (2026-09-21, round 8).

The channel the stealth requirement forces on us has no request ids: replies are
matched in order, and the only thing that can arrive unsolicited is an event. A
connection therefore has to (a) drain the greeting, (b) keep events out of the
reply path, (c) turn `noSuchActor` into a typed error, and (d) survive a server
that never answers — all against a real socket, never a mock.

RED at `464185a`: `app.browser.rdp` did not exist.
"""

import socket

import pytest

from app.browser.rdp import wire
from app.browser.rdp.connection import RdpConnection
from tests.fakes.rdp_stub_server import RdpStubServer, frame

pytestmark = pytest.mark.unit


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def stub():
    server = RdpStubServer()
    try:
        yield server
    finally:
        server.close()


def _connect(port: int, **kwargs) -> RdpConnection:
    conn = RdpConnection(wire.Endpoint("127.0.0.1", port), timeout=3.0, **kwargs)
    conn.connect()
    return conn


def test_connect_reads_the_root_greeting_and_keeps_its_prefix(stub):
    conn = _connect(stub.port)
    assert conn.ready is True
    assert conn.greeting.get("applicationType") == "browser"
    assert conn.drain_events() == [], "the greeting is consumed on connect, never left queued"
    conn.close()


def test_connect_tolerates_a_server_that_skips_the_greeting():
    server = RdpStubServer(greet=False)
    try:
        conn = _connect(server.port)
        assert conn.ready is True
        assert conn.greeting == {} or conn.greeting.get("from") is None
        conn.close()
    finally:
        server.close()


def test_request_and_response_are_paired_in_order(stub):
    conn = _connect(stub.port)
    first = conn.request({"to": "root", "type": "listTabs"})
    second = conn.request({"to": first["tabs"][0]["actor"], "type": "getTarget"})
    assert len(first["tabs"]) == 2
    assert second["form"]["consoleActor"].startswith("server1.conn1.")
    conn.close()


def test_an_event_arriving_while_a_request_is_pending_is_queued_not_consumed(stub):
    """Two requests in flight: replies pair in order, events never steal a slot."""
    conn = _connect(stub.port)
    conn.send({"to": "root", "type": "listTabs"})
    conn.send({"to": "server1.conn1.consoleActor1", "type": "evaluateJSAsync", "text": "1+1"})
    reply = conn.wait_for(lambda r: "resultID" in r)
    assert "resultID" in reply, "the pending request got its own reply"
    assert any("tabs" in p for p in conn.drain_events()), \
        "the reply that came first was queued, not lost"
    event = conn.wait_for(lambda p: p.get("type") == "evaluationResult")
    assert event["resultID"] == reply["resultID"], "and the pushed event follows it"
    assert conn.drain_events() == [], "nothing left behind"
    conn.close()


def test_a_typed_response_is_still_the_response():
    """`tabAttached` replies to `attach` and must not be mistaken for an event."""
    server = RdpStubServer(legacy_attach=True)
    try:
        conn = _connect(server.port)
        tabs = conn.request({"to": "root", "type": "listTabs"})["tabs"]
        target = conn.request({"to": tabs[0]["actor"], "type": "getTarget"})
        assert "consoleActor" not in target["form"]
        attached = conn.request({"to": tabs[0]["actor"], "type": "attach"})
        assert attached["type"] == "tabAttached"
        assert attached["consoleActor"].startswith("server1.conn1.")
        conn.close()
    finally:
        server.close()


def test_a_dead_actor_raises_no_such_actor(stub):
    conn = _connect(stub.port)
    with pytest.raises(wire.RdpError) as exc:
        conn.request({"to": "server1.conn1.consoleActor99", "type": "evaluateJS", "text": "1"})
    assert "noSuchActor" in str(exc.value)
    conn.close()


def test_a_silent_server_times_out_with_a_named_error():
    server = RdpStubServer(silent=True)
    try:
        conn = RdpConnection(wire.Endpoint("127.0.0.1", server.port), timeout=0.4)
        conn.connect()
        with pytest.raises(wire.RdpError) as exc:
            conn.request({"to": "root", "type": "listTabs"})
        assert "timeout" in str(exc.value).lower()
        conn.close()
    finally:
        server.close()


def test_a_dead_port_refuses_to_connect_with_a_reason():
    port = _free_port()
    conn = RdpConnection(wire.Endpoint("127.0.0.1", port), timeout=0.5)
    with pytest.raises(wire.RdpError):
        conn.connect()
    assert conn.ready is False
    conn.close()   # idempotent, no exception


def test_the_connection_is_a_plain_socket_so_detaching_never_touches_the_browser(stub):
    """Attach/detach = open/close our socket; the stub keeps serving (R2)."""
    first = _connect(stub.port)
    assert first.request({"to": "root", "type": "listTabs"})["tabs"]
    first.close()
    second = _connect(stub.port)
    assert second.request({"to": "root", "type": "listTabs"})["tabs"], "browser still there"
    assert stub.connections == 2
    second.close()


def test_a_connection_that_was_never_opened_says_so_instead_of_sending(stub):
    """Boundary: the slot path may call after a failure — it gets a reason, not a crash."""
    conn = RdpConnection(wire.Endpoint("127.0.0.1", stub.port), timeout=1.0)
    with pytest.raises(wire.RdpError) as exc:
        conn.send({"to": "root", "type": "listTabs"})
    assert "not connected" in str(exc.value)
    with pytest.raises(wire.RdpError):
        conn.read()
    conn.close()          # idempotent, and after a failed connect too


def test_probing_an_endpoint_that_is_not_rdp_answers_false_and_leaves_no_socket():
    from app.browser.rdp.client import probe
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        assert probe(wire.Endpoint("127.0.0.1", port), timeout=0.2) is False, \
            "an endpoint that greets nothing is not RDP — and the probe does not raise"


def test_frames_written_by_the_stub_are_read_by_the_codec(stub):
    """The stub frames its own bytes; nothing in the client may assume its writer."""
    conn = _connect(stub.port)
    conn.request({"to": "root", "type": "listTabs"})     # the stub records before it replies
    assert stub.received[-1] == {"to": "root", "type": "listTabs"}
    assert frame({"from": "root"}, byte_prefixed=False).startswith(b"16:")
    conn.close()
