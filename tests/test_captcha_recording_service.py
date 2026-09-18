"""Captcha choke point owns recording start/finish without changing outcome."""

import pytest

from app.browser.page_pool import PagePool
from app.services.captcha.service import CaptchaCtx, CaptchaService, handle_captcha
from tests.test_captcha_service import instant_sleep, make_bridge, make_info
from tests.test_captcha_solver import FakeCtrl


class RecordingSpy:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    async def start(self, ctrl, report):
        self.calls.append(("start", report["eid"], report["tab"]))
        if self.fail:
            return None
        return "recorder"

    async def finish(self, recorder, outcome):
        self.calls.append(("finish", recorder, outcome.status))

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
    assert spy.calls[-1] == ("finish", "recorder", "manual")


@pytest.mark.unit
def test_manager_count_and_delete_delegate_to_store(tmp_path):
    from app.services.captcha_recording.manager import RecordingManager
    manager = RecordingManager(str(tmp_path))
    session_id = manager.store.create({"eid": "e1", "tab": "t", "source": "test",
                                       "url": "https://arena.ai", "kind": "v2"})["session_id"]
    assert manager.count_sessions() == 1
    assert manager.delete_session(session_id) == {"session_id": session_id, "deleted": True}
    assert manager.count_sessions() == 0


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
