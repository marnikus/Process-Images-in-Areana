"""Captcha choke point owns recording start/finish without changing outcome."""

from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.services.captcha.service import CaptchaCtx, CaptchaService, handle_captcha
from tests.test_captcha_service import FakeCtrl, instant_sleep, make_bridge, make_info


class RecordingSpy:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    async def start(self, ctrl, report):
        self.calls.append(("start", report["eid"], report["tab"]))
        if self.fail:
            return None
        return "recorder"

    async def finish(self, recorder, outcome, report=None):
        self.calls.append(("finish", recorder, outcome.status, bool(report)))

    async def abort(self, recorder, reason):
        self.calls.append(("abort", recorder, reason))

    async def note(self, tab_id, phase, outcome):
        self.calls.append(("note", tab_id, phase, outcome.status))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_manual_captcha_starts_and_finishes_recording(monkeypatch, isolated_config_dir):
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)
    service = CaptchaService(str(isolated_config_dir), bridge._log)
    spy = RecordingSpy()
    service.recordings = spy
    bridge._captcha_service = lambda: service
    ctrl = FakeCtrl(visible_seq=[True, False])

    outcome = await handle_captcha(CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1"))

    assert outcome.status == "manual"
    assert spy.calls[0][0] == "start"
    assert spy.calls[-1] == ("finish", "recorder", "manual", True)


@pytest.mark.unit
def test_manager_count_and_delete_delegate_to_store(tmp_path):
    from app.services.captcha_recording.manager import RecordingManager
    manager = RecordingManager(str(tmp_path))
    session_id = manager.store.create({"eid": "e1", "tab": "t", "source": "test",
                                       "url": "https://arena.ai", "kind": "v2"})["session_id"]
    assert manager.count_sessions() == 1
    assert manager.delete_session(session_id) == {"session_id": session_id, "deleted": True}
    assert manager.count_sessions() == 0


class _ProbeCDP:
    def __init__(self):
        self.calls = []

    async def send(self, method, params, timeout=5):
        self.calls.append(method)
        return {"result": {}}

    async def evaluate(self, script):
        self.calls.append("evaluate")
        return {"ok": True}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_manager_start_skips_when_recording_disabled(tmp_path):
    from app.services.captcha_recording.manager import RecordingManager
    manager = RecordingManager(str(tmp_path))
    manager.set_enabled(False)
    cdp = _ProbeCDP()
    outcome = await manager.start(SimpleNamespace(cdp=cdp), {"tab": "t1", "eid": "e1"})
    assert outcome is None
    assert cdp.calls == []  # disabled = no recorder, no CDP probes at all
    assert manager.count_sessions() == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_manager_start_records_when_enabled(tmp_path):
    from app.services.captcha_recording.manager import RecordingManager
    manager = RecordingManager(str(tmp_path))
    assert manager.is_enabled() is True
    recorder = await manager.start(SimpleNamespace(cdp=_ProbeCDP()),
                                   {"tab": "t1", "eid": "e1", "url": "https://arena.ai/c/1"})
    assert recorder is not None and manager.count_sessions() == 1
    await manager.abort(recorder, "test end")
    # the finished recording stays on disk, marked interrupted
    row = manager.list_sessions()[0]
    assert manager.count_sessions() == 1 and row["status"] == "interrupted"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_recording_start_failure_does_not_change_manual_flow(monkeypatch, isolated_config_dir):
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)
    service = CaptchaService(str(isolated_config_dir), bridge._log)
    service.recordings = RecordingSpy(fail=True)
    bridge._captcha_service = lambda: service

    outcome = await handle_captcha(CaptchaCtx(ctrl=FakeCtrl([True, False]), pool=pool,
                                               bridge=bridge, tab_id="t1"))
    assert outcome.status == "manual"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wait_failure_aborts_recording_and_reraises(monkeypatch, isolated_config_dir):
    """A crash inside the wait must abort the recording (never leave it open) and propagate."""
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)
    service = CaptchaService(str(isolated_config_dir), bridge._log)
    spy = RecordingSpy()
    service.recordings = spy
    bridge._captcha_service = lambda: service

    class CrashCtrl(FakeCtrl):
        async def show_watcher_overlay(self, *a, **k):
            raise KeyboardInterrupt()  # BaseException, not Exception → must still abort

    with pytest.raises(KeyboardInterrupt):
        await handle_captcha(CaptchaCtx(ctrl=CrashCtrl([True]), pool=pool, bridge=bridge, tab_id="t1"))
    assert spy.calls[0][0] == "start"
    assert spy.calls[-1][0] == "abort" and "KeyboardInterrupt" in spy.calls[-1][2]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_detect_without_url_falls_back_to_pool_page_url(monkeypatch, isolated_config_dir):
    from app.services.captcha.service import detect_signal

    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir)
    ctrl = FakeCtrl([True], detect={"visible": True, "kind": "recaptcha_v2", "sitekey": "k", "url": ""})
    sig = await detect_signal(CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1"))
    assert sig.page_url == "https://arena.ai/image/direct"  # pool page url used
    pool.get_page = lambda tab_id: (_ for _ in ()).throw(RuntimeError("pool gone"))
    sig = await detect_signal(CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1"))
    assert sig.page_url == ""  # fail open, never raises
