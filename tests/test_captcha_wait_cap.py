"""S3 — D-14R end to end: the captcha wait is capped (RED at base: it hangs).

Real `handle_captcha` / `_run_security_captcha`, real `wait_captcha_cleared`
(pinned unedited by tests/test_cooldown_service.py:604-618 — the cap is
composed into the `stop` predicate it already accepts), a dialog that never
clears, and `_POLL_SEC = 0` so the poll spins without wall sleeps. The cap
minimum is lowered by patching the policy constant (the clamp itself is
exercised by the cap-seconds tests) so caps of 1–2 s stay unit-fast.

RED at base: the wait never ends — `asyncio.wait_for(..., 5)` raises
TimeoutError, which IS the defect (owner: "D-14 should be capped").
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.services import cooldown_service
from app.services import single_job_runner as sjr
from app.services.captcha import policy
from app.services.captcha.service import CaptchaCtx, handle_captcha

pytestmark = pytest.mark.unit

DETECT = json.dumps({"visible": True, "kind": "recaptcha_v2",
                     "sitekey": "sk", "url": "https://arena.ai"})


class Stack:
    """A Watcher-ON boundary with a never-clearing dialog + spies."""

    def __init__(self, cap_sec=1, visible=True, stop=None):
        self.state = {"watcher_enabled": True, "watcher_captcha_timeout_sec": cap_sec,
                      "cooldown_captcha_penalty_seconds": 900}
        self.logs, self.penalties, self.stats = [], [], []
        self.overlay = []
        settings = SimpleNamespace(provider="recaptcha", key_for=lambda p: "sk-abc")
        svc = SimpleNamespace(
            stats=SimpleNamespace(record=lambda e, s="": self.stats.append(e)),
            keys=SimpleNamespace(load=lambda: settings),
            recordings=SimpleNamespace(
                start=self._start, finish=self._finish, abort=self._abort))
        self.bridge = SimpleNamespace(
            config=SimpleNamespace(get_state=lambda k, d=None: self.state.get(k, d)),
            _page_pool=SimpleNamespace(mark_waiting=lambda *a: None),
            _emit_pool_status=lambda: None,
            _log=lambda m, l="info": self.logs.append(m),
            _captcha_service=lambda: svc,
        )
        if isinstance(visible, bool):
            async def dialog_visible():
                return visible  # constant — a bool never "runs out"
        else:
            seq = list(visible)

            async def dialog_visible():
                return seq.pop(0) if seq else False

        async def overlay(text, kind=None, timeout_sec=None, sub=None):
            self.overlay.append({"text": text, "kind": kind,
                                 "timeout_sec": timeout_sec, "sub": sub})
            return True

        async def hide():
            return True

        self.ctrl = SimpleNamespace(
            cdp=SimpleNamespace(evaluate=self._detect),
            is_security_dialog_visible=dialog_visible,
            show_watcher_overlay=overlay,
            hide_watcher_overlay=hide,
        )
        self.stop = stop

    async def _detect(self, js):
        return DETECT

    async def _start(self, ctrl, rep):
        return "rec"

    async def _finish(self, rec, outcome, rep=None):
        return None

    async def _abort(self, rec, reason):
        return None

    def captcha_ctx(self):
        return CaptchaCtx(ctrl=self.ctrl, pool=self.bridge._page_pool,
                          bridge=self.bridge, tab_id="t1", source="check-security",
                          stop=self.stop, log=lambda m, l="info": self.logs.append(m))


@pytest.fixture
def fast_poll(monkeypatch):
    monkeypatch.setattr(cooldown_service, "_POLL_SEC", 0)
    monkeypatch.setattr(policy, "PAUSE_MIN_S", 1)  # unit-fast caps; clamp tested apart
    monkeypatch.setattr(policy, "PAUSE_MAX_S", 3600)


def spy_penalty(monkeypatch, stack):
    monkeypatch.setattr(cooldown_service, "note_captcha_event",
                        lambda *a, **k: stack.penalties.append((a, k)))


async def test_a_dialog_that_never_clears_ends_at_the_cap(fast_poll, monkeypatch):
    stack = Stack(cap_sec=1)
    spy_penalty(monkeypatch, stack)
    t0 = asyncio.get_event_loop().time()
    outcome = await asyncio.wait_for(handle_captcha(stack.captcha_ctx()), 5)
    elapsed = asyncio.get_event_loop().time() - t0
    assert outcome.status == "wait_timeout"
    assert "1" in outcome.reason and "cap" in outcome.reason
    assert 0.5 <= elapsed < 4.0


async def test_wait_timeout_maps_to_a_retryable_job_failure(fast_poll, monkeypatch):
    stack = Stack(cap_sec=1)
    spy_penalty(monkeypatch, stack)
    outcome = await asyncio.wait_for(handle_captcha(stack.captcha_ctx()), 5)
    ctx = SimpleNamespace(bridge=SimpleNamespace(_log=lambda *a, **k: None))
    with pytest.raises(RuntimeError) as exc:
        sjr._handle_captcha_outcome(ctx, outcome)
    assert "cap" in str(exc.value)      # honest, retryable — not a cancel
    assert stack.penalties == []          # no captcha penalty on the timeout path


async def test_stop_before_the_cap_still_yields_stopped(fast_poll, monkeypatch):
    stack = Stack(cap_sec=10, stop=lambda: True)  # operator stop wins earlier
    spy_penalty(monkeypatch, stack)
    outcome = await asyncio.wait_for(handle_captcha(stack.captcha_ctx()), 5)
    assert outcome.status == "stopped"


async def test_the_cap_moves_with_the_setting_without_a_restart(fast_poll, monkeypatch):
    stack = Stack(cap_sec=1)
    spy_penalty(monkeypatch, stack)
    t0 = asyncio.get_event_loop().time()
    first = await asyncio.wait_for(handle_captcha(stack.captcha_ctx()), 5)
    d1 = asyncio.get_event_loop().time() - t0
    stack.state["watcher_captcha_timeout_sec"] = 2  # per-call read, no restart
    t0 = asyncio.get_event_loop().time()
    second = await asyncio.wait_for(handle_captcha(stack.captcha_ctx()), 5)
    d2 = asyncio.get_event_loop().time() - t0
    assert first.status == second.status == "wait_timeout"
    assert d2 > d1 + 0.5  # the cap really moved with the setting


async def test_wait_captcha_cleared_is_called_unchanged(fast_poll, monkeypatch):
    stack = Stack(cap_sec=1)
    spy_penalty(monkeypatch, stack)
    seen = {}

    async def spy(ctrl, stop, timeout_sec, log):
        seen["args"] = (ctrl, stop, timeout_sec, log)
        while not stop():  # the composed predicate must flip at the cap
            await asyncio.sleep(0)
        return False

    monkeypatch.setattr(cooldown_service, "wait_captcha_cleared", spy)
    outcome = await asyncio.wait_for(handle_captcha(stack.captcha_ctx()), 5)
    ctrl, stop, timeout_sec, log = seen["args"]
    assert ctrl is stack.ctrl and callable(stop) and callable(log)
    assert timeout_sec == 1               # the one knob feeds the wait too
    assert stop() is True                 # expired by now (cap reached)
    assert outcome.status == "wait_timeout"


async def test_the_failure_is_honest_not_a_free_pass(fast_poll, monkeypatch):
    """wait_timeout raises a plain RuntimeError out of the runner — no captcha
    penalty stacked, and nothing about it bypasses the normal job cooldown."""
    stack = Stack(cap_sec=1)
    spy_penalty(monkeypatch, stack)
    ctx = sjr.JobCtx(bridge=stack.bridge, ctrl=stack.ctrl, client=None, tab_id="t1",
                     img=SimpleNamespace(absolute_path="/tmp/i.png", relative_path="i.png",
                                         status="pending", output_path=None, error=None),
                     urls=[], job_id="j1", corr_id="c1", final_prompt="p",
                     baseline={"output_count": 0, "output_srcs": []})
    with pytest.raises(RuntimeError) as exc:
        await asyncio.wait_for(sjr.check_security(ctx), 5)
    assert "cap" in str(exc.value)
    assert stack.penalties == []
    assert type(exc.value) is RuntimeError  # generic failure ⇒ normal cooldown
