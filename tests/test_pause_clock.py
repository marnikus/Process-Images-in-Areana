"""PauseClock: the per-generation-wait pause budget (S3, D-25).

Pure value object in `app/core/` (it cannot live in `output_wait.py` — that
file's `max_class_loc` is 4). No fakes needed.
"""

import pytest

from app.core.pause_clock import PauseClock


@pytest.mark.unit
def test_clocks_ignore_garbage():
    clock = PauseClock(cap_s=100)
    clock.note(1.5)
    clock.note(2.5)
    assert clock.total == 4.0
    clock.note(0)
    clock.note(-3)
    clock.note(float("nan"))
    clock.note(None)  # TypeError inside `>` → ignored via the guard
    assert clock.total == 4.0
    assert PauseClock("x").cap_s == 0.0  # unparseable cap → uncapped, never raises


@pytest.mark.unit
def test_cap_is_cumulative_per_wait():
    clock = PauseClock(cap_s=10)
    clock.note(6)
    assert clock.expired() is False
    clock.note(6)
    assert clock.total == 10  # the second settle absorbs 4, not 6 (R22)
    assert clock.expired() is True


@pytest.mark.unit
def test_uncapped_clock_never_expires():
    clock = PauseClock()
    clock.note(10_000)
    assert clock.expired() is False
    assert clock.remaining() > 10_000


@pytest.mark.unit
def test_paused_elapsed_subtracts_and_floors_at_zero():
    clock = PauseClock(cap_s=100)
    clock.note(12)
    assert clock.paused_elapsed(start=100, now=130) == 18
    clock.note(28)
    assert clock.paused_elapsed(start=100, now=130) == 0


@pytest.mark.unit
def test_paused_elapsed_defaults_to_now():
    import time

    clock = PauseClock(cap_s=100)
    start = time.monotonic()
    first = clock.paused_elapsed(start)
    second = clock.paused_elapsed(start)
    assert first >= 0
    assert second >= first  # monotonic() is provably non-decreasing


@pytest.mark.unit
def test_describe_names_absorbed_and_cap():
    clock = PauseClock(cap_s=300)
    assert clock.describe() == ""
    clock.note(12)
    assert clock.describe() == "+12s captcha wait (cap 300s, 288s left)"


@pytest.mark.unit
def test_remaining_never_negative():
    clock = PauseClock(cap_s=10)
    clock.note(999)
    assert clock.remaining() == 0.0


@pytest.mark.unit
def test_clock_is_not_shared_between_waits():
    first = PauseClock(cap_s=10)
    second = PauseClock(cap_s=10)
    first.note(7)
    assert first.total == 7
    assert second.total == 0
