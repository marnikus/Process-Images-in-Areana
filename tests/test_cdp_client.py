"""D4.4: CDP client transport tests — fake websockets server, no real Chrome.

The fake implements the CDP wire contract (JSON id/method/result/error) and
lets tests drive events and per-method failures. RULE 8: CDPClient is the real
unit under test; only the websocket module is faked at the import boundary.
"""

import asyncio
import json
import sys
from types import ModuleType

import pytest

from app.browser import cdp_client
from tests.conftest import FakeCDPServer, RAW_TABS, make_client  # shared harness
from app.browser.cdp_client import (
    CDPClient,
    TabInfo,
    diagnose_sync,
    fetch_tabs_sync,
)

pytestmark = pytest.mark.unit


# ── fake websocket server ──

# ── module-level sync API (HTTP /json endpoints) ──

def test_fetch_tabs_sync_dedupes_and_prefers_host(monkeypatch):
    monkeypatch.setattr(cdp_client, "_is_port_open", lambda h, p, timeout=0.8: True)

    def fake_fetch(url, timeout=3.0):
        host = "10.0.0.9" if "10.0.0.9" in url else "127.0.0.1"
        tabs = []
        for t in RAW_TABS:
            t = dict(t)
            if t.get("webSocketDebuggerUrl"):
                t["webSocketDebuggerUrl"] = t["webSocketDebuggerUrl"].replace("10.0.0.9", host)
            tabs.append(t)
        return tabs, ""
    monkeypatch.setattr(cdp_client, "_fetch_json_sync", fake_fetch)
    tabs, err, tried = fetch_tabs_sync(host="127.0.0.1", port=9222)
    assert err == "" and len(tried) >= 2
    by_id = {t.id: t for t in tabs}
    assert set(by_id) == {"t1", "t2"}  # same id via two hosts → one entry
    assert "127.0.0.1" in by_id["t1"].ws_url  # preferred host wins


def test_fetch_tabs_sync_port_closed_reports_error(monkeypatch):
    monkeypatch.setattr(cdp_client, "_is_port_open", lambda h, p, timeout=0.8: False)
    tabs, err, tried = fetch_tabs_sync(host="127.0.0.1", port=9222)
    assert tabs == [] and "not open" in err and tried


def test_fetch_tabs_sync_bad_json(monkeypatch):
    monkeypatch.setattr(cdp_client, "_is_port_open", lambda h, p, timeout=0.8: True)
    monkeypatch.setattr(cdp_client, "_fetch_json_sync",
                        lambda url, timeout=3.0: (None, "JSON parse failed"))
    tabs, err, _ = fetch_tabs_sync(host="127.0.0.1", port=9222)
    assert tabs == [] and "JSON parse" in err


def test_diagnose_sync_branches(monkeypatch):
    # 1) no open ports
    monkeypatch.setattr(cdp_client, "_is_port_open", lambda h, p, timeout=1.0: False)
    monkeypatch.setattr(cdp_client, "_fetch_json_sync",
                        lambda url, timeout=3.0: (None, "refused"))
    out = diagnose_sync(host="127.0.0.1", port=9222)
    assert out["summary"].startswith("❌") and out["tabs"] == []
    # 2) open but zero tabs
    monkeypatch.setattr(cdp_client, "_is_port_open", lambda h, p, timeout=1.0: True)
    monkeypatch.setattr(cdp_client, "_fetch_json_sync",
                        lambda url, timeout=3.0: ([], "") if "/list" in url else ({"Browser": "x"}, ""))
    out = diagnose_sync(host="127.0.0.1", port=9222)
    assert out["summary"].startswith("⚠")
    # 3) tabs found
    monkeypatch.setattr(cdp_client, "_fetch_json_sync",
                        lambda url, timeout=3.0: (RAW_TABS, "") if "/list" in url
                        else ({"Browser": "Chrome/1"}, ""))
    out = diagnose_sync(host="127.0.0.1", port=9222)
    assert out["summary"].startswith("✅") and len(out["tabs"]) == 2
    assert all(c["port_open"] for c in out["checks"])


# ── client properties / host port ──

def test_client_properties_and_host_port():
    client = make_client()
    assert client.base_url == "http://127.0.0.1:9222"
    assert client.is_connected is False
    assert client.get_host_port() == ("127.0.0.1", 9222)
    client.set_host_port("localhost", 9333)
    assert client.get_host_port() == ("localhost", 9333)
    client.set_host_port("  ", "not-a-port")  # invalid inputs keep old values
    assert client.get_host_port() == ("localhost", 9333)
    client.set_host_port(port=0)
    assert client._port == 9333
    assert isinstance(client.events.add(lambda m: None), type(None))


# ── connect lifecycle ──

async def test_connect_success_enables_domains(cdp_server):
    client = make_client(cdp_server)
    ok = await client.connect("ws://10.0.0.9:9222/devtools/page/t1")
    assert ok is True and client.is_connected
    assert len(client.connected.calls) == 1
    for dom in ("Page", "DOM", "Runtime", "Network"):
        assert f"{dom}.enable" in cdp_server.methods()
    assert client._current_tab_id == "t1"


async def test_connect_reuses_same_tab(cdp_server):
    client = make_client(cdp_server)
    url = "ws://10.0.0.9:9222/devtools/page/t1"
    assert await client.connect(url) is True
    assert await client.connect(url) is True
    assert len(cdp_server.connects) == 1  # second connect was a no-op reuse


async def test_connect_falls_back_to_candidates(cdp_server):
    bad = "ws://10.0.0.9:9222/devtools/page/t1"
    cdp_server.fail_urls = {bad}
    client = make_client(cdp_server)
    ok = await client.connect(bad)
    assert ok is True
    assert len(cdp_server.connects) >= 2  # first candidate failed, fell through
    assert "127.0.0.1:9222" in client._current_ws_url or "localhost:9222" in client._current_ws_url


async def test_connect_all_candidates_fail_emits_error(cdp_server):
    cdp_server.reject = True
    client = make_client(cdp_server)
    assert await client.connect("ws://10.0.0.9:9222/devtools/page/t1") is False
    assert not client.is_connected
    assert any("Connect failed" in str(a) for a in client.error.calls)


async def test_connect_missing_websockets_dependency(monkeypatch):
    monkeypatch.setitem(sys.modules, "websockets", None)  # import → ImportError
    client = make_client()
    assert await client.connect("ws://127.0.0.1:9222/devtools/page/t1") is False
    assert any("websockets" in str(a) for a in client.error.calls)


async def test_disconnect_stops_receiving(cdp_server):
    client = make_client(cdp_server)
    await client.connect("ws://10.0.0.9:9222/devtools/page/t1")
    task = client._receive_task
    await client.disconnect()
    assert client.is_connected is False and task.done()
    assert client.disconnected.calls and cdp_server.last_ws.closed
    assert client._pending == {}


# ── command send / receive ──

async def test_send_requires_connection(cdp_server):
    client = make_client(cdp_server)
    with pytest.raises(ConnectionError):
        await client.send("Page.navigate")


async def test_send_round_trip_and_no_reply_timeout(cdp_server):
    def responder(method, params, server):
        if method == "Stall":
            return "NO_REPLY", None
        if method == "Boom":
            return None, {"code": -32000, "message": "kaboom"}
        return {"value": params.get("x")}, None
    cdp_server.responder = responder
    client = make_client(cdp_server)
    await client.connect("ws://10.0.0.9:9222/devtools/page/t1")
    reply = await client.send("Echo", {"x": 7})
    assert reply["result"]["value"] == 7
    err_reply = await client.send("Boom")
    assert err_reply["error"]["message"] == "kaboom"
    with pytest.raises(TimeoutError):
        await client.send("Stall", timeout=0.05)
    assert client._pending == {}


async def test_events_dispatch_and_garbage_ignored(cdp_server):
    client = make_client(cdp_server)
    await client.connect("ws://10.0.0.9:9222/devtools/page/t1")
    seen = []
    client.events.add(seen.append)
    cdp_server.event("Page.loadEventFired", {"frameId": "f1"})
    cdp_server.last_ws.push("this is not json")
    for _ in range(20):
        if seen:
            break
        await asyncio.sleep(0.01)
    assert seen == [{"method": "Page.loadEventFired", "params": {"frameId": "f1"}}]
    client.events.remove(seen.append)


async def test_ws_close_marks_disconnected(cdp_server):
    client = make_client(cdp_server)
    await client.connect("ws://10.0.0.9:9222/devtools/page/t1")
    await cdp_server.last_ws.close()
    for _ in range(40):
        if not client.is_connected:
            break
        await asyncio.sleep(0.01)
    assert client.is_connected is False
    assert len(client.disconnected.calls) >= 1


# ── evaluate + DOM helpers ──

async def _connected(cdp_server, responder=None):
    if responder:
        cdp_server.responder = responder
    client = make_client(cdp_server)
    assert await client.connect("ws://10.0.0.9:9222/devtools/page/t1") is True
    return client


def _eval_responder(value=None, exception=None, fail=False):
    # responder returns the inner Runtime.evaluate object; handle() wraps it
    # in the {"id": n, "result": ...} envelope
    def responder(method, params, server):
        if method == "Runtime.evaluate":
            if fail:
                return None, {"code": -1, "message": "nope"}
            inner = {}
            if exception is not None:
                inner["exceptionDetails"] = exception
            else:
                inner["result"] = {"type": "string", "value": value}
            return inner, None
        return {"ok": True}, None
    return responder


async def test_evaluate_success_exception_and_failure(cdp_server):
    client = await _connected(cdp_server, _eval_responder(value="42"))
    assert await client.evaluate("21*2") == "42"  # value passes through verbatim
    cdp_server.responder = _eval_responder(exception={"text": "boom"})
    assert await client.evaluate("throw 1") is None
    cdp_server.responder = _eval_responder(fail=True)
    assert await client.evaluate("x") is None


async def test_dom_helpers_and_file_input(cdp_server):
    doc = {"nodeId": 7}

    def responder(method, params, server):
        if method == "DOM.getDocument":
            return {"root": doc}, None
        if method == "DOM.querySelector":
            return {"nodeId": 9 if "file" in params["selector"] else 0}, None
        if method == "DOM.querySelectorAll":
            return {"nodeIds": [9, 10]}, None
        if method == "DOM.setFileInputFiles":
            return ({"error": {"code": -1}}, None) if params["files"] == [] else ({}, None)
        return {"ok": True}, None
    client = await _connected(cdp_server, responder)
    assert (await client.get_document()) == doc
    assert await client.query_selector(7, "input[type='file']") == 9
    assert await client.query_selector(7, "div") is None
    assert await client.query_selector_all(7, "img") == [9, 10]
    assert await client.set_file_input_files(9, ["/tmp/a.png"]) is True

    async def doc_fail(method, params, server):
        return None, {"code": -1, "message": "gone"}
    cdp_server.responder = doc_fail
    assert await client.get_document() is None
    assert await client.query_selector(7, "img") is None
    assert await client.query_selector_all(7, "img") == []
    assert await client.set_file_input_files(9, ["/tmp/a.png"]) is False


async def test_attach_image_cdp_paths(tmp_path, cdp_server):
    img = tmp_path / "pic.png"
    img.write_bytes(b"\x89PNG")

    def responder(method, params, server):
        if method == "DOM.getDocument":
            return {"root": {"nodeId": 5}}, None
        if method == "DOM.querySelector":
            return {"nodeId": 11 if "file" in params["selector"] else 0}, None
        if method == "DOM.setFileInputFiles":
            # CDP error reply shape: {"id": n, "error": {...}} → 2nd return value
            if server.attach_fail:
                return None, {"code": -1, "message": "deny"}
            return {}, None
        return {"ok": True}, None
    cdp_server.attach_fail = False
    client = await _connected(cdp_server, responder)
    ok, msg = await client.attach_image_cdp(str(img))
    assert ok is True and "input" in msg and img.name in msg

    ok, msg = await client.attach_image_cdp(str(img), selectors=["div:not-matching"])
    assert ok is False and "File input not found" in msg

    cdp_server.responder = lambda m, p, s: ({"root": {"nodeId": 0}}, None) if m == "DOM.getDocument" else ({}, None)
    ok, msg = await client.attach_image_cdp(str(img))
    assert ok is False and "No root nodeId" in msg

    cdp_server.attach_fail = True
    cdp_server.responder = responder
    ok, msg = await client.attach_image_cdp(str(img))
    assert ok is False and "setFileInputFiles failed" in msg


async def test_highlight_and_clear_use_evaluate(cdp_server):
    def responder(method, params, server):
        if method == "Runtime.evaluate":
            # both scripts reference data-arena-highlight; clear uses querySelectorAll
            if "querySelectorAll" in params["expression"]:
                return {"result": {"value": {"cleared": 3}}}, None
            return {"result": {"value": {"found": True,
                                         "rect": {"x": 1, "y": 2, "width": 3, "height": 4}}}}, None
        return {"ok": True}, None
    client = await _connected(cdp_server, responder)
    hit = await client.highlight_element("#gen", color="#00ff00", duration_ms=300,
                                         caption="go")
    assert hit["found"] is True and hit["rect"]["width"] == 3
    assert await client.clear_highlights() == {"cleared": 3}


# ── fetch_tabs (async, aiohttp) ──

class _FakeResp:
    def __init__(self, items, status=200):
        self._items, self.status = items, status

    async def json(self):
        return self._items

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _FakeSession:
    def __init__(self, items, status=200, url_log=None):
        self._items, self._status, self.url_log = items, status, url_log

    def get(self, url, timeout=None):
        if self.url_log is not None:
            self.url_log.append(url)
        return _FakeResp(self._items, self._status)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


async def test_fetch_tabs_aiohttp_path(monkeypatch, cdp_server):
    import aiohttp
    urls = []

    class Session(_FakeSession):
        def __init__(self):
            super().__init__(RAW_TABS, url_log=urls)
    monkeypatch.setattr(aiohttp, "ClientSession", Session)
    monkeypatch.setattr(aiohttp, "ClientTimeout", lambda total=None: None)
    client = make_client(cdp_server)
    tabs = await client.fetch_tabs()
    assert {t.id for t in tabs} == {"t1", "t2"}
    assert any("/json/list" in u for u in urls)


async def test_fetch_tabs_falls_back_to_sync(monkeypatch, cdp_server):
    import aiohttp

    def boom(*args, **kwargs):
        raise RuntimeError("aiohttp down")
    monkeypatch.setattr(aiohttp, "ClientSession", boom)
    fallback = []
    monkeypatch.setattr(cdp_client, "fetch_tabs_sync",
                        lambda h, p: (fallback.append((h, p)) or
                                      ([TabInfo("t9", "T", "u", "ws")], "", [])))
    client = make_client(cdp_server)
    tabs = await client.fetch_tabs()  # aiohttp down → executor sync fallback
    assert [t.id for t in tabs] == ["t9"] and fallback == [("127.0.0.1", 9222)]
    assert not client.is_connected  # fetch_tabs never opens a ws


async def test_fetch_tabs_total_failure_emits_error(monkeypatch, cdp_server):
    import aiohttp
    monkeypatch.setattr(aiohttp, "ClientSession", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("down")))
    monkeypatch.setattr(cdp_client, "fetch_tabs_sync",
                        lambda h, p: ([], "Port 9222 not open", []))
    client = make_client(cdp_server)
    tabs = await client.fetch_tabs()
    assert tabs == []
    assert any("not open" in str(a) for a in client.error.calls)


# ── wrapper delegation to pure protocol ──

def test_tab_wrappers_delegate_to_pure():
    tabs = cdp_client._parse_tabs(RAW_TABS, preferred_host="127.0.0.1", preferred_port=9222)
    assert isinstance(tabs[0], TabInfo) and tabs[0].id == "t1"
    assert all(not t.url.startswith("chrome://newtab") for t in cdp_client._filter_real_tabs(tabs))
    norm = cdp_client._normalize_ws_url("ws://10.0.0.9:9222/devtools/page/t1", "127.0.0.1", 9222)
    assert norm.startswith("ws://127.0.0.1:9222")
    assert cdp_client._is_devtools_url("devtools://devtools/bundled/inspector.html") is True
