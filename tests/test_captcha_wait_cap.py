"""D-14R: the captcha wait ends at the user's `watcher_captcha_timeout_sec` (S3).

Real `handle_captcha`, real `wait_captcha_cleared`, a ctrl whose dialog never
clears. The caps are short and real (the raw knob drives the wait deadline, so
1 s means ~1 s); `asyncio.wait_for` bounds the suite, not the assertions.
"""

import asyncio
import time
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.core.models import UrlRow
from app.services import multi_page_dispatcher as mpd
from app.services import single_job_runner as sjr
from app.services.captcha.policy import WaitDeadline, pause_cap_seconds
from app.services.captcha.service import CaptchaCtx, CaptchaService, handle_captcha
from app.services.cooldown_service import FinishCtx
from tests.characterization.harness import make_block
from tests.test_captcha_service import FakeCtrl, make_info

URL = "https://arena.ai/image/direct"


class NeverClearsCtrl(FakeCtrl):
    """The dialog is still up on every poll (the wait can only end by stop/cap)."""

    async def is_security_dialog_visible(self):
        return True


def make_bridge(pool, session, config_dir):
    logs = []
    state = dict(session)
    bridge = SimpleNamespace(
        _cancel_requested=False,
        _page_pool=pool,
        config=SimpleNamespace(get_state=lambda k, d=None: state.get(k, d)),
        state=SimpleNamespace(prompt={"user_prompt": "p"},
                              recalculate_progress=lambda: None),
        _save_arena=lambda: None,
        _log=lambda m, l="info": logs.append((m, l)),
        _emit_pool_status=lambda: None,
        _emit_job_action_status=lambda action: logs.append(
            (getattr(action.block, "block_id", action.block), action.status)),
        job_started=SimpleNamespace(emit=lambda *a: None),
        job_finished=SimpleNamespace(emit=lambda *a: None),
        _get_action_blocks=lambda: [make_block("CHECK_SECURITY")],
        _logs=logs,
        _state=state,
    )
    svc = CaptchaService(str(config_dir), bridge._log)
    bridge._captcha_service = lambda: svc
    return bridge


def make_job(pool, bridge, tab_id="t1"):
    pool.add_page(make_info(tab_id))
    pool.mark_busy(tab_id, "j1")
    img = SimpleNamespace(id="img1", status="pending", error="", output_path="",
                          relative_path="pic.png", absolute_path="/tmp/pic.png",
                          assigned_url_id=None, attempt_count=0)
    owner = UrlRow.create(URL, tab_id=tab_id)
    return img, [owner]


def instant_sleep(monkeypatch):
    async def fake_sleep(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_dialog_that_never_clears_ends_at_the_cap(monkeypatch, isolated_config_dir):
    instant_sleep(monkeypatch)
    pool = PagePool()
    bridge = make_bridge(pool, {"watcher_enabled": True,
                                "watcher_captcha_timeout_sec": 1}, isolated_config_dir)
    img, _ = make_job(pool, bridge)
    ctrl = NeverClearsCtrl(visible_seq=[])
    ctx = CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1")
    outcome = await asyncio.wait_for(handle_captcha(ctx), timeout=30)
    assert outcome.status == "wait_timeout"
    assert "cap" in outcome.reason and "1s" in outcome.reason


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wait_timeout_maps_to_a_retryable_job_failure(monkeypatch, isolated_config_dir):
    from app.services.captcha.signals import SolveOutcome

    instant_sleep(monkeypatch)
    import app.services.cooldown_service as svc

    penalties = []
    monkeypatch.setattr(svc, "note_captcha_event", lambda *a, **k: penalties.append(1))
    # Unit half: the outcome maps to a RuntimeError carrying the cap.
    ctx = SimpleNamespace(bridge=SimpleNamespace())
    with pytest.raises(RuntimeError, match="300s cap"):
        sjr._handle_captcha_outcome(
            ctx, SolveOutcome(status="wait_timeout",
                              reason="Captcha wait timed out at the 300s cap"))
    # Vehicle half: a visible dialog + 1 s cap fails the image honestly.
    pool = PagePool()
    bridge = make_bridge(pool, {"watcher_enabled": True, "watcher_captcha_timeout_sec": 1,
                                "cooldown_enabled": True, "cooldown_min_seconds": 300},
                         isolated_config_dir)
    img, urls = make_job(pool, bridge)
    ctrl = NeverClearsCtrl(visible_seq=[])
    page_ctx = mpd.PageJobCtx(bridge=bridge, pool=pool, img=img, urls=urls,
                              tab_id="t1", ctrl=ctrl, client=None)
    _row, _corr, job_id, failed, err = await asyncio.wait_for(
        mpd._run_image_job(page_ctx), timeout=30)
    mpd._handle_result(mpd.ResultCtx(bridge=bridge, pool=pool, img=img, tab_id="t1",
                                     corr_id="c", job_id=job_id, failed=failed, err=err))
    assert failed is True
    assert "1s cap" in err
    assert img.status == "failed"
    assert img.attempt_count == 1  # started once, never re-bumped by the failure
    assert penalties == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stop_before_the_cap_still_yields_stopped(monkeypatch, isolated_config_dir):
    instant_sleep(monkeypatch)
    pool = PagePool()
    bridge = make_bridge(pool, {"watcher_enabled": True,
                                "watcher_captcha_timeout_sec": 10}, isolated_config_dir)
    img, _ = make_job(pool, bridge)
    ctrl = NeverClearsCtrl(visible_seq=[])
    t0 = time.monotonic()
    ctx = CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1",
                     stop=lambda: time.monotonic() - t0 > 0.2)
    outcome = await asyncio.wait_for(handle_captcha(ctx), timeout=30)
    assert outcome.status == "stopped"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_cap_moves_with_the_setting_without_a_restart(monkeypatch, isolated_config_dir):
    instant_sleep(monkeypatch)
    pool = PagePool()
    bridge = make_bridge(pool, {"watcher_enabled": True,
                                "watcher_captcha_timeout_sec": 1}, isolated_config_dir)
    img, _ = make_job(pool, bridge)

    async def capped_wait():
        ctrl = NeverClearsCtrl(visible_seq=[])
        ctx = CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1")
        t0 = time.monotonic()
        outcome = await asyncio.wait_for(handle_captcha(ctx), timeout=30)
        return outcome, time.monotonic() - t0

    first, dt1 = await capped_wait()
    assert first.status == "wait_timeout"
    assert 0.5 < dt1 < 6
    bridge._state["watcher_captcha_timeout_sec"] = 2
    second, dt2 = await capped_wait()
    assert second.status == "wait_timeout"
    assert 1.5 < dt2 < 8
    # The pause side of the same knob: clamped 10…3600, default 300.
    assert pause_cap_seconds(bridge) == 10  # knob 2 → low clamped
    bridge._state["watcher_captcha_timeout_sec"] = 5
    assert pause_cap_seconds(bridge) == 10
    bridge._state["watcher_captcha_timeout_sec"] = 9999
    assert pause_cap_seconds(bridge) == 3600
    bridge.config.get_state = lambda k, d=None: (_ for _ in ()).throw(RuntimeError("gone"))
    assert pause_cap_seconds(bridge) == 300


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wait_captcha_cleared_is_called_unchanged(monkeypatch, isolated_config_dir):
    instant_sleep(monkeypatch)
    import app.services.cooldown_service as svc

    calls = []

    async def spy(*args):
        calls.append(args)
        return True

    monkeypatch.setattr(svc, "wait_captcha_cleared", spy)
    pool = PagePool()
    bridge = make_bridge(pool, {"watcher_enabled": True,
                                "watcher_captcha_timeout_sec": 300}, isolated_config_dir)
    img, _ = make_job(pool, bridge)
    ctrl = FakeCtrl(visible_seq=[True, False])
    ctx = CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1")
    outcome = await handle_captcha(ctx)
    assert outcome.status == "manual"
    assert len(calls) == 1
    assert len(calls[0]) == 4  # ctrl, stop, timeout_sec, log — the pinned shape
    stop = calls[0][1]
    assert callable(stop) and stop() is False
    stop.deadline.start -= 1000  # travel past the cap without waiting for it
    assert stop() is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_cooldown_still_applies_after_a_wait_timeout(monkeypatch, isolated_config_dir):
    instant_sleep(monkeypatch)
    pool = PagePool()
    bridge = make_bridge(pool, {"watcher_enabled": True, "watcher_captcha_timeout_sec": 1,
                                "cooldown_enabled": True, "cooldown_min_seconds": 300},
                         isolated_config_dir)
    img, urls = make_job(pool, bridge)
    ctrl = NeverClearsCtrl(visible_seq=[])
    page_ctx = mpd.PageJobCtx(bridge=bridge, pool=pool, img=img, urls=urls,
                              tab_id="t1", ctrl=ctrl, client=None)
    _row, _corr, job_id, failed, err = await asyncio.wait_for(
        mpd._run_image_job(page_ctx), timeout=30)
    assert failed is True
    await mpd._finish_page_safely(FinishCtx(pool=pool, bridge=bridge, tab_id="t1",
                                            ctrl=ctrl, client=None))
    assert pool.get_page("t1").status == PageStatus.COOLDOWN
    assert pool.get_page("t1").pending_penalty == 0
