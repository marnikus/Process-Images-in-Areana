"""Extra coverage for watcher_pkg loop and watcher facade to reach 80%."""
import asyncio
import pytest
from app.services.watcher_config import WatcherConfig, WatcherState
from app.services.watcher_pkg.cdp import WatcherCDP
from app.services.watcher_pkg.jobs_ctrl import WatcherJobCtrl
from app.services.watcher_pkg.handlers import WatcherHandlers, HandlerDeps
from app.services.watcher_pkg.loop import WatcherLoop, LoopDeps
from app.services.watcher import WatcherService

class FakeCDP:
    def __init__(self, captcha=False, gen=False):
        self.captcha = captcha
        self.gen = gen
        self.overlay_shown = []
        self.overlay_hidden = 0
    async def is_security_dialog_visible(self):
        return self.captcha
    async def is_generating(self):
        return self.gen, {"details": []}
    async def show_watcher_overlay(self, msg, kind, timeout_sec):
        self.overlay_shown.append((msg, kind))
    async def hide_watcher_overlay(self):
        self.overlay_hidden += 1

def _make_handlers(cfg, state, probe, job_ctrl, logger, notify):
    deps = HandlerDeps(config=cfg, state=state, cdp_probe=probe, job_ctrl=job_ctrl, logger=logger, notifier=notify)
    return WatcherHandlers(deps)

def _make_loop(cfg, state, probe, handlers, notify, logger):
    deps = LoopDeps(config=cfg, state=state, cdp_probe=probe, handlers=handlers, notifier=notify, logger=logger)
    return WatcherLoop(deps)

@pytest.mark.asyncio
async def test_loop_notify_callbacks():
    cfg = WatcherConfig()
    state = WatcherState()
    probe = WatcherCDP(lambda: None, lambda m,l: None)
    job_ctrl = WatcherJobCtrl(cfg, None)
    async def notify(): pass
    handlers = _make_handlers(cfg, state, probe, job_ctrl, lambda m,l: None, notify)
    loop = _make_loop(cfg, state, probe, handlers, notify, lambda m,l: None)
    sync_calls = []
    async_calls = []
    def sync_cb(payload):
        sync_calls.append(payload)
    async def async_cb(payload):
        async_calls.append(payload)
    def bad_cb(payload):
        raise RuntimeError("bad")
    loop.add_callback(sync_cb)
    loop.add_callback(async_cb)
    loop.add_callback(bad_cb)
    await loop.notify()
    assert len(sync_calls)==1
    assert len(async_calls)==1

@pytest.mark.asyncio
async def test_loop_check_once_generation_and_clear():
    cfg = WatcherConfig()
    state = WatcherState()
    cdp = FakeCDP(captcha=False, gen=True)
    probe = WatcherCDP(lambda: cdp, lambda m,l: None)
    job_ctrl = WatcherJobCtrl(cfg, None)
    async def notify(): pass
    handlers = _make_handlers(cfg, state, probe, job_ctrl, lambda m,l: None, notify)
    loop = _make_loop(cfg, state, probe, handlers, notify, lambda m,l: None)
    res = await loop.check_once()
    assert res["waiting_kind"]=="generation"
    # now clear
    cdp2 = FakeCDP(captcha=False, gen=False)
    probe2 = WatcherCDP(lambda: cdp2, lambda m,l: None)
    handlers2 = _make_handlers(cfg, state, probe2, job_ctrl, lambda m,l: None, notify)
    loop2 = _make_loop(cfg, state, probe2, handlers2, notify, lambda m,l: None)
    # set waiting state
    state.waiting_kind="generation"
    state.waiting_since=0
    res2 = await loop2.check_once()
    assert res2["waiting_kind"] is None

def test_loop_start_stop_ensure():
    cfg = WatcherConfig(check_interval_ms=10)
    state = WatcherState()
    probe = WatcherCDP(lambda: None, lambda m,l: None)
    job_ctrl = WatcherJobCtrl(cfg, None)
    async def notify(): pass
    logs=[]
    handlers = _make_handlers(cfg, state, probe, job_ctrl, lambda m,l: logs.append(m), notify)
    loop = _make_loop(cfg, state, probe, handlers, notify, lambda m,l: logs.append(m))
    loop.start()
    # start again should be no-op
    loop.start()
    assert loop._running is True
    loop.stop()
    assert loop._running is False
    assert state.status=="idle"
    # ensure_task when disabled
    cfg.enabled=False
    loop.ensure_task()
    # enable and ensure creates task via running loop
    cfg.enabled=True
    # no running loop -> should not crash
    loop.ensure_task()
    # with running loop
    async def _run_ensure():
        loop.ensure_task()
        await asyncio.sleep(0.02)
        loop.stop()
    asyncio.run(_run_ensure())

@pytest.mark.asyncio
async def test_loop_run_handles_exceptions():
    cfg = WatcherConfig(check_interval_ms=5)
    state = WatcherState()
    class BadProbe:
        def get(self): return object()
        async def check_captcha(self, cdp): raise RuntimeError("probe fail")
        async def check_generation(self, cdp): return False, {}
    logs=[]
    handlers = _make_handlers(cfg, state, BadProbe(), WatcherJobCtrl(cfg, None), lambda m,l: logs.append(m), lambda: None)
    loop = _make_loop(cfg, state, BadProbe(), handlers, lambda: None, lambda m,l: logs.append(m))
    loop._running=True
    # run a few iterations then cancel
    async def _stop_soon():
        await asyncio.sleep(0.02)
        loop._running=False
    await asyncio.gather(loop._run(), _stop_soon())

@pytest.mark.asyncio
async def test_loop_run_cancelled():
    cfg = WatcherConfig(check_interval_ms=5)
    state = WatcherState()
    probe = WatcherCDP(lambda: None, lambda m,l: None)
    job_ctrl = WatcherJobCtrl(cfg, None)
    async def notify(): pass
    handlers = _make_handlers(cfg, state, probe, job_ctrl, lambda m,l: None, notify)
    loop = _make_loop(cfg, state, probe, handlers, notify, lambda m,l: None)
    loop._running=True
    task = asyncio.create_task(loop._run())
    await asyncio.sleep(0.01)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert state.status=="idle"

def test_watcher_service_facade():
    cfg = WatcherConfig(enabled=False)
    svc = WatcherService(config=cfg, cdp_controller_getter=lambda: FakeCDP(), job_runner_getter=lambda: None, logger=lambda m,l="info": None)
    # set getters
    svc.set_cdp_getter(lambda: FakeCDP())
    svc.set_job_runner_getter(lambda: object())
    svc.set_logger(lambda m,l="info": None)
    # update config enable
    svc.update_config(enabled=True, check_interval_ms=20)
    assert svc.config.enabled is True
    assert svc.config.check_interval_ms==20
    # get config/state
    c = svc.get_config()
    assert "enabled" in c
    s = svc.get_state()
    assert "status" in s
    # add callback and start/stop
    svc.add_callback(lambda payload: None)
    svc.start()
    svc.ensure_task()
    svc.stop()
    # update to disable
    svc.update_config(enabled=False)
    assert svc.config.enabled is False

@pytest.mark.asyncio
async def test_watcher_service_force_clear_and_check():
    cfg = WatcherConfig()
    svc = WatcherService(config=cfg, cdp_controller_getter=lambda: FakeCDP(), job_runner_getter=lambda: None, logger=lambda m,l="info": None)
    # force clear with cdp
    await svc.force_clear()
    assert svc.state.waiting_kind is None
    # check_once
    res = await svc.check_once()
    assert "status" in res
    # force clear with failing overlay
    class BadCDP:
        async def hide_watcher_overlay(self): raise RuntimeError("fail")
    svc2 = WatcherService(config=cfg, cdp_controller_getter=lambda: BadCDP(), job_runner_getter=lambda: None, logger=lambda m,l="info": None)
    await svc2.force_clear()
