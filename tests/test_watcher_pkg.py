"""Tests for watcher_pkg split — cdp, handlers, loop, jobs_ctrl."""
import asyncio
import pytest
from app.services.watcher_config import WatcherConfig, WatcherState
from app.services.watcher_pkg.cdp import WatcherCDP
from app.services.watcher_pkg.jobs_ctrl import WatcherJobCtrl
from app.services.watcher_pkg.handlers import WatcherHandlers, HandlerDeps
from app.services.watcher_pkg.loop import WatcherLoop, LoopDeps

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

def test_cdp_get():
    w = WatcherCDP(lambda: FakeCDP(), lambda m,l: None)
    assert w.get() is not None
    w2 = WatcherCDP(None, lambda m,l: None)
    assert w2.get() is None

@pytest.mark.asyncio
async def test_cdp_check_captcha():
    cdp = FakeCDP(captcha=True)
    probe = WatcherCDP(lambda: cdp, lambda m,l: None)
    assert await probe.check_captcha(cdp) is True
    cdp2 = FakeCDP(captcha=False)
    assert await probe.check_captcha(cdp2) is False

@pytest.mark.asyncio
async def test_cdp_check_generation():
    cdp = FakeCDP(gen=True)
    probe = WatcherCDP(lambda: cdp, lambda m,l: None)
    is_gen, details = await probe.check_generation(cdp)
    assert is_gen is True

def test_jobs_ctrl():
    cfg = WatcherConfig(auto_pause_jobs=False)
    ctrl = WatcherJobCtrl(cfg, None)
    ctrl.pause()
    ctrl.resume()
    cfg2 = WatcherConfig(auto_pause_jobs=True)
    class FakeRunner:
        paused=False
        resumed=False
        def pause_run(self): self.paused=True
        def resume_run(self): self.resumed=True
    ctrl2 = WatcherJobCtrl(cfg2, lambda: FakeRunner())
    ctrl2.pause()
    ctrl2.resume()

@pytest.mark.asyncio
async def test_handlers_captcha():
    cfg = WatcherConfig()
    state = WatcherState()
    logs=[]
    cdp = FakeCDP(captcha=True)
    probe = WatcherCDP(lambda: cdp, lambda m,l: logs.append(m))
    job_ctrl = WatcherJobCtrl(cfg, None)
    async def notify(): pass
    handlers = _make_handlers(cfg, state, probe, job_ctrl, lambda m,l: logs.append(m), notify)
    res = await handlers.handle_captcha(cdp, True)
    assert res is True
    assert state.waiting_kind == "captcha"
    res2 = await handlers.handle_captcha(cdp, False)
    assert res2 is False

@pytest.mark.asyncio
async def test_handlers_generation():
    cfg = WatcherConfig()
    state = WatcherState()
    cdp = FakeCDP(gen=True)
    probe = WatcherCDP(lambda: cdp, lambda m,l: None)
    job_ctrl = WatcherJobCtrl(cfg, None)
    async def notify(): pass
    handlers = _make_handlers(cfg, state, probe, job_ctrl, lambda m,l: None, notify)
    res = await handlers.handle_generation(cdp, True, {"details": []})
    assert res is True
    assert state.waiting_kind == "generation"

@pytest.mark.asyncio
async def test_handlers_clear():
    cfg = WatcherConfig()
    state = WatcherState(waiting_kind="captcha", waiting_since=0)
    cdp = FakeCDP()
    probe = WatcherCDP(lambda: cdp, lambda m,l: None)
    job_ctrl = WatcherJobCtrl(cfg, None)
    async def notify(): pass
    handlers = _make_handlers(cfg, state, probe, job_ctrl, lambda m,l: None, notify)
    res = await handlers.handle_clear(cdp, False, False)
    assert res is True
    assert state.waiting_kind is None

@pytest.mark.asyncio
async def test_loop_check_once_no_cdp():
    cfg = WatcherConfig()
    state = WatcherState()
    probe = WatcherCDP(lambda: None, lambda m,l: None)
    job_ctrl = WatcherJobCtrl(cfg, None)
    async def notify(): pass
    handlers = _make_handlers(cfg, state, probe, job_ctrl, lambda m,l: None, notify)
    loop = _make_loop(cfg, state, probe, handlers, notify, lambda m,l: None)
    res = await loop.check_once()
    assert res["status"] == "watching"

@pytest.mark.asyncio
async def test_loop_check_once_captcha():
    cfg = WatcherConfig()
    state = WatcherState()
    cdp = FakeCDP(captcha=True)
    probe = WatcherCDP(lambda: cdp, lambda m,l: None)
    job_ctrl = WatcherJobCtrl(cfg, None)
    async def notify(): pass
    handlers = _make_handlers(cfg, state, probe, job_ctrl, lambda m,l: None, notify)
    loop = _make_loop(cfg, state, probe, handlers, notify, lambda m,l: None)
    res = await loop.check_once()
    assert res["waiting_kind"] == "captcha"
