"""The captcha wait is bounded by the user's knob (S3, D-14R) — end to end.

Real `handle_captcha`, real `wait_captcha_cleared` (unedited, its
never-gives-up test still pins it), real PagePool + key store + stats; a
fake controller whose dialog never clears, and a fake monotonic clock
injected into the real `WaitDeadline` so a 10 s cap costs 10 polls, not
10 seconds. `asyncio.sleep` is instant. At the cap the encounter ends as
`wait_timeout`: no penalty, no stat, a plain retryable job failure.
"""

import functools
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.services import cooldown_service
from app.services import single_job_runner as sjr
from app.services.captcha import policy
from app.services.captcha import service as svc_mod
from app.services.captcha.service import CaptchaCtx, CaptchaService, handle_captcha
from app.services.captcha.signals import SolveOutcome
from tests.test_captcha_boundaries import make_ctx
from tests.test_captcha_service import FakeCtrl, instant_sleep, make_info

pytestmark = pytest.mark.unit

NEVER_CLEARS = [True] * 500   # finite: a regression answers "manual" instead of hanging


class FakeClock:
    """Monotonic seconds that advance `step` per read (deterministic deadlines)."""

    def __init__(self, step=1.0):
        self.t = 0.0
        self.step = step

    def now(self):
        value = self.t
        self.t += self.step
        return value


def arm(monkeypatch, clock: FakeClock):
    """The real WaitDeadline, reading the fake clock (the deadline logic itself is not doubled)."""
    monkeypatch.setattr(svc_mod, "WaitDeadline",
                        functools.partial(policy.WaitDeadline, clock=clock.now))


def make_bridge(pool, config_dir, cap=10):
    state = {"watcher_enabled": True, "watcher_captcha_timeout_sec": cap,
             "cooldown_enabled": True, "cooldown_captcha_penalty_seconds": 900}
    logs = []
    service = CaptchaService(str(config_dir))
    return SimpleNamespace(
        _cancel_requested=False, _page_pool=pool, _ensure_page_pool=lambda: pool,
        config=SimpleNamespace(get_state=lambda k, d=None: state.get(k, d)),
        _log=lambda m, l="info": logs.append((m, l)),
        _emit_pool_status=lambda: logs.append(("emit", "")),
        _captcha_service=lambda: service, _logs=logs, _state=state,
    )


def pooled(tab_id="t1"):
    pool = PagePool()
    pool.add_page(make_info(tab_id))
    return pool


async def test_a_dialog_that_never_clears_ends_at_the_cap(monkeypatch, isolated_config_dir):
    instant_sleep(monkeypatch)
    arm(monkeypatch, FakeClock(step=1.0))
    pool = pooled()
    bridge = make_bridge(pool, isolated_config_dir, cap=10)
    ctrl = FakeCtrl(visible_seq=list(NEVER_CLEARS))
    outcome = await handle_captcha(CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1"))
    assert outcome.status == "wait_timeout"
    assert "10s" in outcome.reason and "retryable" in outcome.reason
    assert len(ctrl._visible) > 0  # it stopped because of the cap, not because the dialog ran out


async def test_the_cap_records_no_penalty_and_no_solve(monkeypatch, isolated_config_dir):
    instant_sleep(monkeypatch)
    arm(monkeypatch, FakeClock(step=1.0))
    pool = pooled()
    bridge = make_bridge(pool, isolated_config_dir, cap=10)
    events = []
    monkeypatch.setattr(cooldown_service, "note_captcha_event",
                        lambda *a, **k: events.append((a, k)) or 1)
    outcome = await handle_captcha(CaptchaCtx(ctrl=FakeCtrl(visible_seq=list(NEVER_CLEARS)),
                                              pool=pool, bridge=bridge, tab_id="t1"))
    assert outcome.status == "wait_timeout"
    assert events == []                                   # nothing was cleared ⇒ no penalty
    assert pool.get_page("t1").pending_penalty == 0
    stats = bridge._captcha_service().stats.to_dict()
    assert stats["manual_solved"] == 0 and stats["detected_total"] == 1


def test_wait_timeout_maps_to_a_retryable_job_failure():
    """The runner raises the same plain RuntimeError its page_error branch uses (retryable path)."""
    ctx = make_ctx(pooled(), SimpleNamespace(_log=lambda *a: None), SimpleNamespace())
    with pytest.raises(RuntimeError, match="not cleared in 10s"):
        sjr._handle_captcha_outcome(ctx, SolveOutcome(status="wait_timeout",
                                                      reason="Captcha not cleared in 10s — job failed (retryable)"))
    with pytest.raises(RuntimeError, match="Captcha wait hit the cap"):
        sjr._handle_captcha_outcome(ctx, SolveOutcome(status="wait_timeout"))
    with pytest.raises(RuntimeError, match="Cancelled during CAPTCHA"):   # equivalence
        sjr._handle_captcha_outcome(ctx, SolveOutcome(status="stopped", reason="ignored"))
    with pytest.raises(RuntimeError, match="boom"):
        sjr._handle_captcha_outcome(ctx, SolveOutcome(status="page_error", reason="boom"))
    for status in ("none", "manual", "out_of_scope", "token_stale"):
        sjr._handle_captcha_outcome(ctx, SolveOutcome(status=status))      # never raises


async def test_stop_before_the_cap_still_yields_stopped(monkeypatch, isolated_config_dir):
    instant_sleep(monkeypatch)
    arm(monkeypatch, FakeClock(step=0.1))
    pool = pooled()
    bridge = make_bridge(pool, isolated_config_dir, cap=10)
    asked = {"n": 0}

    def stop():
        asked["n"] += 1
        return asked["n"] >= 3

    outcome = await handle_captcha(CaptchaCtx(ctrl=FakeCtrl(visible_seq=list(NEVER_CLEARS)),
                                              pool=pool, bridge=bridge, tab_id="t1", stop=stop))
    assert outcome.status == "stopped"   # the existing vocabulary wins over the new one


async def test_the_cap_moves_with_the_setting_without_a_restart(monkeypatch, isolated_config_dir):
    instant_sleep(monkeypatch)
    arm(monkeypatch, FakeClock(step=1.0))
    pool = pooled()
    bridge = make_bridge(pool, isolated_config_dir, cap=10)

    async def polls_until_cap():
        ctrl = FakeCtrl(visible_seq=list(NEVER_CLEARS))
        outcome = await handle_captcha(CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1"))
        assert outcome.status == "wait_timeout"
        return len(NEVER_CLEARS) - len(ctrl._visible)

    first = polls_until_cap()
    assert await first == 10
    bridge._state["watcher_captcha_timeout_sec"] = 20   # per-call read, no cached value
    assert await polls_until_cap() == 20


async def test_wait_captcha_cleared_is_called_unchanged(monkeypatch, isolated_config_dir):
    """The lock that keeps cooldown_service.py (and its never-gives-up test) unedited."""
    instant_sleep(monkeypatch)
    clock = FakeClock(step=0.0)
    arm(monkeypatch, clock)
    seen = {}

    async def spy(*args, **kwargs):
        seen["args"], seen["kwargs"] = args, kwargs
        return False

    monkeypatch.setattr(cooldown_service, "wait_captcha_cleared", spy)
    pool = pooled()
    bridge = make_bridge(pool, isolated_config_dir, cap=10)
    await handle_captcha(CaptchaCtx(ctrl=FakeCtrl(visible_seq=[True]), pool=pool, bridge=bridge, tab_id="t1"))
    assert len(seen["args"]) == 4 and seen["kwargs"] == {}
    ctrl, stop, timeout_sec, log = seen["args"]
    assert timeout_sec == 10 and callable(log)
    assert stop() is False
    clock.t += 10                                        # the cap passes ⇒ the predicate flips
    assert stop() is True


def test_pause_cap_seconds_clamps_the_knob():
    def bridge_with(value):
        return SimpleNamespace(config=SimpleNamespace(get_state=lambda k, d=None: value))

    assert policy.pause_cap_seconds(bridge_with(1)) == 10
    assert policy.pause_cap_seconds(bridge_with(99999)) == 3600
    assert policy.pause_cap_seconds(bridge_with(300)) == 300
    assert policy.pause_cap_seconds(bridge_with("garbage")) == 300
    assert policy.pause_cap_seconds(SimpleNamespace()) == 300           # no config ⇒ default


def test_the_budget_is_bounded_by_what_the_generation_wait_has_left():
    """A second captcha in the same generation wait gets only the remaining pause budget."""
    from app.core.pause_clock import PauseClock

    bridge = SimpleNamespace(config=SimpleNamespace(get_state=lambda k, d=None: 300))
    assert policy.pause_budget(bridge, SimpleNamespace()) == 300         # before generation: the knob
    clock = PauseClock(cap_s=300)
    clock.note(250)
    assert policy.pause_budget(bridge, SimpleNamespace(pause_clock=clock)) == 50
    clock.note(100)
    assert policy.pause_budget(bridge, SimpleNamespace(pause_clock=clock)) == 0


async def test_wait_for_output_installs_the_clock_only_in_scope(monkeypatch, isolated_config_dir):
    """ON: `ctrl.pause_clock` carries the knob for the wait and is gone afterwards; OFF: never installed."""
    from app.core.pause_clock import PauseClock

    seen = {}

    async def fake_poll(ctx, _timeout_ms):
        seen["clock"] = getattr(ctx.ctrl, "pause_clock", None)
        seen["settler"] = getattr(ctx.ctrl, "security_settler", None)
        return "timeout", {"error": "timed out"}, None

    monkeypatch.setattr(sjr, "_poll_generation", fake_poll)

    async def _noop(*a, **k):
        return None

    ctrl = SimpleNamespace(show_watcher_overlay=_noop, hide_watcher_overlay=_noop)
    pool = pooled()
    bridge = make_bridge(pool, isolated_config_dir, cap=120)
    await sjr.wait_for_output(make_ctx(pool, bridge, ctrl), 1000)
    assert isinstance(seen["clock"], PauseClock) and seen["clock"].cap_s == 120
    assert seen["settler"] is not None
    assert not hasattr(ctrl, "pause_clock") and not hasattr(ctrl, "security_settler")

    bridge._state["watcher_enabled"] = False
    await sjr.wait_for_output(make_ctx(pool, bridge, ctrl), 1000)
    assert seen["clock"] is None and seen["settler"] is None
