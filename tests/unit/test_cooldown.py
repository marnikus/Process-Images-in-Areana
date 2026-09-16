"""Unit tests for cooldown logic — pure functions."""

import time
from app.core.cooldown import (
    calculate_cooldown_until,
    is_in_cooldown,
    remaining_seconds,
    format_remaining,
    apply_captcha_penalty,
    should_allow_job,
    cooldown_info,
    epoch_to_iso,
    parse_iso_to_epoch,
    now_epoch,
)


def test_calculate_cooldown_until():
    now = 1000.0
    until = calculate_cooldown_until(last_completed_epoch=now, cooldown_seconds=300, now=now)
    assert until == 1300.0


def test_is_in_cooldown():
    now = 1000.0
    assert is_in_cooldown(cooldown_until_epoch=1100.0, now=now) is True
    assert is_in_cooldown(cooldown_until_epoch=900.0, now=now) is False
    assert is_in_cooldown(cooldown_until_epoch=None, now=now) is False


def test_remaining_seconds():
    now = 1000.0
    assert remaining_seconds(cooldown_until_epoch=1100.0, now=now) == 100
    assert remaining_seconds(cooldown_until_epoch=900.0, now=now) == 0
    assert remaining_seconds(cooldown_until_epoch=None, now=now) == 0


def test_format_remaining():
    assert format_remaining(0) == "ready"
    assert format_remaining(5) == "5s"
    assert format_remaining(65) == "1m 5s"
    assert format_remaining(120) == "2m"
    assert format_remaining(3600) == "1h"
    assert format_remaining(3660) == "1h 1m"


def test_apply_captcha_penalty():
    now = 1000.0
    # no current cooldown -> penalty from now
    new_until = apply_captcha_penalty(current_until_epoch=None, penalty_seconds=900, now=now)
    assert new_until == 1900.0
    # existing cooldown in future -> stacks
    new_until2 = apply_captcha_penalty(current_until_epoch=1500.0, penalty_seconds=900, now=now)
    assert new_until2 == 2400.0
    # existing cooldown expired -> from now
    new_until3 = apply_captcha_penalty(current_until_epoch=900.0, penalty_seconds=900, now=now)
    assert new_until3 == 1900.0


def test_should_allow_job():
    now = 1000.0
    assert should_allow_job(status="steady", cooldown_until_epoch=None, is_connected=True, now=now) is True
    assert should_allow_job(status="steady", cooldown_until_epoch=1100.0, is_connected=True, now=now) is False
    assert should_allow_job(status="busy", cooldown_until_epoch=None, is_connected=True, now=now) is False
    assert should_allow_job(status="steady", cooldown_until_epoch=None, is_connected=False, now=now) is False


def test_cooldown_info():
    now = now_epoch()
    future_iso = epoch_to_iso(now + 100)
    info = cooldown_info(future_iso, now=now)
    assert info["in_cooldown"] is True
    assert info["remaining_sec"] >= 99
    assert "s" in info["remaining_str"] or "m" in info["remaining_str"]

    past_iso = epoch_to_iso(now - 100)
    info2 = cooldown_info(past_iso, now=now)
    assert info2["in_cooldown"] is False
    assert info2["remaining_sec"] == 0
    assert info2["remaining_str"] == "ready"


def test_parse_iso():
    iso = "2026-09-16T10:00:00+00:00"
    epoch = parse_iso_to_epoch(iso)
    assert epoch is not None
    assert parse_iso_to_epoch(None) is None
    assert parse_iso_to_epoch("invalid") is None
