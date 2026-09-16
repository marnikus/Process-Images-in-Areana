"""PagePool cooldown handling — pure functions + manager.

RULE 18: file 150-300 LOC ideal, current ~140 LOC.
RULE 16: func ≤30 LOC, CC ≤10, nesting ≤4, params ≤4.
"""

from __future__ import annotations

from typing import Optional

from .page_status import PageInfo, PageStatus, now_iso
from app.core.cooldown import (
    apply_captcha_penalty,
    calculate_cooldown_until,
    epoch_to_iso,
    now_epoch,
    parse_iso_to_epoch,
)


def _get_page(pool, tab_id: str) -> Optional[PageInfo]:
    try:
        return pool.get_page(tab_id)
    except Exception:
        return None


def set_cooldown(pool, tab_id: str, cooldown_seconds: int, last_completed_iso: Optional[str] = None) -> bool:
    p = _get_page(pool, tab_id)
    if not p:
        return False
    last_epoch = parse_iso_to_epoch(last_completed_iso) if last_completed_iso else now_epoch()
    until_epoch = calculate_cooldown_until(last_epoch, cooldown_seconds, now=now_epoch())
    p.cooldown_until = epoch_to_iso(until_epoch)
    p.cooldown_seconds = int(cooldown_seconds)
    p.last_completed_at = last_completed_iso or now_iso()
    p.status = PageStatus.COOLDOWN
    return True


def reset_cooldown(pool, tab_id: str) -> bool:
    p = _get_page(pool, tab_id)
    if not p:
        return False
    p.cooldown_until = None
    p.captcha_count = 0
    if p.status == PageStatus.COOLDOWN:
        p.status = PageStatus.STEADY
        p.last_steady_at = now_iso()
    return True


def apply_penalty(pool, tab_id: str, penalty_seconds: int) -> bool:
    p = _get_page(pool, tab_id)
    if not p:
        return False
    cur_until = parse_iso_to_epoch(p.cooldown_until)
    new_until = apply_captcha_penalty(cur_until, penalty_seconds, now=now_epoch())
    p.cooldown_until = epoch_to_iso(new_until)
    p.captcha_count += 1
    p.status = PageStatus.COOLDOWN
    return True


def is_in_cooldown(pool, tab_id: str) -> bool:
    p = _get_page(pool, tab_id)
    if not p:
        return False
    return p.is_in_cooldown()


def remaining(pool, tab_id: str) -> int:
    p = _get_page(pool, tab_id)
    if not p:
        return 0
    return p.remaining_cooldown()


def check_cooldowns(pool) -> int:
    moved = 0
    try:
        cur = now_epoch()
        # access _pages directly if possible
        pages = getattr(pool, "_pages", {})
        for p in list(pages.values()):
            if p.status == PageStatus.COOLDOWN and p.cooldown_until:
                until = parse_iso_to_epoch(p.cooldown_until)
                if until is None or cur >= until:
                    p.status = PageStatus.STEADY
                    p.last_steady_at = now_iso()
                    moved += 1
    except Exception:
        pass
    return moved


def _set_steady(p: PageInfo):
    p.status = PageStatus.STEADY
    p.current_job_id = None
    p.busy_since = None
    p.last_steady_at = now_iso()
    p.error = None


def _set_cooldown_state(p: PageInfo):
    p.status = PageStatus.COOLDOWN
    p.current_job_id = None
    p.busy_since = None
    p.last_steady_at = now_iso()
    p.error = None


def mark_steady_with_cooldown(pool, tab_id: str) -> bool:
    p = _get_page(pool, tab_id)
    if not p:
        return False
    if p.cooldown_until:
        until_epoch = parse_iso_to_epoch(p.cooldown_until)
        if until_epoch and until_epoch > now_epoch():
            _set_cooldown_state(p)
            return True
    _set_steady(p)
    return True
