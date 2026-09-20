"""S3 — D-25/D-14R: the PauseClock value object (RED at base: no module).

One wait, one clock: `note()` charges at most `cap − total` (R22 — a second
settle in the same wait absorbs nothing), `expired()` is False forever when
uncapped, and `paused_elapsed` floors at zero. Pure arithmetic — no Qt, no
bridge, no I/O.
"""

import math
import time

import pytest

pytestmark = pytest.mark.unit


def _clock(cap_s=0.0):
    from app.core.pause_clock import PauseClock
    return PauseClock(cap_s=cap_s)


def test_note_accumulates_and_ignores_garbage():
    c = _clock(cap_s=100)
    c.note(1.5)
    c.note(2.5)
    assert c.total == pytest.approx(4.0)
    c.note(0)
    c.note(-3)
    c.note(float("nan"))
    assert c.total == pytest.approx(4.0)  # garbage never lands, never raises


def test_cap_is_cumulative_per_wait():
    c = _clock(cap_s=10)
    c.note(6)
    c.note(6)  # R22: only 4 more may be absorbed
    assert c.total == pytest.approx(10)
    assert c.expired() is True


def test_uncapped_clock_never_expires():
    c = _clock()  # cap_s = 0 ⇒ uncapped
    c.note(10_000)
    assert c.expired() is False
    assert c.remaining() > 10_000


def test_paused_elapsed_subtracts_and_floors_at_zero():
    c = _clock(cap_s=100)
    c.note(12)
    assert c.paused_elapsed(start=100.0, now=130.0) == pytest.approx(18.0)
    c.note(28)  # total 40 > the 30 s window
    assert c.paused_elapsed(start=100.0, now=130.0) == 0.0  # never negative


def test_paused_elapsed_defaults_to_now():
    c = _clock(cap_s=100)
    c.note(1.0)
    start = time.monotonic()
    first = c.paused_elapsed(start)
    second = c.paused_elapsed(start)
    assert first >= 0.0 and second >= first  # monotone, floored


def test_describe_names_absorbed_and_cap():
    c = _clock(cap_s=300)
    assert c.describe() == ""  # nothing absorbed ⇒ nothing to say
    c.note(12)
    text = c.describe()
    assert "12" in text and "300" in text and "288" in text
    assert "captcha wait" in text


def test_remaining_never_negative():
    c = _clock(cap_s=5)
    c.note(9)
    assert c.total == pytest.approx(5)
    assert c.remaining() == 0.0
    assert not math.isnan(c.remaining())


def test_clock_is_not_shared_between_waits():
    a, b = _clock(cap_s=10), _clock(cap_s=10)
    a.note(7)
    assert a.total == pytest.approx(7) and b.total == 0.0
    assert b.expired() is False
