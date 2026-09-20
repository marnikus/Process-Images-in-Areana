"""S2 — D-23: Watcher OFF is ZERO captcha activity, counted, not assumed.

A counting stack (spy service, counting pool/ctrl, penalty spy) proves the
zero on the real `handle_captcha` / runner gates, and each counting test
carries a positive control (RULE 16.0: a test that passes with the feature
deleted is not a test). RED at base: with the switch OFF the whole flow
still runs — every counter is >= 1.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.services import cooldown_service
from app.services import single_job_runner as sjr
from app.services.captcha.service import CaptchaCtx, handle_captcha

pytestmark = pytest.mark.unit


class CountingPool:
    """Real-list behaviour for the two members the gates touch, counted."""

    def __init__(self):
        self.mark_waiting_calls = []

    def mark_waiting(self, tab_id, kind):
        self.mark_waiting_calls.append((tab_id, kind))

    def get_page(self, tab_id):
        return SimpleNamespace(url="https://arena.ai")


class CountingService:
    """Spy `_captcha_service`: stats + recordings count, never act."""

    def __init__(self):
        self.stats_calls = []
        self.recording_calls = []
        self.stats = SimpleNamespace(
            record=lambda event, site="": self.stats_calls.append((event, site)))
        self.recordings = self

    async def start(self, ctrl, rep):
        self.recording_calls.append("start")
        return "recorder"

    async def finish(self, recorder, outcome, rep=None):
        self.recording_calls.append("finish")

    async def abort(self, recorder, reason):
        self.recording_calls.append("abort")


class Stack:
    """One assembled fake boundary: ctrl + pool + bridge + spies."""

    def __init__(self, watcher_on: bool, visible_seq):
        self.pool = CountingPool()
        self.svc = CountingService()
        self.logs = []
        self.penalties = []
        state = {"watcher_enabled": watcher_on, "watcher_captcha_timeout_sec": 300,
                 "cooldown_captcha_penalty_seconds": 900}
        self.bridge = SimpleNamespace(
            config=SimpleNamespace(get_state=lambda k, d=None: state.get(k, d)),
            _page_pool=self.pool,
            _emit_pool_status=lambda: None,
            _log=lambda m, l="info": self.logs.append(m),
            _captcha_service=lambda: self.svc,
        )
        seq = list(visible_seq)
        ctrl = SimpleNamespace()
        ctrl.probes, ctrl.visible_calls, ctrl.overlay_calls = [], [], []

        async def evaluate(js):
            ctrl.probes.append(js)
            return json.dumps({"visible": True, "kind": "recaptcha_v2",
                               "sitekey": "sk", "url": "https://arena.ai"})

        async def dialog_visible():
            ctrl.visible_calls.append("visible")
            return seq.pop(0) if seq else False

        async def overlay(*a, **k):
            ctrl.overlay_calls.append(k)
            return True

        async def hide():
            return True

        ctrl.cdp = SimpleNamespace(evaluate=evaluate)
        ctrl.is_security_dialog_visible = dialog_visible
        ctrl.show_watcher_overlay = overlay
        ctrl.hide_watcher_overlay = hide
        self.ctrl = ctrl

    def counters(self):
        return {
            "detect_probes": len(self.ctrl.probes),
            "dialog_polls": len(self.ctrl.visible_calls),
            # generation overlays/marks are normal WAIT_OUTPUT work — only the
            # captcha-kind events count as captcha activity (D-23)
            "overlays": sum(1 for k in self.ctrl.overlay_calls if k.get("kind") == "captcha"),
            "mark_waiting": sum(1 for _t, kind in self.pool.mark_waiting_calls
                                if kind == "captcha"),
            "stats": len(self.svc.stats_calls),
            "recordings": len(self.svc.recording_calls),
            "penalties": len(self.penalties),
            "shield_lines": sum("🛡" in m for m in self.logs),
            "captcha_solve_lines": sum("CAPTCHA_SOLVE" in m for m in self.logs),
        }

    def captcha_ctx(self):
        return CaptchaCtx(ctrl=self.ctrl, pool=self.pool, bridge=self.bridge,
                          tab_id="t1", source="check-security",
                          log=lambda m, l="info": self.logs.append(m))


def instant_sleep(monkeypatch):
    async def _fast(_s):
        return None
    monkeypatch.setattr(asyncio, "sleep", _fast)


def spy_penalty(monkeypatch, stack):
    monkeypatch.setattr(cooldown_service, "note_captcha_event",
                        lambda *a, **k: stack.penalties.append((a, k)))


async def test_watcher_off_produces_zero_captcha_side_effects(monkeypatch):
    """RED at base: every counter is >= 1 (the flow runs despite the switch)."""
    instant_sleep(monkeypatch)
    stack = Stack(watcher_on=False, visible_seq=[True, True, False])
    spy_penalty(monkeypatch, stack)
    outcome = await asyncio.wait_for(handle_captcha(stack.captcha_ctx()), 5)
    assert (outcome.status, outcome.reason) == ("out_of_scope", "watcher off")
    assert stack.counters() == {k: 0 for k in stack.counters()}
    assert not hasattr(stack.ctrl, "pause_clock")  # S3 forward-lock: no pause either


async def test_the_same_counters_do_count_when_on(monkeypatch):
    """Positive control (RULE 16.0): the counters are alive on the ON path."""
    instant_sleep(monkeypatch)
    stack = Stack(watcher_on=True, visible_seq=[True, False])
    spy_penalty(monkeypatch, stack)
    outcome = await asyncio.wait_for(handle_captcha(stack.captcha_ctx()), 5)
    assert outcome.status == "manual"
    c = stack.counters()
    assert c["detect_probes"] >= 1 and c["overlays"] >= 1
    assert c["mark_waiting"] == 1 and c["stats"] >= 2 and c["recordings"] >= 2
    assert c["penalties"] == 1 and c["shield_lines"] >= 1 and c["captcha_solve_lines"] == 1


async def test_zero_activity_holds_through_the_whole_job(monkeypatch):
    """OFF + dialog UP through CHECK_SECURITY and WAIT_OUTPUT: zeros, job completes."""
    instant_sleep(monkeypatch)

    async def verified(ctx, src):
        return "completed", {}, src

    async def wait_done(*a, **k):
        return "completed", {"new_src": "https://x/new.png"}

    monkeypatch.setattr(sjr, "_verify_download", verified)
    stack = Stack(watcher_on=False, visible_seq=[])
    spy_penalty(monkeypatch, stack)
    stack.ctrl.wait_for_new_output = wait_done
    ctx = sjr.JobCtx(bridge=stack.bridge, ctrl=stack.ctrl, client=None, tab_id="t1",
                     img=SimpleNamespace(absolute_path="/tmp/i.png", relative_path="i.png",
                                         status="pending", output_path=None, error=None),
                     urls=[], job_id="j1", corr_id="c1", final_prompt="p",
                     baseline={"output_count": 0, "output_srcs": []})
    await sjr._handle_security(ctx, SimpleNamespace(block_id="CHECK_SECURITY"))
    status, _data, src = await sjr.wait_for_output(ctx, 5000)
    assert status == "completed" and src == "https://x/new.png"  # timeout untouched
    assert stack.counters() == {k: 0 for k in stack.counters()}
    # positive control: armed, the same block loop probes the dialog
    on_stack = Stack(watcher_on=True, visible_seq=[False, False])
    on_ctx = sjr.JobCtx(bridge=on_stack.bridge, ctrl=on_stack.ctrl, client=None,
                        tab_id="t1", img=ctx.img, urls=[], job_id="j1", corr_id="c1",
                        final_prompt="p", baseline={"output_count": 0, "output_srcs": []})
    await sjr._handle_security(on_ctx, SimpleNamespace(block_id="CHECK_SECURITY"))
    assert len(on_stack.ctrl.visible_calls) >= 1
