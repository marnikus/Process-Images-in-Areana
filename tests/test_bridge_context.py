"""BridgeContext construction tests (R11/A6): same attrs, wired services."""

from types import SimpleNamespace

from app.persistence.config_manager import ConfigManager
from app.ui import bridge_context as ctx
from app.ui.bridge import Bridge
from app.ui.panels import watcher_captcha
from tests.characterization.fakes import FakeCDP


class Rec:
    def __init__(self):
        self.calls = []

    def __call__(self, *a):
        self.calls.append(a)

    def emit(self, *a):
        self.calls.append(a)


class SigCDP(FakeCDP):
    """FakeCDP whose signals actually fire into connected slots."""

    def __init__(self):
        super().__init__()
        self.connected = Rec()
        self.disconnected = Rec()
        self.error = Rec()
        for sig in (self.connected, self.disconnected, self.error):
            sig.connect = sig.calls.append


def make_bridge(tmp_path, cdp=None, **state):
    cfg = ConfigManager(str(tmp_path / "cfg"))
    for k, v in state.items():
        cfg.set_state(**{k: v})
    bridge = Bridge(config_manager=cfg, state_path=tmp_path / "arena.json",
                    cdp_client=cdp if cdp is not None else FakeCDP())
    return bridge, cfg


def test_construction_attr_snapshot(tmp_path):
    b, _ = make_bridge(tmp_path)
    assert b._run_state == "idle" and b._batch_future is None
    assert b._cancel_requested is False and b._pause_requested is False
    assert b._stop_after is False and b._exported_paths == {}
    assert b._bg_loop is None and b._bg_thread is None
    assert b._bg_lock is not None and b._bg_ready is not None
    assert b._watcher_loop_task is None
    assert (b._last_find_query, b._last_find_ts) == ("", 0.0)
    assert (b._last_connect_ws, b._last_connect_ts) == ("", 0.0)
    for flag in ("_find_in_progress", "_connect_in_progress",
                 "_auto_scan_running", "_ensure_running",
                 "_scan_in_progress"):
        assert getattr(b, flag) is False
    assert b._persist_ok is True and b._restore_note_done is False
    assert b._thumb_cache == {} and b._thumb_in_progress == set()
    assert b._thumb_executor is not None  # real pool (2 workers)
    assert b.undo_service is not None
    assert b._watcher is not None and b._watcher.config.enabled is False
    assert b._page_pool is not None
    assert (b._page_pool._host, b._page_pool._port) == ("127.0.0.1", 9222)


def test_watcher_controller_pool_pages(tmp_path):
    b, _ = make_bridge(tmp_path)
    controller = object()

    class Pool:
        def status_snapshot(self):
            return {"pages": [{"tab_id": "tab-a"}, {"tab_id": "tab-b"}]}

        def get_clients(self, tab_id):
            return (None, controller if tab_id == "tab-a" else None)

    b._page_pool = Pool()
    assert watcher_captcha.get_watcher_cdp_controllers(b) == [("tab-a", controller)]


def test_pool_endpoint_honored(tmp_path):
    b, _ = make_bridge(tmp_path, cdp_host="10.0.0.2", cdp_port=9333)
    assert (b._page_pool._host, b._page_pool._port) == ("10.0.0.2", 9333)


def test_pool_endpoint_bad_port_falls_back(tmp_path):
    b, _ = make_bridge(tmp_path, cdp_port="not-a-port")
    assert (b._page_pool._host, b._page_pool._port) == ("127.0.0.1", 9222)


def test_watcher_enabled_builds_configured_service(tmp_path):
    b, _ = make_bridge(tmp_path, watcher_enabled=True,
                       watcher_interval_ms=5000)
    assert b._watcher is not None
    assert b._watcher.config.enabled is True
    assert b._watcher.config.check_interval_ms == 5000


def test_service_failure_degrades_to_none(tmp_path, monkeypatch):
    import app.browser.page_pool as pool_mod
    import app.services.watcher as watcher_mod

    def boom(*_a, **_kw):
        raise RuntimeError("init exploded")
    monkeypatch.setattr(pool_mod, "PagePool", boom)
    monkeypatch.setattr(watcher_mod, "WatcherService", boom)
    b, _ = make_bridge(tmp_path, watcher_enabled=True)
    assert b._watcher is None and b._page_pool is None


def test_cdp_forwarding_wired(tmp_path):
    cdp = SigCDP()
    b, _ = make_bridge(tmp_path, cdp=cdp)
    b.connection_status = Rec()
    assert len(cdp.connected.calls) == 1  # forwarding lambda connected
    cdp.connected.calls[0]()
    cdp.error.calls[0]("boom")
    assert b.connection_status.calls == [("connected",), ("error",)]


def test_on_cdp_error_unit():
    logs, status = Rec(), Rec()
    fake = SimpleNamespace(_log=lambda m, l="info": logs(m, l),
                           connection_status=status)
    ctx.on_cdp_error(fake, "x" * 600)
    assert logs.calls and len(logs.calls[0][0]) <= 600
    assert "CDP error" in logs.calls[0][0] and logs.calls[0][1] == "error"
    assert status.calls == [("error",)]


def test_log_build_version_best_effort():
    logs = Rec()
    fake = SimpleNamespace(_log=lambda m, l="info": logs(m, l))
    ctx.log_build_version(fake)  # never raises (git/network absent ok)
    assert all("Build" in m for m, _ in logs.calls)


def test_captcha_service_seam_delegates(tmp_path):
    b, _ = make_bridge(tmp_path)
    svc = b._captcha_service()
    assert svc is not None
