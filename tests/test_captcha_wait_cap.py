"""S3 — the captcha pause is capped (D-14R), the bound is OUR setting, and
the pipelined wait ends there as an honest, retryable `wait_timeout`."""

import asyncio
import time
from types import SimpleNamespace

import pytest

from app.services.captcha.policy import WaitDeadline, pause_cap_seconds
from app.services.captcha.service import (
    CaptchaCtx, _handle_captcha_scoped, handle_captcha,
)
from test_captcha_service import (
    FakeCtrl, detect_result, instant_sleep, make_bridge, make_info,
)
from app.browser.page_pool import PagePool


class NeverClearsCtrl(FakeCtrl):
    """The dialog stays up forever — the only way out is the user's stop
    or (since S3) the cap."""

    def __init__(self):
        super().__init__(visible_seq=[True], detect=detect_result())

    async def is_security_dialog_visible(self):
        return True


def timed_bridge(pool, config_dir, seconds, mapping=None):
    bridge = make_bridge(pool, config_dir)
    states = mapping if mapping is not None else {"watcher_captcha_timeout_sec": seconds,
                                                  "watcher_enabled": True}
    bridge.config = SimpleNamespace(get_state=lambda k, d=None: states.get(k, d))
    bridge._states = states
    return bridge


@pytest.mark.unit
def test_cap_reads_the_existing_setting(isolated_config_dir):
    """Pause cap ⇔ captcha wait bound ⇔ `watcher_captcha_timeout_sec`: ONE value."""
    pool = PagePool()
    bridge = timed_bridge(pool, isolated_config_dir, 500)
    assert pause_cap_seconds(bridge) == 500
    bridge._states["watcher_captcha_timeout_sec"] = 123
    assert pause_cap_seconds(bridge) == 123
    bridge._states["watcher_captcha_timeout_sec"] = 5      # below the floor
    assert pause_cap_seconds(bridge) == 10
    bridge._states["watcher_captcha_timeout_sec"] = "junk"
    assert pause_cap_seconds(bridge) == 300                # fail-closed default


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_dialog_that_never_clears_ends_at_the_cap(monkeypatch, isolated_config_dir):
    """RED at base: the wait is unbounded (wait_for guard times out — the defect)."""
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = timed_bridge(pool, isolated_config_dir, 1)
    ctx = CaptchaCtx(ctrl=NeverClearsCtrl(), pool=pool, bridge=bridge, tab_id="t1")

    outcome = await asyncio.wait_for(handle_captcha(ctx), timeout=5)

    assert outcome.status == "wait_timeout"
    assert "1s" in (outcome.reason or "")
    assert "retryable" in (outcome.reason or "")
    assert not pool.get_page("t1").pending_penalty  # honest failure, not a free penalty


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wait_timeout_maps_to_a_retryable_job_failure(monkeypatch, isolated_config_dir):
    """`wait_timeout` raises out of the runner; no captcha penalty is recorded."""
    from app.services import cooldown_service
    from app.services.captcha.service import _wait_outcome
    from app.services.single_job_runner import _handle_captcha_outcome

    spy = []
    monkeypatch.setattr(cooldown_service, "note_captcha_event",
                        lambda *a, **k: spy.append(True))
    fake = {"t": 1000.0}
    monkeypatch.setattr(time, "monotonic", lambda: fake["t"])

    pool = PagePool()
    bridge = timed_bridge(pool, isolated_config_dir, 60)
    ctx = CaptchaCtx(ctrl=FakeCtrl(visible_seq=[False]), pool=pool, bridge=bridge, tab_id="t1")
    deadline = WaitDeadline(60)
    fake["t"] += 61                                        # past the cap
    outcome = _wait_outcome(ctx, SimpleNamespace(page_url="https://x.ai"), False, deadline)

    assert outcome.status == "wait_timeout"
    assert spy == []                                       # no penalty on the timeout path
    job_ctx = SimpleNamespace(bridge=bridge)
    with pytest.raises(RuntimeError, match="60s"):
        _handle_captcha_outcome(job_ctx, outcome)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stop_before_the_cap_still_yields_stopped(monkeypatch, isolated_config_dir):
    """The existing vocabulary wins when the user, not the cap, ended the wait."""
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = timed_bridge(pool, isolated_config_dir, 300)
    ctx = CaptchaCtx(ctrl=NeverClearsCtrl(), pool=pool, bridge=bridge, tab_id="t1",
                     stop=lambda: True)

    outcome = await handle_captcha(ctx)

    assert outcome.status == "stopped"
    assert outcome.reason == "stop requested while waiting for solve"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_cap_moves_with_the_setting_without_a_restart(monkeypatch, isolated_config_dir):
    """Per-call read, no cached value: change the setting, the next wait follows."""
    instant_sleep(monkeypatch)
    fake = {"t": 1000.0}

    def _ticks():
        fake["t"] += 0.4          # each wall-clock read advances 0.4 fake seconds
        return fake["t"]

    monkeypatch.setattr(time, "monotonic", _ticks)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    mapping = {"watcher_captcha_timeout_sec": 1, "watcher_enabled": True}
    bridge = timed_bridge(pool, isolated_config_dir, None, mapping)

    outcome1 = await handle_captcha(
        CaptchaCtx(ctrl=NeverClearsCtrl(), pool=pool, bridge=bridge, tab_id="t1"))
    mapping["watcher_captcha_timeout_sec"] = 2             # user edits the knob mid-session
    outcome2 = await handle_captcha(
        CaptchaCtx(ctrl=NeverClearsCtrl(), pool=pool, bridge=bridge, tab_id="t1"))

    assert "1s" in (outcome1.reason or "")
    assert "2s" in (outcome2.reason or "")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wait_captcha_cleared_is_called_unchanged(monkeypatch, isolated_config_dir):
    """The lock that keeps cooldown_service.py and its pinned test unedited:
    exactly 4 positional arguments, the second a callable that becomes True at the cap."""
    from app.services import cooldown_service

    instant_sleep(monkeypatch)
    seen = []

    async def spy(ctrl, stop, timeout, log):
        seen.append((ctrl, stop, timeout, log))
        return True                                # the dialog clears, test exits

    monkeypatch.setattr(cooldown_service, "wait_captcha_cleared", spy)
    fake = {"t": 1000.0}
    monkeypatch.setattr(time, "monotonic", lambda: fake["t"])

    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = timed_bridge(pool, isolated_config_dir, 300)
    ctrl = FakeCtrl(visible_seq=[True, False])
    outcome = await handle_captcha(CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1"))

    assert outcome.status == "manual"
    assert len(seen) == 1
    got_ctrl, stop, timeout, _log = seen[0]
    assert got_ctrl is ctrl and timeout == 300 and callable(stop) and callable(_log)
    assert stop() is False                               # fresh deadline: keep waiting
    fake["t"] += 301                                     # past the cap…
    assert stop() is True                                # …the composed predicate fires


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_cooled_down_tab_still_applies_after_a_wait_timeout(monkeypatch, isolated_config_dir):
    """A wait_timeout is the job's ordinary failure path: the pool row ends a
    normal cooldown candidate — marked waiting during the wait (I-21), back to
    busy afterwards, never carrying a captcha penalty."""
    instant_sleep(monkeypatch)

    def _ticks():
        _ticks.t += 0.5           # each wall-clock read advances 0.5 fake seconds

        return _ticks.t

    _ticks.t = 1000.0
    monkeypatch.setattr(time, "monotonic", _ticks)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = timed_bridge(pool, isolated_config_dir, 1)
    ctx = CaptchaCtx(ctrl=NeverClearsCtrl(), pool=pool, bridge=bridge, tab_id="t1")

    outcome = await asyncio.wait_for(handle_captcha(ctx), timeout=5)

    assert outcome.status == "wait_timeout"
    assert not pool.get_page("t1").pending_penalty
