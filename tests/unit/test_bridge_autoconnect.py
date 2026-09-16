"""Unit tests — Bridge auto-connect glue (spec 01, 03, 04) without Qt.

The real mixin, the real ConfigManager (tmp dir), the real PagePool and the real
AutoConnectService are exercised; only Chrome and the Qt signal are faked, so the
wiring that ships is the wiring under test (RULE 8).
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo
from app.persistence.config_manager import ConfigManager
from app.ui.autoconnect_pages import PageConnector
from app.ui.autoconnect_settings import clamp_int
from app.ui.bridge_autoconnect import AutoConnectMixin

def pool_ids(pool) -> list:
    """Sorted page ids in the pool — the pool is the source of truth."""
    return sorted(p["tab_id"] for p in pool.status_snapshot()["pages"])


def tab(pid: str, url: str = "https://arena.ai/c/1", title: str = "Arena", port: int = 9222) -> dict:
    return {"id": pid, "title": title, "url": url, "ws_url": f"ws://127.0.0.1:{port}/devtools/page/{pid}"}


class FakeSignal:
    def __init__(self):
        self.emitted: list = []

    def emit(self, *args):
        self.emitted.append(args)


class FakeCDP:
    """Stands in for CDPClient: records the endpoint asked for, serves canned tabs."""

    def __init__(self, tabs=None, host="127.0.0.1", port=9222):
        self.tabs = list(tabs or [])
        self.calls: list = []
        self.is_connected = False
        self._current_tab_id = ""
        self._host = host
        self._port = port
        self.connected_ws: list = []

    async def fetch_tabs(self, host=None, port=None, strict_host=True):
        self.calls.append({"host": host or self._host, "port": port or self._port, "strict_host": strict_host})
        return list(self.tabs)

    async def connect(self, ws_url: str) -> bool:
        self.connected_ws.append(ws_url)
        self.is_connected = True
        self._current_tab_id = ws_url.rsplit("/", 1)[-1]
        return True


class StubBridge(AutoConnectMixin):
    """Minimal Bridge: same collaborators, no QWebChannel."""

    def __init__(self, config_dir, cdp, pool=None, cdp_port=9223):
        self.config = ConfigManager(config_dir=str(config_dir))
        # user picked the arena port in Settings (spec 04)
        self.config.set_state(cdp_port=cdp_port)
        self.cdp = cdp
        self._page_pool = pool if pool is not None else PagePool()
        self.autoconnect_status = FakeSignal()
        self.logs: list = []
        self.scheduled: list = []
        self.pool_status_emissions = 0
        self.primary_connects: list = []
        self.pool_connects: list = []
        self.cooldown_restores: list = []
        self._autoconnect = None
        self._init_autoconnect()

    def _log(self, msg, level="info"):
        self.logs.append((msg, level))

    def _schedule_coro(self, coro):
        self.scheduled.append(coro)
        return None

    def _emit_pool_status(self):
        self.pool_status_emissions += 1

    def _restore_cooldown(self, tab_id):
        self.cooldown_restores.append(tab_id)

    async def _do_connect_tab(self, ws_url):
        self.primary_connects.append(ws_url)
        await self.cdp.connect(ws_url)
        self._add_pool_page(ws_url)

    async def _do_connect_page_pool(self, ws_url):
        self.pool_connects.append(ws_url)
        self._add_pool_page(ws_url)

    def _add_pool_page(self, ws_url):
        pid = ws_url.rsplit("/", 1)[-1]
        self._page_pool.add_page(PageInfo(tab_id=pid, ws_url=ws_url, title="Arena", url="https://arena.ai/c/1"))
        self._emit_pool_status()

    async def drain(self):
        """Await everything the bridge scheduled, like the bg loop would."""
        pending, self.scheduled = self.scheduled, []
        for coro in pending:
            try:
                await coro
            except Exception:
                pass


@pytest.fixture
def stub(tmp_path):
    cdp = FakeCDP(tabs=[tab("AAA"), tab("BBB"), tab("CCC", url="https://docs.python.org/3/")])
    bridge = StubBridge(tmp_path, cdp)
    yield bridge, cdp
    for coro in bridge.scheduled:
        coro.close()


@pytest.mark.unit
def test_clamp_int_handles_garbage():
    assert clamp_int("1200", 5000, 1000, 600000) == 1200
    assert clamp_int(None, 5000, 1000, 600000) == 5000
    assert clamp_int(10, 5000, 1000, 600000) == 1000


@pytest.mark.unit
def test_service_is_built_from_stored_settings(stub):
    bridge, _cdp = stub
    svc = bridge._autoconnect
    assert svc is not None
    assert bridge._autoconnect_loop is not None
    assert svc.config.patterns == ["arena.ai"]
    assert svc.config.endpoint == "127.0.0.1:9223"  # the port the user stored in Settings
    assert svc.config.enabled is True


@pytest.mark.unit
def test_set_autoconnect_config_persists_and_clamps(stub):
    bridge, _cdp = stub
    res = json.loads(bridge.set_autoconnect_config(json.dumps({
        "enabled": True, "url_pattern": " arena.ai , lmarena.ai ", "interval_ms": 20,
        "max_pages": 999, "connect_primary": False,
    })))
    assert res["ok"] is True
    assert bridge.config.get_state("autoconnect_url_pattern") == "arena.ai , lmarena.ai"
    assert bridge.config.get_state("autoconnect_interval_ms") == 1000  # clamped to min
    assert bridge.config.get_state("autoconnect_max_pages") == 100  # clamped to max
    assert bridge.config.get_state("autoconnect_primary") is False
    assert bridge._autoconnect.config.patterns == ["arena.ai", "lmarena.ai"]
    assert bridge._autoconnect.config.connect_primary is False
    # stored on disk, so the next app start behaves the same
    assert ConfigManager(config_dir=str(bridge.config.dir)).get_state("autoconnect_interval_ms") == 1000


@pytest.mark.unit
def test_set_autoconnect_config_rejects_broken_json(stub):
    bridge, _cdp = stub
    res = json.loads(bridge.set_autoconnect_config("{not json"))
    assert res["ok"] is False
    assert res["error"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_disabled_autoconnect_stops_a_running_loop(stub):
    bridge, _cdp = stub
    svc = bridge._autoconnect
    stopped: list = []

    async def fake_stop():
        stopped.append(True)

    loop = bridge._autoconnect_loop
    loop.stop = fake_stop
    loop._task = asyncio.Future()  # looks "running"
    bridge.set_autoconnect_config(json.dumps({"enabled": False}))
    assert bridge.config.get_state("autoconnect_enabled") is False
    await bridge.drain()
    assert stopped == [True]


@pytest.mark.unit
def test_enabling_schedules_the_loop_and_disabling_does_not(stub):
    bridge, _cdp = stub
    bridge.set_autoconnect_config(json.dumps({"enabled": False}))
    assert bridge.scheduled == []
    bridge.set_autoconnect_config(json.dumps({"enabled": True}))
    assert len(bridge.scheduled) == 1
    for coro in bridge.scheduled:
        coro.close()


@pytest.mark.unit
def test_scan_now_schedules_a_single_scan(stub):
    bridge, _cdp = stub
    res = json.loads(bridge.autoconnect_scan_now())
    assert res["ok"] is True
    assert len(bridge.scheduled) == 1
    for coro in bridge.scheduled:
        coro.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_boot_scan_links_every_matching_page_without_manual_add(stub):
    bridge, cdp = stub
    report = await bridge._autoconnect.scan_once()
    assert report["matched"] == 2
    assert sorted(pool_ids(bridge._page_pool)) == ["AAA", "BBB"]
    # spec 02: only the host:port from Settings is scanned, never a fallback host
    assert cdp.calls[-1] == {"host": "127.0.0.1", "port": 9223, "strict_host": True}
    # primary session points at the first matched page
    assert bridge.primary_connects and bridge.primary_connects[0].endswith("/AAA")
    assert bridge.pool_status_emissions > 0
    assert bridge.autoconnect_status.emitted, "UI must receive the scan report"
    payload = json.loads(bridge.autoconnect_status.emitted[-1][0])
    assert payload["pool_total"] == 2
    assert payload["url_pattern"] == "arena.ai"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_two_tabs_on_the_same_url_are_linked_as_two_pages(stub):
    bridge, _cdp = stub
    bridge.cdp.tabs = [tab("AAA", url="https://arena.ai/c/same"), tab("BBB", url="https://arena.ai/c/same")]
    report = await bridge._autoconnect.scan_once()
    assert report["matched"] == 2
    assert sorted(pool_ids(bridge._page_pool)) == ["AAA", "BBB"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_primary_session_is_not_stolen_when_already_linked(stub):
    bridge, cdp = stub
    cdp.is_connected = True
    cdp._current_tab_id = "ZZZ"
    await bridge._autoconnect.scan_once()
    assert bridge.primary_connects == []
    assert sorted(pool_ids(bridge._page_pool)) == ["AAA", "BBB"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rescan_never_redials_linked_pages(stub):
    bridge, _cdp = stub
    await bridge._autoconnect.scan_once()
    first = len(bridge.pool_connects)
    await bridge._autoconnect.scan_once()
    assert len(bridge.pool_connects) == first
    assert sorted(pool_ids(bridge._page_pool)) == ["AAA", "BBB"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_closed_tab_is_removed_on_next_scan(stub):
    bridge, cdp = stub
    await bridge._autoconnect.scan_once()
    cdp.tabs = [tab("AAA")]
    report = await bridge._autoconnect.scan_once()
    assert report["removed"] == ["BBB"]
    assert pool_ids(bridge._page_pool) == ["AAA"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_busy_tab_survives_a_scan_where_it_stopped_matching(stub):
    bridge, cdp = stub
    await bridge._autoconnect.scan_once()
    bridge._page_pool.mark_busy("BBB", "job-9")
    cdp.tabs = [tab("AAA")]
    report = await bridge._autoconnect.scan_once()
    assert report["removed"] == []
    assert sorted(pool_ids(bridge._page_pool)) == ["AAA", "BBB"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unreachable_port_is_logged_as_broken(stub):
    bridge, cdp = stub

    async def explode(**_kwargs):
        raise ConnectionError("Port 9223 not open on 127.0.0.1 (connection refused)")

    cdp.fetch_tabs = explode
    report = await bridge._autoconnect.scan_once()
    assert report["ok"] is False
    assert "not open" in report["error"]
    assert any(lvl == "warn" and "scan failed" in m for m, lvl in bridge.logs)
    assert pool_ids(bridge._page_pool) == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chrome_not_reachable_and_no_cdp_client_uses_sync_fetch(tmp_path, monkeypatch):
    from app.browser import cdp_client

    seen: list = []

    def fake_fetch(host, port, timeout=3.0, strict_host=True):
        seen.append((host, port, strict_host))
        return [], "Port 9223 not open", [f"http://{host}:{port}/json/list"]

    monkeypatch.setattr(cdp_client, "fetch_tabs_sync", fake_fetch)
    bridge = StubBridge(tmp_path, cdp=None)
    connector = PageConnector(bridge, bridge._autoconnect_config)
    with pytest.raises(ConnectionError):
        await connector.fetch()
    assert seen == [("127.0.0.1", 9223, True)]


@pytest.mark.unit
def test_get_autoconnect_config_reports_settings_and_state(stub):
    bridge, _cdp = stub
    payload = json.loads(bridge.get_autoconnect_config())
    assert payload["enabled"] is True
    assert payload["url_pattern"] == "arena.ai"
    assert payload["endpoint"] == "127.0.0.1:9223"
    assert payload["running"] is False
    assert bridge.get_autoconnect_status() == bridge.get_autoconnect_config()


@pytest.mark.unit
def test_preset_round_trip_keeps_every_autoconnect_field(stub):
    bridge, _cdp = stub
    bridge.set_autoconnect_config(json.dumps({
        "enabled": True, "url_pattern": "lmarena.ai", "interval_ms": 4000,
        "max_pages": 3, "connect_primary": False,
    }))
    doc = bridge._autoconnect_preset_doc()
    assert doc == {"enabled": True, "url_pattern": "lmarena.ai", "interval_ms": 4000,
                   "max_pages": 3, "connect_primary": False}
    other = StubBridge(bridge.config.dir, FakeCDP())
    other.config.set_state(autoconnect_url_pattern="something.else")
    other._restore_autoconnect_preset(doc)
    for coro in other.scheduled:
        coro.close()
    assert other._autoconnect.config.url_pattern == "lmarena.ai"
    assert other._autoconnect.config.interval_ms == 4000
    assert other._autoconnect.config.max_pages == 3
    assert other._autoconnect.config.connect_primary is False


@pytest.mark.unit
def test_restore_preset_survives_garbage(stub):
    bridge, _cdp = stub
    bridge._restore_autoconnect_preset({"interval_ms": "many", "max_pages": None})
    assert bridge._autoconnect.config.interval_ms >= 1000


@pytest.mark.unit
def test_shutdown_halts_the_loop(stub):
    bridge, _cdp = stub
    svc = bridge._autoconnect
    halted: list = []
    bridge._autoconnect_loop.halt = lambda: halted.append(True)
    bridge.shutdown_autoconnect()
    assert halted == [True]


@pytest.mark.unit
def test_boot_does_not_start_a_loop_when_disabled(tmp_path):
    cdp = FakeCDP(tabs=[tab("AAA")])
    bridge = StubBridge(tmp_path, cdp)
    bridge.config.set_state(autoconnect_enabled=False)
    bridge._start_autoconnect_boot()
    assert bridge.scheduled == []
    assert any("OFF" in m for m, _l in bridge.logs)


@pytest.mark.unit
def test_boot_schedules_the_loop_when_enabled(tmp_path):
    cdp = FakeCDP(tabs=[tab("AAA")])
    bridge = StubBridge(tmp_path, cdp)
    bridge._start_autoconnect_boot()
    assert len(bridge.scheduled) == 1
    assert any("Auto-connect on start" in m for m, _l in bridge.logs)
    for coro in bridge.scheduled:
        coro.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_loop_keeps_links_confirmed_until_stopped(stub):
    bridge, cdp = stub
    bridge.config.set_state(autoconnect_interval_ms=1000)
    bridge._autoconnect.reload_config(bridge.config.get_state)
    loop = bridge._autoconnect_loop
    loop._start_watcher = lambda: None  # no Chrome endpoint in unit tests
    task = asyncio.ensure_future(loop.run())
    await asyncio.sleep(0.05)
    assert sorted(pool_ids(bridge._page_pool)) == ["AAA", "BBB"]
    cdp.tabs.append(tab("DDD"))
    await asyncio.sleep(1.2)
    assert "DDD" in pool_ids(bridge._page_pool)
    await loop.stop()
    assert task.done()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_page_connector_link_reports_failure_when_pool_rejects(stub):
    bridge, _cdp = stub
    connector = PageConnector(bridge, bridge._autoconnect_config)

    async def reject(_ws_url):
        return None  # pool never received the page

    bridge._do_connect_page_pool = reject
    bridge.config.set_state(autoconnect_primary=False)  # isolate the pool link
    bridge._autoconnect.reload_config(bridge.config.get_state)
    assert await connector.link({"page_id": "AAA", "ws_url": "ws://127.0.0.1:9223/devtools/page/AAA"}) is False
    assert pool_ids(bridge._page_pool) == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_page_connector_survives_a_failing_primary_connect(stub):
    bridge, _cdp = stub
    connector = PageConnector(bridge, bridge._autoconnect_config)

    async def boom(_ws_url):
        raise RuntimeError("primary websocket refused")

    bridge._do_connect_tab = boom
    ok = await connector.link({"page_id": "AAA", "ws_url": "ws://127.0.0.1:9223/devtools/page/AAA"})
    assert ok is True  # the pool link still succeeded
    assert pool_ids(bridge._page_pool) == ["AAA"]
    assert any(lvl == "warn" and "primary failed" in m for m, lvl in bridge.logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_auto_linked_page_restores_its_persisted_cooldown(stub):
    bridge, _cdp = stub
    await bridge._autoconnect.scan_once()
    assert sorted(bridge.cooldown_restores) == ["AAA", "BBB"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_page_connector_needs_a_ws_url(stub):
    bridge, _cdp = stub
    connector = PageConnector(bridge, bridge._autoconnect_config)
    assert await connector.link({"page_id": "AAA", "ws_url": ""}) is False
    assert pool_ids(bridge._page_pool) == []


@pytest.mark.unit
def test_unlink_without_a_pool_is_false(stub):
    bridge, _cdp = stub
    connector = PageConnector(bridge, bridge._autoconnect_config)
    bridge._page_pool = None
    assert connector.unlink("AAA") is False


@pytest.mark.unit
def test_init_failure_is_logged_not_raised(stub):
    bridge, _cdp = stub
    bridge._page_pool = None

    def boom(*_a, **_kw):
        raise RuntimeError("pool gone")

    import app.ui.bridge_autoconnect as mod

    original = mod.PageLinker
    mod.PageLinker = boom
    try:
        bridge._init_autoconnect()
    finally:
        mod.PageLinker = original
    assert bridge._autoconnect is None
    assert any(lvl == "warn" and "init failed" in m for m, lvl in bridge.logs)


@pytest.mark.unit
def test_slots_report_failure_when_service_is_missing(stub):
    bridge, _cdp = stub
    bridge._autoconnect = None
    bridge._autoconnect_loop = None
    assert json.loads(bridge.autoconnect_scan_now())["ok"] is False
    bridge.shutdown_autoconnect()  # no service → no crash
    payload = json.loads(bridge.get_autoconnect_config())
    assert payload["running"] is False
    assert payload["url_pattern"] == "arena.ai"


@pytest.mark.unit
def test_boot_failure_is_logged(stub):
    bridge, _cdp = stub

    def boom(_get):
        raise RuntimeError("settings unreadable")

    bridge._autoconnect.reload_config = boom
    bridge._start_autoconnect_boot()
    assert bridge.scheduled == []
    assert any(lvl == "warn" and "boot failed" in m for m, lvl in bridge.logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_boot_run_links_pages_and_keeps_them_linked(tmp_path):
    """Full boot path: stored settings → loop → scan → pool, twice over (spec 01+03)."""
    cdp = FakeCDP(tabs=[tab("AAA"), tab("BBB", url="https://arena.ai/c/same")])
    bridge = StubBridge(tmp_path, cdp)
    bridge.config.set_state(autoconnect_interval_ms=1000, autoconnect_url_pattern="arena.ai")
    bridge._start_autoconnect_boot()
    loop = bridge._autoconnect_loop
    loop._start_watcher = lambda: None
    assert len(bridge.scheduled) == 1  # boot scheduled exactly one run
    task = asyncio.ensure_future(bridge.scheduled[0])
    bridge.scheduled.clear()
    await asyncio.sleep(0.05)
    assert pool_ids(bridge._page_pool) == ["AAA", "BBB"]
    assert cdp.is_connected and cdp._current_tab_id == "AAA"
    # a third page appears while running — the periodic pass picks it up, no Add click
    cdp.tabs.append(tab("DDD", url="https://arena.ai/c/third"))
    await asyncio.sleep(1.2)
    assert pool_ids(bridge._page_pool) == ["AAA", "BBB", "DDD"]
    # closing the app stops the loop promptly
    bridge.shutdown_autoconnect()
    await asyncio.sleep(0.05)
    assert task.done()
    assert loop.running is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_falls_back_to_a_second_read_when_the_client_says_nothing(stub, monkeypatch):
    """Empty from the async client is confirmed by a second read — never trusted blindly."""
    from app.browser import cdp_client

    bridge, cdp = stub
    cdp.tabs = []  # client answered, but with nothing
    connector = PageConnector(bridge, bridge._autoconnect_config)
    calls: list = []

    def fake_sync(host, port, timeout=3.0, strict_host=True):
        calls.append((host, port, strict_host))
        return ([], "", [f"http://{host}:{port}/json/list"])

    monkeypatch.setattr(cdp_client, "fetch_tabs_sync", fake_sync)
    assert await connector.fetch() == []
    assert calls == [("127.0.0.1", 9223, True)]  # only the configured endpoint (spec 02)
    assert pool_ids(bridge._page_pool) == []  # an empty scan reaps nothing


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_raises_when_the_endpoint_is_unreachable(stub, monkeypatch):
    """A refused port is broken, not empty (RULE 4) — so linked pages survive."""
    from app.browser import cdp_client

    bridge, cdp = stub
    cdp.tabs = []
    connector = PageConnector(bridge, bridge._autoconnect_config)

    def fake_sync(host, port, timeout=3.0, strict_host=True):
        return ([], f"Port {port} not open on {host} (connection refused)", [f"http://{host}:{port}/json/list"])

    monkeypatch.setattr(cdp_client, "fetch_tabs_sync", fake_sync)
    with pytest.raises(ConnectionError) as exc:
        await connector.fetch()
    assert "9223" in str(exc.value)
    assert "connection refused" in str(exc.value)
