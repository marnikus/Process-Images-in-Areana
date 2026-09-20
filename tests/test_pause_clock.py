"""S3 units: one definition for each PauseClock method, table-driven scenarios."""
import math

import pytest

from app.core.pause_clock import PauseClock

pytestmark = pytest.mark.unit


@pytest.mark.target('app.core.pause_clock:PauseClock.__init__')
@pytest.mark.parametrize('cap', [0, 10, '300', -1])
def test_init(cap):
    first, second = PauseClock(cap), PauseClock(cap)
    assert first.cap_s == float(cap)
    assert first.total == second.total == 0
    first.total = 7
    assert second.total == 0


@pytest.mark.target('app.core.pause_clock:PauseClock.note')
@pytest.mark.parametrize('cap,steps,total', [
    (100, [1.5, 2.5, 0, -3, math.nan, math.inf, 'bad', None], 4),
    (10, [6, 6, 6], 10), (0, [10000, 1], 10001), (-1, [2], 2)])
def test_note(cap, steps, total):
    clock = PauseClock(cap)
    for seconds in steps:
        clock.note(seconds)
    assert clock.total == pytest.approx(total)


@pytest.mark.target('app.core.pause_clock:PauseClock.expired')
@pytest.mark.parametrize('cap,total,expected', [(0, 10000, False), (-1, 9, False),
                                               (10, 9, False), (10, 10, True), (10, 11, True)])
def test_expired(cap, total, expected):
    clock = PauseClock(cap)
    clock.total = total
    assert clock.expired() is expected


@pytest.mark.target('app.core.pause_clock:PauseClock.remaining')
@pytest.mark.parametrize('cap,total,expected', [(0, 10000, math.inf), (-1, 0, math.inf),
                                               (10, 4, 6), (5, 5, 0), (5, 9, 0)])
def test_remaining(cap, total, expected):
    clock = PauseClock(cap)
    clock.total = total
    assert clock.remaining() == expected
    assert not math.isnan(clock.remaining())


@pytest.mark.target('app.core.pause_clock:PauseClock.paused_elapsed')
@pytest.mark.parametrize('absorbed,now,expected', [(12, 130, 18), (40, 130, 0),
                                                (1, None, 29), (0, 90, 0)])
def test_paused_elapsed(monkeypatch, absorbed, now, expected):
    ticks = [130]
    monkeypatch.setattr('app.core.pause_clock.time.monotonic', lambda: ticks[0])
    clock = PauseClock(100)
    clock.total = absorbed
    assert clock.paused_elapsed(100, now) == expected
    if now is None:
        ticks[0] += 1
        assert clock.paused_elapsed(100) == expected + 1


@pytest.mark.target('app.core.pause_clock:PauseClock.describe')
@pytest.mark.parametrize('cap,total,expected', [(300, 0, ''),
    (300, 12, '+12s captcha wait (cap 300s, 288s left)'),
    (0, 12, '+12s captcha wait (uncapped)'), (10, 10, '+10s captcha wait (cap 10s, 0s left)')])
def test_describe(cap, total, expected):
    clock = PauseClock(cap)
    clock.total = total
    assert clock.describe() == expected
