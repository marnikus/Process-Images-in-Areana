"""Per-page passive captcha monitor — watcher-principle checks for the run flow.

RULE 8: real monitor + real guard against a fake ctrl/clock-free loop (tiny
interval). Pins: one settle per encounter, re-arm after clear, fail-open on
probe errors, guard blocks concurrent settles, stop cancels.
"""

import asyncio

import pytest

from app.services.captcha.monitor import (
    MAX_CONSECUTIVE_ERRORS, PAGE_CHECK_INTERVAL_SEC, PageMonitor, SettleGuard,
    start_page_monitor, stop_page_monitor,
)


class FakeCtrl:
    def __init__(self, visible_seq=None, fail_after=None):
        self._visible = list(visible_seq or [])
        self._fail_after = fail_after
        self.calls = 0

    async def is_security_dialog_visible(self):
        self.calls += 1
        if self._fail_after is not None and self.calls > self._fail_after:
            raise RuntimeError("cdp gone")
        return self._visible.pop(0) if self._visible else False


async def run_ticks(monitor, ticks):
    """Let the monitor loop run ~ticks ticks (interval shrunk for tests)."""
    for _ in range(ticks):
        await asyncio.sleep(monitor.interval * 2)


def make_monitor(ctrl, settle, report=None, interval=0.01):
    return PageMonitor(ctrl, settle, interval=interval, report=report or (lambda m, l="info": None))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_settle_called_once_per_encounter_and_rearms_after_clear():
    ctrl = FakeCtrl(visible_seq=[True, True, True, False, True, False, False])
    settles = []

    async def settle():
        settles.append(1)
        await asyncio.sleep(0)

    monitor = make_monitor(ctrl, settle)
    monitor.start()
    await run_ticks(monitor, 8)
    await stop_page_monitor(monitor)
    assert len(settles) == 2  # one per encounter; the 2nd visible run re-arms
    assert ctrl.calls >= 6


@pytest.mark.unit
@pytest.mark.asyncio
async def test_never_settles_when_never_visible():
    ctrl = FakeCtrl(visible_seq=[False, False, False, False])
    settles = []

    async def settle():
        settles.append(1)

    monitor = make_monitor(ctrl, settle)
    monitor.start()
    await run_ticks(monitor, 6)
    await stop_page_monitor(monitor)
    assert settles == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_errors_are_fail_open_and_self_terminate_eventually():
    """Probe errors never settle; enough consecutive ones stop the monitor."""
    ctrl = FakeCtrl(fail_after=0)  # every probe raises
    settles = []

    async def settle():
        settles.append(1)

    stopped = []
    monitor = make_monitor(ctrl, settle, report=lambda m, l="info": stopped.append((m, l)))
    monitor.start()
    await run_ticks(monitor, MAX_CONSECUTIVE_ERRORS + 4)
    await asyncio.sleep(0.01)
    assert settles == []                     # never trusted an error
    assert not monitor.running               # self-terminated (fail-open exit)
    assert any("monitor stopped" in m.lower() or "stopped" in m.lower() for m, _ in stopped)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_error_resets_when_page_recovers():
    """A bounded probe-error burst never settles again nor kills the monitor."""

    class FlakyThenClearCtrl:
        def __init__(self):
            self.calls = 0

        async def is_security_dialog_visible(self):
            self.calls += 1
            if self.calls == 1:
                return True               # one real encounter
            if 2 <= self.calls <= 6:      # then a 5-probe hiccup
                raise RuntimeError("cdp hiccup")
            return False

    settles = []

    async def settle():
        settles.append(1)

    monitor = make_monitor(FlakyThenClearCtrl(), settle)
    monitor.start()
    await run_ticks(monitor, 12)
    assert len(settles) == 1                 # the encounter before the errors
    assert monitor.running                   # still alive after transient errors
    await stop_page_monitor(monitor)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stop_cancels_the_loop():
    ctrl = FakeCtrl(visible_seq=[])
    settles = []

    async def settle():
        settles.append(1)

    monitor = make_monitor(ctrl, settle)
    monitor.start()
    assert monitor.running
    await stop_page_monitor(monitor)
    assert not monitor.running
    calls_before = ctrl.calls
    await asyncio.sleep(0.03)
    assert ctrl.calls == calls_before        # loop is dead


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_page_monitor_stores_on_ctrl_and_stop_removes():
    ctrl = FakeCtrl(visible_seq=[])

    async def settle():
        return None

    monitor = start_page_monitor(ctrl, settle, interval=0.01)
    assert isinstance(monitor, PageMonitor)
    assert getattr(ctrl, "_captcha_monitor", None) is monitor
    await stop_page_monitor(ctrl)
    assert not monitor.running
    assert not hasattr(ctrl, "_captcha_monitor")
    await stop_page_monitor(ctrl)  # idempotent


@pytest.mark.unit
@pytest.mark.asyncio
async def test_settle_guard_blocks_concurrent_second_settle():
    guard = SettleGuard()
    started = []

    async def slow():
        started.append(1)
        await asyncio.sleep(0.05)
        return True

    first = asyncio.create_task(guard.run(slow))
    await asyncio.sleep(0.01)
    assert guard.busy
    assert await guard.run(slow) is False    # deferred while busy
    assert await first is True
    assert not guard.busy
    assert await guard.run(slow) is True     # works again after release


@pytest.mark.unit
def test_default_interval_is_the_watcher_like_500ms():
    assert 0.3 <= PAGE_CHECK_INTERVAL_SEC <= 0.7
