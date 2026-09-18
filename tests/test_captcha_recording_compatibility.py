"""Legacy recording bridge remains a fallback, never a competing lifecycle."""

import pytest

from app.browser.page_pool import PagePool
from app.services.captcha.service import CaptchaCtx, handle_captcha
from tests.test_captcha_service import instant_sleep, make_bridge, make_info
from tests.test_captcha_solver import FakeCtrl


class LegacyRecordingSpy:
    def __init__(self):
        self.calls = []

    async def start(self, ctrl, tab_id, detect):
        self.calls.append(("start", tab_id, detect["trigger"]))

    async def edge(self, ctrl, tab_id, note, snapshot=False):
        self.calls.append(("edge", tab_id, note, bool(snapshot)))

    def stop(self, tab_id, status, method):
        self.calls.append(("stop", tab_id, status, method))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_legacy_recorder_is_used_only_without_schema_v2_service(monkeypatch):
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, with_service=False)
    spy = LegacyRecordingSpy()
    bridge._recording_service = lambda: spy

    outcome = await handle_captcha(CaptchaCtx(
        ctrl=FakeCtrl(visible_seq=[True, False]), pool=pool, bridge=bridge,
        tab_id="t1", source="compatibility-test"))

    assert outcome.status == "manual"
    assert spy.calls[0] == ("start", "t1", "compatibility-test")
    assert spy.calls[-1] == ("stop", "t1", "manual", "manual")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_schema_v2_service_suppresses_legacy_automatic_recorder(
        monkeypatch, isolated_config_dir):
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(pool, isolated_config_dir, with_service=True)
    spy = LegacyRecordingSpy()
    bridge._recording_service = lambda: spy

    outcome = await handle_captcha(CaptchaCtx(
        ctrl=FakeCtrl(visible_seq=[True, False]), pool=pool, bridge=bridge,
        tab_id="t1"))

    assert outcome.status == "manual"
    assert spy.calls == []
