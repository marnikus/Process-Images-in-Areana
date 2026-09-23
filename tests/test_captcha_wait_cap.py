"""S3 · D-14R end to end — a captcha wait ends at `watcher_captcha_timeout_sec`.

Real `handle_captcha`, real `wait_captcha_cleared` (unedited: exactly 4
positional args, never gives up on its own — the cap rides the caller's
`stop`), a fake ctrl whose dialog never clears, and a fake monotonic clock
patched into `policy` so the cap is reached in milliseconds.

RED at base: the wait is unbounded ⇒ `asyncio.wait_for(..., 5)` raises
`TimeoutError`, which *is* the defect.
"""

import asyncio
from types import SimpleNamespace

import pytest

import app.services.cooldown_service as cooldown
import app.services.single_job_runner as sjr
from app.browser.page_pool import PagePool
from app.browser.page_status import PageStatus
from app.services.captcha import policy
from app.services.captcha.service import CaptchaCtx, CaptchaService, SolveOutcome, handle_captcha
from tests.test_captcha_service import FakeCtrl, make_info
from tests.test_single_job_runner import make_bridge as make_runner_bridge, make_ctx, make_ctrl

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class FakeMonotonic:
    """Each read advances `step` seconds — a wait of N polls costs N·step 'seconds'."""

    def __init__(self, step=0.5):
        self.t = 1000.0
        self.step = step

    def __call__(self):
        self.t += self.step
        return self.t


class NeverClears(FakeCtrl):
    def __init__(self):
        super().__init__(visible_seq=[])
        self.visible_polls = 0

    async def is_security_dialog_visible(self):
        self.visible_polls += 1
        return True


@pytest.fixture
def clock(monkeypatch):
    fake = FakeMonotonic()
    monkeypatch.setattr(policy, "time", SimpleNamespace(monotonic=fake))
    monkeypatch.setattr(cooldown, "_POLL_SEC", 0)
    real_sleep = asyncio.sleep

    async def _fast(_s):
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _fast)
    return fake


def make_bridge(pool, config_dir, session):
    logs = []
    bridge = SimpleNamespace(
        _page_pool=pool,
        config=SimpleNamespace(get_state=lambda k, d=None: session.get(k, d)),
        _log=lambda m, l="info": logs.append((m, l)),
        _emit_pool_status=lambda: None,
        _cancel_requested=False,
        _logs=logs,
    )
    service = CaptchaService(str(config_dir), bridge._log)
    bridge._captcha_service = lambda: service
    return bridge


def make_wait(config_dir, session, stop=None):
    pool = PagePool()
    pool.add_page(make_info("t1"))
    pool.mark_busy("t1", "job1")
    bridge = make_bridge(pool, config_dir, session)
    ctrl = NeverClears()
    ctx = CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1", stop=stop, log=bridge._log)
    return ctx, ctrl, pool, bridge


async def run(ctx):
    return await asyncio.wait_for(handle_captcha(ctx), 5)


async def test_a_dialog_that_never_clears_ends_at_the_cap(clock, isolated_config_dir):
    session = {"watcher_enabled": True, "watcher_captcha_timeout_sec": 1}  # clamps to the 10 s floor
    ctx, ctrl, pool, bridge = make_wait(isolated_config_dir, session)
    outcome = await run(ctx)
    assert outcome.status == "wait_timeout"
    assert "10s" in outcome.reason and "cap" in outcome.reason
    assert ctrl.visible_polls >= 2  # it really waited, then gave up at the cap
    assert pool.get_page("t1").pending_penalty == 0  # no penalty on the timeout path
    assert all("🧾 CAPTCHA_SOLVE" not in m or '"wait_timeout"' in m for m, _ in bridge._logs)


async def test_wait_timeout_maps_to_a_retryable_job_failure(monkeypatch):
    penalties = []
    monkeypatch.setattr(cooldown, "note_captcha_event", lambda *a, **k: penalties.append(a) or 1)
    outcome = SolveOutcome(status="wait_timeout", reason="captcha wait exceeded 10s cap")

    async def fake_handle(_ctx):
        return outcome

    monkeypatch.setattr("app.services.captcha.handle_captcha", fake_handle)
    ctrl = make_ctrl(is_security_dialog_visible=lambda: _true())
    bridge = make_runner_bridge()
    img = SimpleNamespace(path="/tmp/a.png", attempt_count=2, status="processing")
    ctx = make_ctx(bridge, ctrl, None, img)
    with pytest.raises(RuntimeError) as exc:
        sjr._handle_captcha_outcome(ctx, outcome)
    assert "10s" in str(exc.value)
    block = SimpleNamespace(block_id="CHECK_SECURITY", enabled=True, params={})
    failed, error = await sjr._loop_blocks(ctx, [block])
    assert failed is True and "10s" in error
    assert img.attempt_count == 2  # the runner never touches retries — retryable by the orchestrator
    assert penalties == []


async def _true():
    return True


async def test_stop_before_the_cap_still_yields_stopped(clock, isolated_config_dir):
    """The existing vocabulary wins: a stop inside the cap is `stopped`, not `wait_timeout`."""
    session = {"watcher_enabled": True, "watcher_captcha_timeout_sec": 3600}
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        return calls["n"] >= 3

    ctx, ctrl, _pool, _bridge = make_wait(isolated_config_dir, session, stop=stop)
    outcome = await run(ctx)
    assert outcome.status == "stopped"


async def test_the_cap_moves_with_the_setting_without_a_restart(clock, isolated_config_dir):
    session = {"watcher_enabled": True, "watcher_captcha_timeout_sec": 1}
    ctx, ctrl, _pool, _bridge = make_wait(isolated_config_dir, session)
    first = await run(ctx)
    assert "10s" in first.reason and ctrl.overlay_calls[-1]["timeout_sec"] == 10
    session["watcher_captcha_timeout_sec"] = 20  # changed mid-run, no restart
    second = await run(ctx)
    assert "20s" in second.reason and ctrl.overlay_calls[-1]["timeout_sec"] == 20
    assert policy.pause_cap_seconds(ctx.bridge) == 20
    session["watcher_captcha_timeout_sec"] = 99_999
    assert policy.pause_cap_seconds(ctx.bridge) == 3600  # ceiling
    session["watcher_captcha_timeout_sec"] = "garbage"
    assert policy.pause_cap_seconds(ctx.bridge) == 300  # default


async def test_wait_captcha_cleared_is_called_unchanged(clock, monkeypatch, isolated_config_dir):
    """The lock that keeps `cooldown_service.py` and its never-gives-up test unedited."""
    seen = {}

    async def spy(*args, **kwargs):
        seen["args"], seen["kwargs"] = args, kwargs
        while not args[1]():  # the composed predicate must become True at the cap
            await asyncio.sleep(0)
        return False

    monkeypatch.setattr(cooldown, "wait_captcha_cleared", spy)
    session = {"watcher_enabled": True, "watcher_captcha_timeout_sec": 10}
    ctx, _ctrl, _pool, _bridge = make_wait(isolated_config_dir, session)
    outcome = await run(ctx)
    assert len(seen["args"]) == 4 and seen["kwargs"] == {}
    assert callable(seen["args"][1]) and seen["args"][2] == 10
    assert outcome.status == "wait_timeout"


async def test_the_cooldown_still_applies_after_a_wait_timeout(clock, monkeypatch, isolated_config_dir):
    """An honest failure, not a free pass: the tab enters its normal job-cycle cooldown."""
    session = {"watcher_enabled": True, "watcher_captcha_timeout_sec": 1,
               "cooldown_enabled": True, "cooldown_min_seconds": 300}
    ctx, _ctrl, pool, bridge = make_wait(isolated_config_dir, session)
    outcome = await run(ctx)
    assert outcome.status == "wait_timeout"

    async def fake_reset(_ctx):
        return True, "mock ready"

    monkeypatch.setattr(cooldown, "reset_to_new_chat", fake_reset)
    finish = cooldown.FinishCtx(pool=pool, bridge=bridge, tab_id="t1", ctrl=object(), client=object())
    assert await cooldown.finish_page_after_job(finish) is True
    assert pool.get_page("t1").status == PageStatus.COOLDOWN
