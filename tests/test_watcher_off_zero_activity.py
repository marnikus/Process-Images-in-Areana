"""D-23: Watcher OFF means zero captcha activity anywhere in the pipeline (S2).

RULE 8: real PagePool (counting subclass) + real `handle_captcha` / block loop;
only CDP/bridge/service-surface faked. The OFF tests assert one all-zeros dict;
the ON test is the positive control (RULE 16.0: a test that passes with the
feature deleted is not a test).
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.services import single_job_runner as sjr
from app.services.captcha.service import CaptchaCtx, handle_captcha
from tests.characterization.harness import make_block

URL = "https://arena.ai/image/direct"
VISIBLE_DETECT = {"visible": True, "kind": "recaptcha_enterprise",
                  "sitekey": "TESTSITEKEY", "url": URL}
ZEROS = {"detect_probes": 0, "dialog_polls": 0, "overlays": 0, "mark_waiting": 0,
         "stats": 0, "recordings": 0, "penalties": 0, "shield_lines": 0,
         "captcha_solve_lines": 0}


class CountingCtrl:
    """CDP + dialog + overlay + generation double; counts every captcha touch."""

    def __init__(self, visible_seq, detect=None):
        self._visible = list(visible_seq)
        self._detect = detect if detect is not None else dict(VISIBLE_DETECT)
        self.probes = []
        self.polls = 0
        self.overlay_calls = []
        self.settler_seen = None
        self.cdp = SimpleNamespace(evaluate=self._evaluate)

    async def _evaluate(self, js):
        self.probes.append(js)
        return json.dumps(self._detect)

    async def is_security_dialog_visible(self):
        self.polls += 1
        return self._visible.pop(0) if self._visible else False

    async def show_watcher_overlay(self, *a, **k):
        self.overlay_calls.append(k)

    async def hide_watcher_overlay(self, *a, **k):
        pass

    async def wait_for_new_output(self, *a, **k):
        self.settler_seen = hasattr(self, "security_settler")
        return "completed", {"new_src": "https://x/new.png"}

    async def download_image(self, src):
        return True, b"z" * 200, "image/png"


class CountingPool(PagePool):
    """Real pool that records mark_waiting kinds (generation vs captcha)."""

    def __init__(self):
        super().__init__()
        self.wait_marks = []

    def mark_waiting(self, tab_id, kind):
        self.wait_marks.append(kind)
        return super().mark_waiting(tab_id, kind)


def make_spy_service():
    stats_calls = []
    rec_calls = []

    async def _start(ctrl, rep):
        rec_calls.append("start")
        return None

    async def _finish(recorder, outcome, rep):
        rec_calls.append("finish")

    async def _abort(recorder, reason):
        rec_calls.append("abort")

    svc = SimpleNamespace(
        stats=SimpleNamespace(record=lambda e, s="": stats_calls.append(e)),
        recordings=SimpleNamespace(start=_start, finish=_finish, abort=_abort),
    )
    return svc, stats_calls, rec_calls


def make_bridge(pool, session, spy):
    logs = []
    events = []
    state = dict(session)
    return SimpleNamespace(
        _cancel_requested=False,
        _page_pool=pool,
        config=SimpleNamespace(get_state=lambda k, d=None: state.get(k, d)),
        _log=lambda m, l="info": logs.append((m, l)),
        _emit_pool_status=lambda: None,
        _emit_job_action_status=lambda action: events.append(
            (getattr(action.block, "block_id", action.block),
             action.status, action.message)),
        _captcha_service=lambda: spy,
        _logs=logs,
        _events=events,
        _state=state,
    )


def make_stack(session, visible_seq):
    pool = CountingPool()
    pool.add_page(PageInfo(ws_url="ws://t1", tab_id="t1", title="T-t1",
                           url=URL, status=PageStatus.STEADY, is_connected=True))
    pool.mark_busy("t1", "j1")
    svc, stats_calls, rec_calls = make_spy_service()
    bridge = make_bridge(pool, session, svc)
    ctrl = CountingCtrl(visible_seq)
    return SimpleNamespace(pool=pool, bridge=bridge, ctrl=ctrl,
                           stats_calls=stats_calls, rec_calls=rec_calls)


def spy_penalties(monkeypatch):
    import app.services.cooldown_service as svc

    calls = []

    def _note(*a, **k):
        calls.append(1)

    monkeypatch.setattr(svc, "note_captcha_event", _note)
    return calls


def collect(stack, penalty_calls):
    logs = stack.bridge._logs
    return {
        "detect_probes": len(stack.ctrl.probes),
        "dialog_polls": stack.ctrl.polls,
        "overlays": len([c for c in stack.ctrl.overlay_calls
                         if c.get("kind") == "captcha"]),
        "mark_waiting": len([k for k in stack.pool.wait_marks if k == "captcha"]),
        "stats": len(stack.stats_calls),
        "recordings": len(stack.rec_calls),
        "penalties": len(penalty_calls),
        "shield_lines": sum(1 for m, _ in logs if "🛡️" in m),
        "captcha_solve_lines": sum(1 for m, _ in logs if "CAPTCHA_SOLVE" in m),
    }


def instant_sleep(monkeypatch):
    async def fake_sleep(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_watcher_off_produces_zero_captcha_side_effects(monkeypatch):
    instant_sleep(monkeypatch)
    penalties = spy_penalties(monkeypatch)
    stack = make_stack({}, [True] * 50)
    ctx = CaptchaCtx(ctrl=stack.ctrl, pool=stack.pool, bridge=stack.bridge, tab_id="t1")
    outcome = await handle_captcha(ctx)
    assert outcome.status == "out_of_scope"
    assert collect(stack, penalties) == ZEROS
    assert not hasattr(stack.ctrl, "pause_clock")
    assert not hasattr(stack.ctrl, "pause_cap_s")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_same_counters_do_count_when_on(monkeypatch):
    instant_sleep(monkeypatch)
    penalties = spy_penalties(monkeypatch)
    stack = make_stack({"watcher_enabled": True}, [True, False])
    ctx = CaptchaCtx(ctrl=stack.ctrl, pool=stack.pool, bridge=stack.bridge, tab_id="t1")
    outcome = await handle_captcha(ctx)
    assert outcome.status == "manual"
    got = collect(stack, penalties)
    assert got["detect_probes"] >= 1
    assert got["overlays"] >= 1
    assert got["mark_waiting"] == 1
    assert got["stats"] >= 2
    assert got["shield_lines"] >= 1
    assert got["recordings"] >= 2
    assert got["penalties"] >= 1
    assert got["dialog_polls"] >= 1
    assert got["captcha_solve_lines"] >= 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_zero_activity_holds_through_the_whole_job(monkeypatch):
    instant_sleep(monkeypatch)
    penalties = spy_penalties(monkeypatch)
    stack = make_stack({}, [True] * 50)
    img = SimpleNamespace(status="pending", error="", output_path="",
                          relative_path="pic.png")
    ctx = sjr.JobCtx(bridge=stack.bridge, ctrl=stack.ctrl, client=None,
                     tab_id="t1", img=img, urls=[], job_id="j1", corr_id="c1",
                     final_prompt="p [JOB-ID: c1]",
                     baseline={"output_count": 0, "output_srcs": []})
    await sjr._handle_one_block(ctx, make_block("CHECK_SECURITY"))
    await sjr._handle_one_block(ctx, make_block("WAIT_OUTPUT", timeout_ms=1000))
    assert collect(stack, penalties) == ZEROS
    assert stack.ctrl.settler_seen is False
    assert hasattr(stack.ctrl, "security_settler") is False
    assert not hasattr(stack.ctrl, "pause_clock")
    assert not hasattr(stack.ctrl, "pause_cap_s")
    # The job itself completes untouched: both blocks succeed, bytes land.
    pairs = [(b, s) for b, s, _m in stack.bridge._events]
    assert ("CHECK_SECURITY", "success") in pairs
    assert ("WAIT_OUTPUT", "success") in pairs
    assert ctx.new_src == "https://x/new.png"
    assert len(ctx.file_bytes) == 200
    # The generation wait ran normally (its own overlay + pool mark, not captcha's).
    assert "generation" in [c.get("kind") for c in stack.ctrl.overlay_calls]
    assert "generation" in stack.pool.wait_marks
