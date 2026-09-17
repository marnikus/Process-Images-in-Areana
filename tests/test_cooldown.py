"""Tests for app/core/cooldown.py — pure primitives, <10ms (RULE 8).

Covers: config defaults/clamp/round-trip, remaining/ready edges,
cooldown total math, MM:SS / H:MM:SS formatting.
"""

import time

import pytest

from app.core.cooldown import (
    CooldownConfig,
    clamp_seconds,
    config_from_dict,
    config_to_dict,
    cooldown_total,
    format_remaining,
    is_cooling,
    remaining_seconds,
)


@pytest.mark.unit
def test_config_defaults_match_spec():
    cfg = CooldownConfig()
    assert cfg.enabled is True
    assert cfg.min_seconds == 300  # 5 min per spec 02
    assert cfg.captcha_penalty_seconds == 900  # 15 min per spec 04


@pytest.mark.unit
def test_clamp_seconds_bounds():
    assert clamp_seconds(-5) == 0
    assert clamp_seconds(0) == 0
    assert clamp_seconds(300) == 300
    assert clamp_seconds(10_000_000) == 86400
    assert clamp_seconds("abc", default=60) == 60
    assert clamp_seconds(None, default=60) == 60


@pytest.mark.unit
def test_config_from_dict_clamps_and_round_trips():
    cfg = config_from_dict({"enabled": False, "min_seconds": -1, "captcha_penalty_seconds": 999999})
    assert cfg.enabled is False
    assert cfg.min_seconds == 0
    assert cfg.captcha_penalty_seconds == 86400
    back = config_to_dict(config_from_dict(config_to_dict(cfg)))
    assert back["enabled"] is False
    assert back["min_seconds"] == 0


@pytest.mark.unit
def test_config_to_dict_exposes_minutes_for_ui():
    d = config_to_dict(CooldownConfig(True, 300, 900))
    assert d["min_minutes"] == 5
    assert d["captcha_penalty_minutes"] == 15


@pytest.mark.unit
def test_remaining_seconds_edges():
    now = time.time()
    assert remaining_seconds(now + 100, now) == 100
    assert remaining_seconds(now - 1, now) == 0
    assert remaining_seconds(0.0, now) == 0
    assert remaining_seconds(now + 0.9, now) == 0  # sub-second floors to 0


@pytest.mark.unit
def test_is_cooling_edges():
    now = time.time()
    assert is_cooling(now + 10, now) is True
    assert is_cooling(now - 10, now) is False
    assert is_cooling(0.0, now) is False


@pytest.mark.unit
def test_cooldown_total_stacks_base_plus_pending():
    assert cooldown_total(300, 0) == 300
    assert cooldown_total(300, 900) == 1200  # first captcha stacks
    assert cooldown_total(300, 1800) == 2100  # repeated captchas stack
    assert cooldown_total(-5, -5) == 0


@pytest.mark.unit
def test_format_remaining_mm_ss_and_h_mm_ss():
    assert format_remaining(0) == "00:00"
    assert format_remaining(5) == "00:05"
    assert format_remaining(300) == "05:00"
    assert format_remaining(3599) == "59:59"
    assert format_remaining(3600) == "1:00:00"
    assert format_remaining(900) == "15:00"
    assert format_remaining(-3) == "00:00"
