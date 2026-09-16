"""PagePool — inherits core, adds cooldown, per RULE 18/16.

RULE 18: file 150-300 LOC ideal, current ~110 LOC.
RULE 16: func ≤30, class ≤150, methods ≤15, CC ≤10, nesting ≤4.
"""

from __future__ import annotations

from typing import Optional

from .page_pool_core import PagePoolCore, PageWaitOpts
from .page_pool_cooldown import (
    apply_penalty,
    check_cooldowns,
    is_in_cooldown,
    mark_steady_with_cooldown,
    remaining,
    reset_cooldown,
    set_cooldown,
)
from .page_status import PageInfo


class PagePool(PagePoolCore):
    def mark_steady(self, tab_id: str) -> bool:
        return mark_steady_with_cooldown(self, tab_id)

    def get_counts(self):
        try:
            check_cooldowns(self)
        except Exception:
            pass
        return super().get_counts()

    def status_snapshot(self) -> dict:
        try:
            check_cooldowns(self)
        except Exception:
            pass
        return super().status_snapshot()

    def set_cooldown(self, tab_id: str, cooldown_seconds: int, last_completed_iso: Optional[str] = None) -> bool:
        return set_cooldown(self, tab_id, cooldown_seconds, last_completed_iso)

    def reset_cooldown(self, tab_id: str) -> bool:
        return reset_cooldown(self, tab_id)

    def apply_captcha_penalty(self, tab_id: str, penalty_seconds: int) -> bool:
        return apply_penalty(self, tab_id, penalty_seconds)

    def is_in_cooldown(self, tab_id: str) -> bool:
        return is_in_cooldown(self, tab_id)

    def get_cooldown_remaining(self, tab_id: str) -> int:
        return remaining(self, tab_id)

    def check_cooldowns(self) -> int:
        return check_cooldowns(self)
