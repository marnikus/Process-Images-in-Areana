"""Cooldown logic — pure, no I/O, no Qt, no CDP.

Handles:
- minimum pause between jobs per tab
- countdown timer per tab
- captcha penalty stacking per tab

RULE 18: file 150-300 LOC ideal, current ~210 LOC.
RULE 16: func ≤30 LOC, CC ≤10, nesting ≤4, params ≤4.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from typing import Optional


def now_epoch() -> float:
    return time.time()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso_to_epoch(iso_str: Optional[str]) -> Optional[float]:
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return None


def epoch_to_iso(epoch: float) -> str:
    try:
        return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
    except Exception:
        return now_iso()


def calculate_cooldown_until(
    last_completed_epoch: Optional[float],
    cooldown_seconds: int,
    now: Optional[float] = None,
) -> float:
    base = last_completed_epoch if last_completed_epoch is not None else (now or now_epoch())
    cd = max(0, int(cooldown_seconds))
    return base + cd


def is_in_cooldown(cooldown_until_epoch: Optional[float], now: Optional[float] = None) -> bool:
    if cooldown_until_epoch is None:
        return False
    cur = now if now is not None else now_epoch()
    return cur < cooldown_until_epoch


def remaining_seconds(
    cooldown_until_epoch: Optional[float], now: Optional[float] = None
) -> int:
    if cooldown_until_epoch is None:
        return 0
    cur = now if now is not None else now_epoch()
    rem = cooldown_until_epoch - cur
    return max(0, int(rem))


def format_remaining(remaining_sec: int) -> str:
    sec = max(0, int(remaining_sec))
    if sec <= 0:
        return "ready"
    if sec < 60:
        return f"{sec}s"
    mins = sec // 60
    secs = sec % 60
    if mins < 60:
        if secs == 0:
            return f"{mins}m"
        return f"{mins}m {secs}s"
    hours = mins // 60
    mins = mins % 60
    if mins == 0:
        return f"{hours}h"
    return f"{hours}h {mins}m"


def apply_captcha_penalty(
    current_until_epoch: Optional[float],
    penalty_seconds: int,
    now: Optional[float] = None,
) -> float:
    cur = now if now is not None else now_epoch()
    base = current_until_epoch if current_until_epoch is not None else cur
    if base < cur:
        base = cur
    pen = max(0, int(penalty_seconds))
    return base + pen


def reset_cooldown() -> None:
    return None


def should_allow_job(
    status: str,
    cooldown_until_epoch: Optional[float],
    is_connected: bool,
    now: Optional[float] = None,
) -> bool:
    if not is_connected:
        return False
    if status not in ("steady", "ready"):
        if status != "steady":
            return False
    return not is_in_cooldown(cooldown_until_epoch, now=now)


def cooldown_info(
    cooldown_until_iso: Optional[str], now: Optional[float] = None
) -> dict:
    until_epoch = parse_iso_to_epoch(cooldown_until_iso)
    cur = now if now is not None else now_epoch()
    in_cd = is_in_cooldown(until_epoch, now=cur)
    rem = remaining_seconds(until_epoch, now=cur)
    return {
        "in_cooldown": in_cd,
        "remaining_sec": rem,
        "remaining_str": format_remaining(rem),
        "until_iso": cooldown_until_iso,
        "until_epoch": until_epoch,
    }


def next_ready_after_penalty(
    current_until_iso: Optional[str],
    penalty_seconds: int,
    now: Optional[float] = None,
) -> str:
    cur_epoch = now if now is not None else now_epoch()
    cur_until = parse_iso_to_epoch(current_until_iso)
    new_until = apply_captcha_penalty(cur_until, penalty_seconds, now=cur_epoch)
    return epoch_to_iso(new_until)


def calculate_next_cooldown_iso(
    last_completed_iso: Optional[str],
    cooldown_seconds: int,
    now: Optional[float] = None,
) -> str:
    last_epoch = parse_iso_to_epoch(last_completed_iso)
    cur = now if now is not None else now_epoch()
    until = calculate_cooldown_until(last_epoch, cooldown_seconds, now=cur)
    return epoch_to_iso(until)
