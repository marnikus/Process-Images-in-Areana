"""The RDP tab driver — Firefox tabs connect and automate (2026-09-22).

`RdpDriver` is the `CDPTransport`-compatible async driver the bridge and the
pool hold for Firefox tabs: `connect` on an `rdp://host:port#tab` handle,
`evaluate` decoding to the CDP value shape (`None` + `last_error[_kind]`
on failure), an honest attach refusal (`⛔ not in RDP`), and an
RDP-aware `diagnose_sync`. No persistent socket — "connected" means the
endpoint answers and the tab resolves.

RED at `a58f617`: `app.browser.rdp_driver` did not exist.
"""

import pytest

from tests.test_rdp import FakeDebuggerServer

pytestmark = pytest.mark.unit


@pytest.fixture
def firefox():
    srv = FakeDebuggerServer()
    try:
        yield srv
    finally:
        srv.close()


def _driver(port):
    from app.browser.rdp_driver import RdpDriver
    return RdpDriver(host="127.0.0.1", port=port)


def _handle(port, tab="11"):
    return f"rdp://127.0.0.1:{port}#{tab}"


async def test_connect_resolves_the_tab_and_reports_identity(firefox):
    drv = _driver(firefox.port)
    assert await drv.connect(_handle(firefox.port)) is True
    assert drv.is_connected is True
    assert drv._current_tab_id == "11"
    assert (drv._host, drv._port) == ("127.0.0.1", firefox.port)


async def test_connect_refuses_unknown_tabs_dead_ports_and_garbage(firefox):
    drv = _driver(firefox.port)
    assert await drv.connect(_handle(firefox.port, "999")) is False
    assert drv.is_connected is False and "999" in drv.last_error
    assert await drv.connect("rdp://127.0.0.1:1#11") is False
    assert await drv.connect("ws://127.0.0.1:9222/devtools/page/AAA") is False
    assert await drv.connect("garbage") is False


async def test_evaluate_decodes_to_the_cdp_value_shape(firefox):
    drv = _driver(firefox.port)
    await drv.connect(_handle(firefox.port))
    assert await drv.evaluate("DICT shape") == {"ok": True, "n": 1}
    assert await drv.evaluate("STR hi") == "hi"
    assert await drv.evaluate("UNDEF x") is None
    assert drv.last_error == "" and drv.last_error_kind == ""


async def test_evaluate_maps_errors_and_remembers_why(firefox):
    drv = _driver(firefox.port)
    await drv.connect(_handle(firefox.port))
    assert await drv.evaluate("BOOM oops") is None
    assert drv.last_error_kind == "js" and "boom happened" in drv.last_error
    drv._current_tab_id = "999"  # the tab closed mid-run
    assert await drv.evaluate("1+1") is None
    assert drv.last_error_kind == "transport" and "999" in drv.last_error


async def test_attach_refuses_honestly_and_send_raises(firefox):
    drv = _driver(firefox.port)
    await drv.connect(_handle(firefox.port))
    ok, reason = await drv.attach_image_cdp("/tmp/x.png")
    assert ok is False and "not in RDP" in reason
    with pytest.raises(ConnectionError):
        await drv.send("DOM.getDocument")


async def test_disconnect_clears_the_session(firefox):
    drv = _driver(firefox.port)
    await drv.connect(_handle(firefox.port))
    await drv.disconnect()
    assert drv.is_connected is False


def test_diagnose_names_firefox_and_counts_tabs(firefox):
    drv = _driver(firefox.port)
    diag = drv.diagnose_sync("127.0.0.1", firefox.port)
    assert "Firefox" in diag["summary"] and "2" in diag["summary"]
    assert diag["checks"][0]["port_open"] is True
    assert [t["id"] for t in diag["tabs"]] == ["11", "12"]
    dead = drv.diagnose_sync("127.0.0.1", 1)
    assert dead["checks"][0]["port_open"] is False


async def test_fetch_without_a_source_lists_its_own_endpoint(firefox):
    drv = _driver(firefox.port)
    tabs = await drv.fetch_tabs()
    assert [(t.browser, t.id) for t in tabs] == [("firefox", "11"), ("firefox", "12")]


async def test_fetch_with_a_source_delegates(firefox):
    drv = _driver(firefox.port)
    tabs, errors = [("delegated",)], ["firefox: down"]
    drv.set_tab_source(lambda: _async_result((tabs, errors)))
    assert await drv.fetch_tabs() is tabs
    assert drv._last_fetch_errors == errors


async def _async_result(value):
    return value
