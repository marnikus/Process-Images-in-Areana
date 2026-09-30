"""The browser-level truth of one endpoint — dial, target list, create, close.

Design: docs/archive/2026-09-29-new-chat-new-tab-profile-truth/design.md (§3 R1/R2, §4).
The fakes answer Chrome's own message shape (`{"id", "result"}` / `{"id", "error"}`) because
that is what `CDPTransport.send` hands back (I-74).
"""
from __future__ import annotations

import asyncio

import pytest

from app.browser.cdp import browser_targets as bt

pytestmark = pytest.mark.unit


# ── pure helpers ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ws_url, want", [
    ("ws://127.0.0.1:9223/devtools/page/AB12", ("127.0.0.1", 9223)),
    ("ws://localhost:9222/devtools/browser/9c-1", ("localhost", 9222)),
    ("", None), (None, None), ("http://127.0.0.1:9222/json/list", None),
    ("ws://127.0.0.1/devtools/page/AB", None),
])
def test_endpoint_of_ws_reads_the_tabs_own_endpoint(ws_url, want):
    assert bt.endpoint_of_ws(ws_url) == want


def _infos(*rows):
    return list(rows)


P1 = {"targetId": "P1", "type": "page", "url": "https://arena.ai/c/1", "title": ""}
P2 = {"targetId": "P2", "type": "page", "url": "https://arena.ai/c/2", "title": "",
      "browserContextId": "CTX2"}
WORKER = {"targetId": "W1", "type": "service_worker", "url": "https://arena.ai/sw.js"}


def test_context_of_distinguishes_default_absent_and_unknown():
    infos = _infos(P1, P2, WORKER)
    assert bt.context_of(infos, "P1") == ""            # listed without an id = default context
    assert bt.context_of(infos, "P2") == "CTX2"
    assert bt.context_of(infos, "NOPE") is None         # not listed = unknown, never a guess


def test_target_of_finds_a_page_target_only():
    assert bt.target_of(_infos(P1, WORKER), "P1")["url"] == "https://arena.ai/c/1"
    assert bt.target_of(_infos(P1, WORKER), "W1") is None
    assert bt.target_of(_infos(P1), "P2") is None


def test_matching_targets_filters_pattern_and_context():
    infos = _infos(P1, P2, WORKER, {"targetId": "X", "type": "page", "url": "https://other/x"})
    assert [t["targetId"] for t in bt.matching_targets(infos, "arena.ai")] == ["P1", "P2"]
    assert [t["targetId"] for t in bt.matching_targets(infos, "arena.ai", "CTX2")] == ["P2"]
    assert [t["targetId"] for t in bt.matching_targets(infos, "arena.ai", "")] == ["P1"]
    assert bt.matching_targets(infos, "") == []


# ── the browser connection ─────────────────────────────────────────────────

class _FakeClient:
    def __init__(self, replies=None, boom=False):
        self.replies, self.boom = list(replies or []), boom
        self.sent, self.connected, self.disconnected = [], "", False

    async def connect(self, ws_url):
        if self.boom:
            return False
        self.connected = ws_url
        return True

    async def send(self, method, params=None, timeout=30):
        self.sent.append((method, params))
        reply = self.replies.pop(0) if self.replies else {}
        if isinstance(reply, Exception):
            raise reply
        return reply

    async def disconnect(self):
        self.disconnected = True


def _dial(monkeypatch, client, ws="ws://127.0.0.1:9333/devtools/browser/U1", url="ws://127.0.0.1:9333/devtools/browser/U1"):
    calls = []

    def fake_ws_url(host, port):
        calls.append((host, port))
        return url
    monkeypatch.setattr(bt, "_browser_ws_url", fake_ws_url)
    monkeypatch.setattr(bt, "CDPClient", lambda host, port: client)
    return calls


def test_dial_connects_to_the_endpoints_browser_socket(monkeypatch):
    client = _FakeClient()
    calls = _dial(monkeypatch, client)
    probe, err = asyncio.run(bt.dial("127.0.0.1", 9333))
    assert err == "" and probe is not None
    assert calls == [("127.0.0.1", 9333)] and client.connected.endswith("/devtools/browser/U1")
    assert (probe.host, probe.port) == ("127.0.0.1", 9333)


def test_dial_without_a_browser_socket_is_a_reason_not_a_crash(monkeypatch):
    client = _FakeClient()
    _dial(monkeypatch, client, url="")
    probe, err = asyncio.run(bt.dial("127.0.0.1", 9333))
    assert probe is None and "browser" in err.lower() and client.sent == []


def test_dial_refused_connection_is_a_reason(monkeypatch):
    client = _FakeClient(boom=True)
    _dial(monkeypatch, client)
    probe, err = asyncio.run(bt.dial("127.0.0.1", 9333))
    assert probe is None and err


def test_targets_reads_chrome_result_and_reports_an_error(monkeypatch):
    ok = _FakeClient([{"id": 1, "result": {"targetInfos": [P1, P2]}}])
    monkeypatch.setattr(bt, "_browser_ws_url", lambda h, p: "ws://h:1/devtools/browser/U")
    monkeypatch.setattr(bt, "CDPClient", lambda host, port: ok)
    probe, err = asyncio.run(bt.dial("h", 1))
    infos, err = asyncio.run(probe.targets())
    assert err == "" and [t["targetId"] for t in infos] == ["P1", "P2"]
    bad = _FakeClient([{"id": 1, "error": {"message": "Target domain not available"}}])
    monkeypatch.setattr(bt, "CDPClient", lambda host, port: bad)
    probe2, _ = asyncio.run(bt.dial("h", 1))
    infos, err = asyncio.run(probe2.targets())
    assert infos == [] and "not available" in err


def test_create_sends_the_context_and_reads_the_id_or_the_refusal(monkeypatch):
    client = _FakeClient([{"id": 1, "result": {"targetId": "NEW"}},
                          {"id": 2, "error": {"message": "Failed to find browser context with id CTX"}}])
    monkeypatch.setattr(bt, "_browser_ws_url", lambda h, p: "ws://h:1/devtools/browser/U")
    monkeypatch.setattr(bt, "CDPClient", lambda host, port: client)
    probe, _ = asyncio.run(bt.dial("h", 1))
    tid, err = asyncio.run(probe.create("https://arena.ai/x", "CTX"))
    assert (tid, err) == ("NEW", "")
    assert client.sent[0] == ("Target.createTarget", {"url": "https://arena.ai/x", "browserContextId": "CTX"})
    tid, err = asyncio.run(probe.create("https://arena.ai/x", "CTX"))
    assert tid == "" and "Failed to find browser context" in err


def test_create_without_a_context_sends_no_context_key(monkeypatch):
    client = _FakeClient([{"id": 1, "result": {"targetId": "NEW"}}])
    monkeypatch.setattr(bt, "_browser_ws_url", lambda h, p: "ws://h:1/devtools/browser/U")
    monkeypatch.setattr(bt, "CDPClient", lambda host, port: client)
    probe, _ = asyncio.run(bt.dial("h", 1))
    asyncio.run(probe.create("https://arena.ai/x", ""))
    assert client.sent[0] == ("Target.createTarget", {"url": "https://arena.ai/x"})


def test_close_reports_success_and_a_failure(monkeypatch):
    client = _FakeClient([{"id": 1, "result": {"success": True}},
                          {"id": 2, "result": {"success": False}},
                          RuntimeError("socket gone")])
    monkeypatch.setattr(bt, "_browser_ws_url", lambda h, p: "ws://h:1/devtools/browser/U")
    monkeypatch.setattr(bt, "CDPClient", lambda host, port: client)
    probe, _ = asyncio.run(bt.dial("h", 1))
    assert asyncio.run(probe.close("OLD")) == (True, "")
    ok, err = asyncio.run(probe.close("OLD"))
    assert ok is False and err
    ok, err = asyncio.run(probe.close("OLD"))
    assert ok is False and "socket gone" in err


def test_browser_ws_url_reads_the_version_endpoint(monkeypatch):
    from app.browser.cdp import tabs as tabs_mod
    monkeypatch.setattr(tabs_mod, "_fetch_json_sync",
                        lambda url, timeout=3.0: ({"webSocketDebuggerUrl": "ws://h:1/devtools/browser/U"}, ""))
    assert bt._browser_ws_url("h", 1) == "ws://h:1/devtools/browser/U"
    monkeypatch.setattr(tabs_mod, "_fetch_json_sync", lambda url, timeout=3.0: ({"Browser": "Chrome"}, ""))
    assert bt._browser_ws_url("h", 1) == ""
    monkeypatch.setattr(tabs_mod, "_fetch_json_sync", lambda url, timeout=3.0: (None, "connection refused"))
    assert bt._browser_ws_url("h", 1) == ""


def test_a_reply_of_the_wrong_shape_is_a_reason():
    assert bt._reply("nope", "Target.getTargets") == ({}, "Target.getTargets answered str")
    assert bt._reply({"error": "flat message"}, "Target.closeTarget") == ({}, "Target.closeTarget: flat message")


def test_create_and_close_on_a_dead_socket_are_reasons():
    client = _FakeClient()
    probe = bt.BrowserTargets(host="h", port=1, client=client)
    client.send = _boom
    tid, err = asyncio.run(probe.create("https://arena.ai/x", "CTX"))
    assert tid == "" and "socket gone" in err
    ok, err = asyncio.run(probe.close("X"))
    assert ok is False and "socket gone" in err


def test_close_that_answers_an_error_is_a_reason(monkeypatch):
    client = _FakeClient([{"id": 1, "error": {"message": "No target with given id"}}])
    monkeypatch.setattr(bt, "_browser_ws_url", lambda h, p: "ws://h:1/devtools/browser/U")
    monkeypatch.setattr(bt, "CDPClient", lambda host, port: client)
    probe, _ = asyncio.run(bt.dial("h", 1))
    ok, err = asyncio.run(probe.close("GONE"))
    assert ok is False and "No target with given id" in err


def test_calls_on_a_dead_socket_become_reasons_not_raises():
    client = _FakeClient()
    probe = bt.BrowserTargets(host="h", port=1, client=client)
    infos, err = asyncio.run(probe.targets())
    assert infos == [] and err                                    # no answer is a reason
    client.send = _boom
    infos, err = asyncio.run(probe.targets())
    assert infos == [] and "socket gone" in err
    ok, err = asyncio.run(probe.close("X"))
    assert ok is False and "socket gone" in err


def _boom(*_args, **_kwargs):
    raise RuntimeError("socket gone")


def test_aclose_is_idempotent_and_a_failed_disconnect_is_logged(monkeypatch):
    client = _FakeClient()
    probe = bt.BrowserTargets(host="h", port=1, client=client)
    asyncio.run(probe.aclose())
    asyncio.run(probe.aclose())                                   # second call is a no-op
    assert client.disconnected is True

    async def broken():
        raise RuntimeError("already closed")
    client.disconnect = broken
    probe2 = bt.BrowserTargets(host="h", port=1, client=client)
    asyncio.run(probe2.aclose())                                  # never raises


def test_dial_that_cannot_connect_reports_the_socket_error(monkeypatch):
    class _Exploding(_FakeClient):
        async def connect(self, ws_url):
            raise RuntimeError("handshake refused")
    monkeypatch.setattr(bt, "_browser_ws_url", lambda h, p: "ws://h:1/devtools/browser/U")
    monkeypatch.setattr(bt, "CDPClient", lambda host, port: _Exploding())
    probe, err = asyncio.run(bt.dial("h", 1))
    assert probe is None and "handshake refused" in err


def test_aclose_disconnects_and_never_raises(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(bt, "_browser_ws_url", lambda h, p: "ws://h:1/devtools/browser/U")
    monkeypatch.setattr(bt, "CDPClient", lambda host, port: client)
    probe, _ = asyncio.run(bt.dial("h", 1))
    asyncio.run(probe.aclose())
    assert client.disconnected is True
    monkeypatch.setattr(bt, "CDPClient", lambda host, port: _FakeClient(boom=True))
    dead, err = asyncio.run(bt.dial("h", 1))
    assert dead is None and err


def test_page_ws_is_the_reverse_of_endpoint_of_ws():
    """The page socket is formatted where it is parsed, and the pair round-trips (audit #4 N4)."""
    ws = bt.page_ws("127.0.0.1", 9333, "ABC123")
    assert ws == "ws://127.0.0.1:9333/devtools/page/ABC123"
    assert bt.endpoint_of_ws(ws) == ("127.0.0.1", 9333)
