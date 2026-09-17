"""Cooldown primitives — pure job-cycle math, no Qt, no CDP.

One responsibility: per-tab cooldown values (spec 02-04). Pool owns the
locking (`app/services/cooldown_service.py`); tabs own the fields
(`app/browser/page_status.py`). Imports: stdlib only.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

DAY_SECONDS = 86400
DEFAULT_MIN_SECONDS = 300  # spec 02 example: 5 min between jobs
DEFAULT_PENALTY_SECONDS = 900  # spec 04 example: +15 min per captcha


@dataclass
class CooldownConfig:
    """User settings: base pause + per-captcha extra (seconds)."""

    enabled: bool = True
    min_seconds: int = DEFAULT_MIN_SECONDS
    captcha_penalty_seconds: int = DEFAULT_PENALTY_SECONDS


def clamp_seconds(value, default: int = 0, limit: int = DAY_SECONDS) -> int:
    """Clamp user input to 0..limit, forgiving bad types."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number < 0:
        return 0
    if number > limit:
        return limit
    return number


def config_from_dict(data: dict | None) -> CooldownConfig:
    """Build config from session/preset dict, clamped."""
    raw = data if isinstance(data, dict) else {}
    return CooldownConfig(
        enabled=bool(raw.get("enabled", True)),
        min_seconds=clamp_seconds(raw.get("min_seconds", DEFAULT_MIN_SECONDS),
                                  DEFAULT_MIN_SECONDS),
        captcha_penalty_seconds=clamp_seconds(raw.get("captcha_penalty_seconds",
                                                      DEFAULT_PENALTY_SECONDS),
                                              DEFAULT_PENALTY_SECONDS),
    )


def config_to_dict(cfg: CooldownConfig) -> dict:
    """Serialize for UI (seconds on the wire, minutes for display)."""
    return {
        "enabled": bool(cfg.enabled),
        "min_seconds": int(cfg.min_seconds),
        "captcha_penalty_seconds": int(cfg.captcha_penalty_seconds),
        "min_minutes": int(cfg.min_seconds) // 60,
        "captcha_penalty_minutes": int(cfg.captcha_penalty_seconds) // 60,
    }


def remaining_seconds(cooldown_until: float, now: float | None = None) -> int:
    """Seconds left until ready; 0 when no timer or expired."""
    at = now if now is not None else time.time()
    left = int(cooldown_until - at)
    return left if left > 0 else 0


def is_cooling(cooldown_until: float, now: float | None = None) -> bool:
    """True while the timer still gates the next job."""
    return remaining_seconds(cooldown_until, now) > 0


def cooldown_total(base_seconds: int, pending_penalty: int) -> int:
    """Total pause: base minimum + stacked captcha penalty."""
    base = base_seconds if base_seconds > 0 else 0
    extra = pending_penalty if pending_penalty > 0 else 0
    return base + extra


def format_remaining(seconds: int) -> str:
    """Countdown text: MM:SS under an hour, H:MM:SS above."""
    total = int(seconds) if seconds > 0 else 0
    mins, secs = divmod(total, 60)
    if mins < 60:
        return f"{mins:02d}:{secs:02d}"
    hours, mins = divmod(mins, 60)
    return f"{hours}:{mins:02d}:{secs:02d}"
