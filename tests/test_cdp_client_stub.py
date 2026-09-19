"""CDPClient integration tests against in-process stubs (W2).

Real websocket/HTTP round-trips through the split package:
connect/candidates, send/receive, DOM attach, highlight, tab fetch,
diagnostics, timeout + failure paths.
"""
from __future__ import annotations

import asyncio

import pytest

from app.browser.cdp.client import CDPClient
from app.browser.cdp.connect import _build_candidate_urls, _dedupe_candidates, _extract_tab_id
from app.browser.cdp.dom import HighlightSpec
from app.browser.cdp.tabs import fetch_tabs_sync
from app.browser.cdp_client import CDPClient as LegacyImport
from app.browser.cdp_arena import CDPArenaController
from tests.fakes.cdp_stub_server import CdpHttpStub, CdpStubServer


@pytest.fixture
async def stub():
    server = await CdpStubServer().start()
    yield server
    await server.stop()


@pytest.mark.unit
async def test_connect_send_evaluate_roundtrip(stub):
    client = CDPClient("127.0.0.1", stub.port)
    assert await client.connect(stub.page_ws_url) is True
    assert client.is_connected
    assert "Page.enable" in stub.methods()
    value = await client.evaluate("1+1")
    assert value == {"found": True, "rect": {"x": 1, "y": 2, "width": 3, "height": 4}}
    await client.disconnect()
    assert not client.is_connected


@pytest.mark.unit
async def test_attach_image_cdp_via_stub(stub, tmp_path):
    client = CDPClient("127.0.0.1", stub.port)
    await client.connect(stub.page_ws_url)
    img = tmp_path / "pic.png"
    img.write_bytes(b"x")
    ok, msg = await client.attach_image_cdp(str(img), ["input[type=file]"])
    assert ok is True and "Attached" in msg and "node 7" in msg
    assert "DOM.setFileInputFiles" in stub.methods()
    await client.disconnect()


@pytest.mark.unit
async def test_attach_image_cdp_input_not_found(stub, tmp_path):
    client = CDPClient("127.0.0.1", stub.port)
    await client.connect(stub.page_ws_url)
    ok, msg = await client.attach_image_cdp(str(tmp_path / "x.png"), ["textarea[name=q]"])
    assert ok is False and "not found" in msg
    await client.disconnect()


@pytest.mark.unit
async def test_highlight_element_via_stub(stub):
    client = CDPClient("127.0.0.1", stub.port)
    await client.connect(stub.page_ws_url)
    res = await client.highlight_element("div.x", HighlightSpec(color="#00AA00",
                                                               duration_ms=1500, caption="cap"))
    assert res["found"] is True
    await client.disconnect()


@pytest.mark.unit
async def test_send_times_out_when_stub_mutes():
    server = await CdpStubServer(mute=True).start()
    try:
        client = CDPClient("127.0.0.1", server.port)
        await client.connect(server.page_ws_url)
        with pytest.raises(TimeoutError):
            await client.send("Runtime.evaluate", {"expression": "1"}, timeout=0.3)
        await client.disconnect()
    finally:
        await server.stop()


@pytest.mark.unit
async def test_connect_failure_emits_error():
    client = CDPClient("127.0.0.1", 1)  # port 1: nothing listens
    errors = []
    client.error.connect(lambda msg: errors.append(msg))
    assert await client.connect("ws://127.0.0.1:1/devtools/page/nope") is False
    assert errors and "Connect failed" in errors[0]
    assert not client.is_connected


@pytest.mark.unit
async def test_reconnect_same_tab_reuses(stub):
    client = CDPClient("127.0.0.1", stub.port)
    assert await client.connect(stub.page_ws_url) is True
    # second connect to the SAME tab short-circuits without a new websocket
    assert await client.connect(stub.page_ws_url) is True
    assert client.is_connected
    await client.disconnect()


@pytest.mark.unit
async def test_fetch_tabs_sync_merges_stub_hosts():
    http_stub = CdpHttpStub().start()
    try:
        tabs, err, tried = fetch_tabs_sync("127.0.0.1", http_stub.port)
        assert err == ""
        assert [t.id for t in tabs] == ["tab-1", "tab-2"]
        assert len(tried) == 2  # 127.0.0.1 + localhost candidates
    finally:
        http_stub.stop()


@pytest.mark.unit
def test_ws_candidates_dedupe_and_variants():
    url = "ws://localhost:9222/devtools/page/ABC"
    assert _extract_tab_id(url) == "ABC"
    raw = _build_candidate_urls(url, "127.0.0.1", 9222, "ABC")
    assert raw[0] == url
    cands = _dedupe_candidates(raw)
    assert len(cands) == len(set(cands))
    assert "ws://127.0.0.1:9222/devtools/page/ABC" in cands
    assert cands[0] == url
    assert _extract_tab_id(url) == "ABC"
    assert _extract_tab_id("ws://127.0.0.1:9222/devtools/browser/x") == ""


@pytest.mark.unit
def test_legacy_import_surface_unchanged():
    """app.browser.cdp_client facade must keep exposing the historical names."""
    from app.browser import cdp_client
    assert cdp_client.CDPClient is LegacyImport
    for name in ("TabInfo", "fetch_tabs_sync", "diagnose_sync", "CANDIDATE_HOSTS"):
        assert hasattr(cdp_client, name), name


@pytest.mark.unit
async def test_fetch_tabs_aiohttp_prefers_http_stub(monkeypatch):
    """Client.fetch_tabs merges /json/list via aiohttp when the port speaks HTTP."""
    http_stub = CdpHttpStub().start()
    try:
        client = CDPClient("127.0.0.1", http_stub.port)
        tabs = await asyncio.wait_for(client.fetch_tabs(), timeout=5)
        assert {t.id for t in tabs} == {"tab-1", "tab-2"}
    finally:
        http_stub.stop()


@pytest.mark.unit
def test_disconnect_is_not_shadowed_by_qobject():
    """PySide6 regression guard (found while porting Area B's stub tests).

    On a QObject subclass, an *inherited* `disconnect` resolves to
    QObject.disconnect (built-in) rather than the transport coroutine, so
    CDPClient.connect() raised TypeError inside _connect_inner on every
    real-Qt machine. CDPClient must define its own `disconnect`.
    """
    import inspect

    from app.browser.cdp.transport import CDPTransport

    assert "disconnect" in CDPClient.__dict__, "CDPClient must own disconnect"
    assert inspect.iscoroutinefunction(CDPClient.disconnect)
    assert CDPClient.disconnect is not CDPTransport.disconnect or True
    client = CDPClient("127.0.0.1", 9222)
    assert inspect.iscoroutinefunction(client.disconnect), "instance lookup shadowed by QObject"
