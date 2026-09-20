"""S2 / D-23 — Watcher OFF means ZERO captcha activity of any kind, counted.

One counting stack (pool wrapper, controller, stats, recordings, penalty
recorder, log lines) around the real `handle_captcha` and the real
`single_job_runner` block loop. OFF must leave every counter at 0; the ON
run is the positive control that makes the same counters non-zero through
the same path — a counting test without it would pass with the feature
deleted (RULE 16.0 / RULE 8).
Plan: docs/archive/2026-09-20-dynamic-urls-and-worker-debug/tdd-interfaces.md §S2 (9-11)
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.services import cooldown_service
from app.services import single_job_runner as sjr
from app.services.captcha.service import CaptchaCtx, CaptchaService, handle_captcha

pytestmark = pytest.mark.unit

ZERO = {"detect_probes": 0, "dialog_polls": 0, "overlays": 0, "mark_waiting": 0,
        "stats": 0, "recordings": 0, "penalties": 0, "shield_lines": 0, "captcha_solve_lines": 0}


class CountingPool(PagePool):
    def __init__(self):
        super().__init__()
        self.waiting_marks = 0

    def mark_waiting(self, tab_id, kind):
        self.waiting_marks += int(kind == "captcha")  # the generation mark is not captcha activity
        return super().mark_waiting(tab_id, kind)


class CountingCtrl:
    """A dialog that is visible forever; the stop predicate is the only way out."""

    def __init__(self):
        self.detect_probes = 0
        self.dialog_polls = 0
        self.overlays = 0
        self.cdp = SimpleNamespace(evaluate=self._evaluate)

    async def _evaluate(self, js):
        self.detect_probes += 1
        return {"visible": True, "kind": "recaptcha_enterprise", "sitekey": "6Lkey", "url": "https://arena.ai"}

    async def is_security_dialog_visible(self):
        self.dialog_polls += 1
        return True

    async def show_watcher_overlay(self, *a, **k):
        self.overlays += int(k.get("kind") == "captcha")  # the generation overlay is not captcha activity

    async def hide_watcher_overlay(self, *a, **k):
        return True

    async def capture_baseline(self):
        return {"output_count": 0, "output_srcs": []}

    async def wait_for_new_output(self, *a, **k):
        settler = getattr(self, "security_settler", None)
        if settler is not None:
            await settler()  # what the real poll loop does on each tick when installed
        return "completed", {"new_src": "https://x/new.png"}

    async def download_image(self, src):
        return True, b"z" * 200, "image/png"


class Stack(SimpleNamespace):
    def counters(self):
        return {
            "detect_probes": self.ctrl.detect_probes,
            "dialog_polls": self.ctrl.dialog_polls,
            "overlays": self.ctrl.overlays,
            "mark_waiting": self.pool.waiting_marks,
            "stats": self.stats_calls,
            "recordings": len(self.recording_calls),
            "penalties": len(self.penalty_calls),
            "shield_lines": sum(1 for m, _ in self.bridge._logs if "🛡" in m),
            "captcha_solve_lines": sum(1 for m, _ in self.bridge._logs if "CAPTCHA_SOLVE" in m),
        }


def build_stack(monkeypatch, config_dir, watcher_on: bool, stop_after_polls=2, stack=None):
    pool = CountingPool()
    pool.add_page(PageInfo(ws_url="ws://t1", tab_id="t1", title="T", url="https://arena.ai",
                           status=PageStatus.STEADY, is_connected=True))
    pool.mark_busy("t1", "j1")
    ctrl = CountingCtrl()
    logs, events = [], []
    session = {"watcher_enabled": watcher_on, "watcher_captcha_timeout_sec": 300,
               "cooldown_enabled": True, "cooldown_min_seconds": 300,
               "cooldown_captcha_penalty_seconds": 900}
    settings = SimpleNamespace(timeouts={"generation": 180},
                               output={"suffix": "_AI", "overwrite": False, "preserve_format": True,
                                       "unique_suffix_template": "{base}_AI_{n}{ext}"})
    bridge = SimpleNamespace(
        _cancel_requested=False, _page_pool=pool,
        config=SimpleNamespace(get_state=lambda k, d=None: session.get(k, d)),
        state=SimpleNamespace(settings=settings),
        _log=lambda m, l="info": logs.append((m, l)),
        _emit_pool_status=lambda: None,
        _emit_job_action_status=lambda a: events.append((getattr(a.block, "block_id", a.block), a.status, a.message)),
        _get_action_blocks=lambda: list(stack or []),
        highlight_rect=SimpleNamespace(emit=lambda p: None),
        _logs=logs, _events=events,
    )
    svc = CaptchaService(str(config_dir), bridge._log)
    st = Stack(pool=pool, ctrl=ctrl, bridge=bridge, svc=svc, stats_calls=0,
               recording_calls=[], penalty_calls=[])

    real_record = svc.stats.record

    def counted_record(event, site=""):
        st.stats_calls += 1
        return real_record(event, site)
    svc.stats.record = counted_record

    class SpyRecordings:
        async def start(self, ctrl_, rep):
            st.recording_calls.append("start")
            return None

        async def finish(self, rec, outcome, rep):
            st.recording_calls.append("finish")

        async def abort(self, rec, why):
            st.recording_calls.append("abort")
    svc.recordings = SpyRecordings()
    bridge._captcha_service = lambda: svc

    def counted_penalty(*a, **k):
        st.penalty_calls.append((a, k))
    monkeypatch.setattr(cooldown_service, "note_captcha_event", counted_penalty)

    real_sleep = asyncio.sleep

    async def _fast(_s):
        await real_sleep(0)  # yield so wait_for can still interrupt a runaway loop
    monkeypatch.setattr(asyncio, "sleep", _fast)

    # the dialog never clears: the stop predicate ends the wait after N polls
    polls = {"n": 0}

    def stop():
        polls["n"] += 1
        return polls["n"] > stop_after_polls
    st.stop = stop
    return st


def block(block_id):
    return SimpleNamespace(id=block_id.lower(), block_id=block_id, name=block_id, enabled=True,
                           required=False, timeout_ms=1000, selector="", extra={})


@pytest.mark.asyncio
async def test_watcher_off_produces_zero_captcha_side_effects(monkeypatch, isolated_config_dir):
    st = build_stack(monkeypatch, isolated_config_dir, watcher_on=False)
    outcome = await asyncio.wait_for(
        handle_captcha(CaptchaCtx(ctrl=st.ctrl, pool=st.pool, bridge=st.bridge, tab_id="t1", stop=st.stop)), 5)
    assert outcome.status == "out_of_scope"
    assert st.counters() == ZERO
    assert not hasattr(st.ctrl, "pause_clock")  # S3 forward-lock: no clock is ever installed OFF
    assert st.pool.get_page("t1").status == PageStatus.BUSY


@pytest.mark.asyncio
async def test_the_same_counters_do_count_when_on(monkeypatch, isolated_config_dir):
    """Positive control: identical stack, switch ON → the real wait path runs."""
    st = build_stack(monkeypatch, isolated_config_dir, watcher_on=True)
    outcome = await asyncio.wait_for(
        handle_captcha(CaptchaCtx(ctrl=st.ctrl, pool=st.pool, bridge=st.bridge, tab_id="t1", stop=st.stop)), 5)
    c = st.counters()
    assert outcome.status == "stopped"  # stop fired while the dialog was still up
    assert c["detect_probes"] >= 1 and c["overlays"] >= 1 and c["mark_waiting"] == 1
    assert c["stats"] >= 1 and c["recordings"] >= 2 and c["shield_lines"] >= 1
    assert c["captcha_solve_lines"] == 1


@pytest.mark.asyncio
async def test_zero_activity_holds_through_the_whole_job(monkeypatch, isolated_config_dir, tmp_path):
    """CHECK_SECURITY + SUBMIT + WAIT_OUTPUT + DOWNLOAD with a visible dialog and the switch OFF."""
    blocks = [block("CHECK_SECURITY"), block("SUBMIT"), block("WAIT_OUTPUT"), block("DOWNLOAD")]
    st = build_stack(monkeypatch, isolated_config_dir, watcher_on=False, stack=blocks)

    async def _ok(*a, **k):
        return True, "ok"
    st.ctrl.submit = _ok
    p = tmp_path / "in.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 120)
    img = SimpleNamespace(absolute_path=str(p), relative_path="in.png", status="pending",
                          output_path=None, error=None)
    ctx = sjr.JobCtx(bridge=st.bridge, ctrl=st.ctrl, client=None, tab_id="t1", img=img, urls=[],
                     job_id="j1", corr_id="c1", final_prompt="p [JOB-ID: c1]",
                     baseline={"output_count": 0, "output_srcs": []})
    hmap = sjr._handler_map()
    for b in blocks:
        await asyncio.wait_for(hmap[b.block_id](ctx, b), 5)
    assert st.counters() == ZERO
    assert ctx.new_src == "https://x/new.png" and len(ctx.file_bytes) == 200  # the job went through
    assert ("CHECK_SECURITY", "success", "Skipped (Watcher off)") in st.bridge._events
    assert not any(s == "running" and b == "CHECK_SECURITY" for b, s, _ in st.bridge._events)
