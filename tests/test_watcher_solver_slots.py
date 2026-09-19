"""WatcherSolverMixin — Captcha Watcher slots: lifecycle, key hygiene, pool seams.

RULE 8: real mixin + real key store + real CaptchaWatcher; only the bg-loop
scheduler and the SDK client are faked. Also pins the Watcher ON/OFF →
solver coupling in WatcherCaptchaMixin.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.persistence.config_manager import ConfigManager
from app.services.captcha.key_store import CaptchaKeyStore
from app.ui.panels import watcher_solver as ws
from app.ui.panels.watcher_captcha import WatcherCaptchaMixin
from app.ui.panels.watcher_solver import WatcherSolverMixin

pytestmark = pytest.mark.unit

KEY = "abcdefghij1234567890"


class Host(WatcherSolverMixin, WatcherCaptchaMixin):
    pass


def make_host(cfg, **attrs):
    host = Host()
    host.config = cfg
    host.logs = []
    host._log = lambda m, l="info": host.logs.append((m, l))
    host._watcher = None
    host.scheduled = []
    for k, v in attrs.items():
        setattr(host, k, v)
    return host


@pytest.fixture
def cfg(isolated_config_dir):
    return ConfigManager(str(isolated_config_dir))


@pytest.fixture
def no_bg_loop(monkeypatch):
    """Capture coroutines instead of running them on a bg thread."""
    def fake_schedule(bridge, coro):
        bridge.scheduled.append(coro)
        coro.close()
        return None
    monkeypatch.setattr(ws, "schedule_coro", fake_schedule)
    import app.ui.panels.watcher_captcha as wc
    monkeypatch.setattr(wc, "schedule_coro", fake_schedule)
    return fake_schedule


def test_key_slots_store_locally_and_mask(cfg, no_bg_loop):
    host = make_host(cfg)
    assert json.loads(host.get_captcha_api_key()) == {"ok": True, "has_key": False, "masked_key": ""}
    assert json.loads(host.set_captcha_api_key("short"))["ok"] is False
    saved = json.loads(host.set_captcha_api_key(f"  {KEY}  "))
    assert saved == {"ok": True, "has_key": True, "masked_key": "abcd****7890"}
    assert KEY not in json.dumps(host.logs)  # raw key never logged
    assert CaptchaKeyStore(cfg.dir).load().api_key == KEY  # same file as the legacy slot
    assert json.loads(host.get_captcha_status())["masked_key"] == "abcd****7890"
    assert json.loads(host.set_captcha_api_key(""))["has_key"] is False
    assert CaptchaKeyStore(cfg.dir).load().api_key == ""


def test_start_requires_key_then_schedules_loop(cfg, no_bg_loop):
    host = make_host(cfg)
    assert json.loads(host.watcher_start()) == {"ok": False, "running": False, "error": "no api key"}
    assert any("will NOT solve" in m for m, _ in host.logs)
    host.set_captcha_api_key(KEY)
    res = json.loads(host.watcher_start())
    assert res["ok"] is True and len(host.scheduled) == 1
    assert host.scheduled[0].cr_code.co_name == "run_forever"
    status = json.loads(host.watcher_status())
    assert status["ok"] is True and status["has_key"] is True and status["running"] is False
    assert json.loads(host.watcher_stop()) == {"ok": True, "running": False}
    bare = make_host(cfg)
    assert json.loads(bare.watcher_stop()) == {"ok": True, "running": False}  # never built → noop


def test_watcher_switch_drives_the_solver(cfg, no_bg_loop):
    from app.services.watcher import WatcherConfig, WatcherService
    host = make_host(cfg, _watcher=WatcherService(config=WatcherConfig(enabled=False, check_interval_ms=100),
                                                  logger=lambda m, l="info": None))
    host.set_captcha_api_key(KEY)
    res = json.loads(host.start_watcher())
    assert res["ok"] is True and res["solver"]["ok"] is True
    assert [c.cr_code.co_name for c in host.scheduled] == ["run_forever"]
    host.stop_watcher()
    assert json.loads(host.set_watcher_config(json.dumps({"enabled": True})))["ok"] is True
    assert len(host.scheduled) == 2  # config save with enabled=True starts the solver again
    cfg.set_state(watcher_enabled=True)
    host._watcher = None
    host.get_watcher_config()  # UI boot with Watcher ON → solver follows
    assert len(host.scheduled) == 3


def test_balance_slot_schedules_job_and_updates_status(cfg, monkeypatch):
    host = make_host(cfg)
    assert json.loads(host.captcha_balance())["error"] == "no api key"
    host.set_captcha_api_key(KEY)
    monkeypatch.setattr(ws, "schedule_coro", lambda bridge, coro: asyncio.run(coro))

    class Sdk:
        async def balance(self):
            return 4.25

    monkeypatch.setattr(ws, "make_solver", lambda bridge: SimpleNamespace(
        has_key=True, balance=Sdk().balance))
    assert json.loads(host.captcha_balance()) == {"ok": True, "pending": True}
    assert json.loads(host.watcher_status())["balance"] == 4.25
    assert any("balance $4.25" in m for m, _ in host.logs)
    monkeypatch.setattr(ws, "make_solver", lambda bridge: None)
    host.captcha_balance()
    assert any("unavailable" in m for m, _ in host.logs)


def test_pool_seams_only_touch_connected_pool_pages(cfg):
    pool = PagePool()
    pool.add_page(PageInfo(ws_url="ws://a", tab_id="a", url="https://arena.ai/a",
                           status=PageStatus.STEADY, is_connected=True))
    pool.add_page(PageInfo(ws_url="ws://b", tab_id="b", url="https://arena.ai/b"))
    pool.get_page("b").is_connected = False
    host = make_host(cfg, _page_pool=pool, cdp=SimpleNamespace(_current_tab_id="z", is_connected=True,
                                                               evaluate=None))
    assert ws.pool_tabs(host) == [{"id": "a", "url": "https://arena.ai/a"}]
    assert ws.pool_tabs(make_host(cfg)) == []

    class Client:
        is_connected = True

        async def evaluate(self, js):
            return {"js": js}

    pool.register_client("a", Client(), None)
    assert asyncio.run(ws.evaluate_on_tab(host, "a", "1+1")) == {"js": "1+1"}
    assert asyncio.run(ws.evaluate_on_tab(host, "nope", "1+1")) is None

    async def main_eval(js):
        return "main"
    host.cdp.evaluate = main_eval
    assert asyncio.run(ws.evaluate_on_tab(host, "z", "1")) == "main"  # main client fallback by tab id


def test_status_signal_is_optional_and_watcher_is_cached(cfg):
    host = make_host(cfg)
    ws.on_solver_status(host, {"running": False})  # no signal attr → silently ignored
    emitted = []
    host.captcha_watcher_status = SimpleNamespace(emit=emitted.append)
    ws.on_solver_status(host, {"running": True})
    assert json.loads(emitted[0]) == {"running": True}
    assert ws.captcha_watcher(host) is ws.captcha_watcher(host)
    assert ws.make_solver(host) is None
    host.set_captcha_api_key(KEY)
    assert ws.make_solver(host).has_key is True


def test_slots_degrade_to_error_json(cfg, monkeypatch):
    host = make_host(cfg)

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(ws, "solver_start", boom)
    monkeypatch.setattr(ws, "solver_stop", boom)
    monkeypatch.setattr(ws, "captcha_watcher", boom)
    monkeypatch.setattr(ws, "save_api_key", boom)
    monkeypatch.setattr(ws, "load_api_key", boom)
    for slot in (host.watcher_start, host.watcher_stop, host.watcher_status, host.captcha_balance,
                 host.get_captcha_api_key):
        assert json.loads(slot()) == {"ok": False, "error": "boom"}
    assert json.loads(host.set_captcha_api_key("x")) == {"ok": False, "error": "boom"}
    assert ws.solver_follow(host, True) is None  # never raises
