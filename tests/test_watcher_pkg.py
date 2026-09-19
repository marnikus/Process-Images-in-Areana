"""Tests for watcher_pkg split — cdp, handlers, loop, jobs_ctrl."""
import time
import asyncio
from types import SimpleNamespace
import pytest
from app.services.watcher_config import WatcherConfig, WatcherState
from app.services.watcher_pkg.cdp import WatcherCDP
from app.services.watcher_pkg.jobs_ctrl import WatcherJobCtrl
from app.services.watcher_pkg.handlers import WatcherHandlers, HandlerDeps
from app.services.watcher_pkg.loop import WatcherLoop, LoopDeps
from app.services.captcha.signals import CaptchaSignal

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

def _make_handlers(cfg, state, probe, job_ctrl, logger, notify, solver=None):
    deps = HandlerDeps(config=cfg, state=state, cdp_probe=probe, job_ctrl=job_ctrl,
                       logger=logger, notifier=notify, captcha_solver=solver)
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


def test_cdp_normalizes_page_collections_and_getter_errors():
    pages = {"tab-a": FakeCDP(), "tab-b": None}
    probe = WatcherCDP(lambda: pages, lambda m,l: None)
    assert probe.get_pages() == [("tab-a", pages["tab-a"])]
    pair = FakeCDP()
    assert WatcherCDP(lambda: ("tab-p", pair), lambda m,l: None).get_pages()
    assert WatcherCDP(lambda: [("tab-l", pair)], lambda m,l: None).get_pages()
    broken = WatcherCDP(lambda: (_ for _ in ()).throw(RuntimeError("gone")), lambda m,l: None)
    assert broken.get_pages() == []


@pytest.mark.asyncio
async def test_cdp_structured_probe_and_overlay_fail_open():
    class Structured:
        async def evaluate(self, _script):
            return {"visible": True, "kind": "recaptcha_v2", "sitekey": "key"}
    cdp = SimpleNamespace(cdp=Structured())
    logs = []
    probe = WatcherCDP(lambda: cdp, lambda m,l: logs.append((m, l)))
    signal = await probe.detect_captcha(cdp)
    assert signal.solvable is True

    class Broken(FakeCDP):
        async def is_generating(self): raise RuntimeError("closed")
        async def show_watcher_overlay(self, *args, **kwargs): raise RuntimeError("closed")
        async def hide_watcher_overlay(self): raise RuntimeError("closed")
    broken = Broken()
    assert (await probe.check_generation(broken))[0] is False
    await probe.show_overlay(broken, "x", "captcha", 1)
    await probe.hide_overlay(broken)
    assert logs


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
async def test_handlers_solver_success_timeout_and_page_state():
    cfg = WatcherConfig(captcha_timeout_sec=1, generation_timeout_sec=1)
    state = WatcherState()
    cdp = FakeCDP()
    probe = WatcherCDP(lambda: cdp, lambda m,l: None)
    logs = []
    class Solver:
        def enabled(self): return True
        async def solve(self, request): return SimpleNamespace(status="solved", reason="")
    job_ctrl = WatcherJobCtrl(cfg, None)
    async def notify(): pass
    handlers = _make_handlers(cfg, state, probe, job_ctrl, lambda m,l: logs.append(m), notify, Solver())
    signal = CaptchaSignal(visible=True, kind="recaptcha_v2", sitekey="key")
    handlers._current_page_id = "tab-2"
    assert await handlers.handle_captcha(cdp, signal) is True
    assert handlers._page_states["tab-2"].waiting_kind is None
    handlers._current_page_id = "primary"
    state.waiting_kind = "captcha"
    state.waiting_since = time.time() - 5
    assert await handlers.handle_captcha(cdp, signal) is True
    assert await handlers.handle_generation(cdp, True, {"details": []}) is True
    state.waiting_since = time.time() - 5
    assert await handlers.handle_generation(cdp, True, {"details": []}) is True

    class DisabledSolver(Solver):
        def enabled(self): return False
    manual = _make_handlers(WatcherConfig(auto_pause_jobs=False), WatcherState(), probe,
                             WatcherJobCtrl(cfg, None), lambda m,l: logs.append(m), notify,
                             DisabledSolver())
    await manual.handle_captcha(cdp, signal)

    class FailedSolver(Solver):
        async def solve(self, request): return SimpleNamespace(status="failed", reason="busy")
    failed = _make_handlers(cfg, WatcherState(), probe, job_ctrl, lambda m,l: logs.append(m), notify,
                            FailedSolver())
    await failed.handle_captcha(cdp, signal)
    assert logs

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
    cfg = WatcherConfig(enabled=True)
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
    cfg = WatcherConfig(enabled=True)
    state = WatcherState()
    cdp = FakeCDP(captcha=True)
    probe = WatcherCDP(lambda: cdp, lambda m,l: None)
    job_ctrl = WatcherJobCtrl(cfg, None)
    async def notify(): pass
    handlers = _make_handlers(cfg, state, probe, job_ctrl, lambda m,l: None, notify)
    loop = _make_loop(cfg, state, probe, handlers, notify, lambda m,l: None)
    res = await loop.check_once()
    assert res["waiting_kind"] == "captcha"
