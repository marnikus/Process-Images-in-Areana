"""Page status — steady/busy tracking + cooldown per tab."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


class PageStatus(str, Enum):
    STEADY = "steady"
    BUSY = "busy"
    WAITING_GENERATION = "waiting_generation"
    WAITING_CAPTCHA = "waiting_captcha"
    COOLDOWN = "cooldown"
    ERROR = "error"
    DISCONNECTED = "disconnected"


@dataclass
class PageInfo:
    ws_url: str = ""
    tab_id: str = ""
    title: str = ""
    url: str = ""
    status: PageStatus = PageStatus.STEADY
    is_connected: bool = False
    current_job_id: Optional[str] = None
    busy_since: Optional[str] = None
    last_steady_at: Optional[str] = None
    error: Optional[str] = None
    # cooldown per tab
    cooldown_until: Optional[str] = None
    cooldown_seconds: int = 300
    captcha_penalty_seconds: int = 900
    captcha_count: int = 0
    last_completed_at: Optional[str] = None

    def is_in_cooldown(self, now_epoch: Optional[float] = None) -> bool:
        until = _parse_iso(self.cooldown_until)
        if until is None:
            return False
        cur = now_epoch if now_epoch is not None else datetime.now(timezone.utc).timestamp()
        return cur < until

    def remaining_cooldown(self, now_epoch: Optional[float] = None) -> int:
        until = _parse_iso(self.cooldown_until)
        if until is None:
            return 0
        cur = now_epoch if now_epoch is not None else datetime.now(timezone.utc).timestamp()
        return max(0, int(until - cur))

    def is_free(self) -> bool:
        if self.status != PageStatus.STEADY:
            return False
        if not self.is_connected:
            return False
        if self.is_in_cooldown():
            return False
        return True

    def is_busy(self) -> bool:
        return self.status in (
            PageStatus.BUSY,
            PageStatus.WAITING_GENERATION,
            PageStatus.WAITING_CAPTCHA,
        )

    def to_dict(self) -> dict:
        base = {
            "ws_url": self.ws_url,
            "tab_id": self.tab_id,
            "title": self.title,
            "url": self.url,
            "status": self.status.value if isinstance(self.status, Enum) else str(self.status),
            "is_connected": self.is_connected,
            "current_job_id": self.current_job_id,
            "busy_since": self.busy_since,
            "last_steady_at": self.last_steady_at,
            "error": self.error,
            "cooldown_until": self.cooldown_until,
            "cooldown_seconds": self.cooldown_seconds,
            "captcha_penalty_seconds": self.captcha_penalty_seconds,
            "captcha_count": self.captcha_count,
            "last_completed_at": self.last_completed_at,
            "cooldown_remaining": self.remaining_cooldown(),
            "in_cooldown": self.is_in_cooldown(),
        }
        return base
