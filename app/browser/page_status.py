"""Page status — steady/busy/cooldown tracking for multi-page pool."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from app.core.cooldown import remaining_seconds as _remaining


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PageStatus(str, Enum):
    STEADY = "steady"
    BUSY = "busy"
    COOLDOWN = "cooldown"
    WAITING_GENERATION = "waiting_generation"
    WAITING_CAPTCHA = "waiting_captcha"
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
    cooldown_until: float = 0.0
    cooldown_total: int = 0
    captcha_count: int = 0
    rate_limit_count: int = 0
    pending_penalty: int = 0
    last_job_at: Optional[str] = None
    cooldown_reason: str = ""
    jobs_completed: int = 0
    current_image: Optional[str] = None

    def is_free(self) -> bool:
        return self.status == PageStatus.STEADY and self.is_connected

    def is_busy(self) -> bool:
        return self.status in (
            PageStatus.BUSY,
            PageStatus.WAITING_GENERATION,
            PageStatus.WAITING_CAPTCHA,
        )

    def remaining_seconds(self, now: float | None = None) -> int:
        """Live countdown; 0 unless actively cooling."""
        if self.status != PageStatus.COOLDOWN:
            return 0
        return _remaining(self.cooldown_until, now)

    def is_cooling(self, now: float | None = None) -> bool:
        """True while the cooldown timer gates the next job."""
        return self.status == PageStatus.COOLDOWN and self.remaining_seconds(now) > 0

    def try_expire(self, now: float | None = None) -> bool:
        """Flip expired COOLDOWN to STEADY; single source (no copies)."""
        if self.status != PageStatus.COOLDOWN:
            return False
        if self.is_cooling(now):
            return False
        self.status = PageStatus.STEADY
        self.current_job_id = None
        self.current_image = None
        self.cooldown_until = 0.0
        self.cooldown_total = 0
        self.cooldown_reason = ""
        self.last_steady_at = now_iso()
        self.error = None
        return True

    def to_dict(self) -> dict:
        return {
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
            "cooldown_total": self.cooldown_total,
            "captcha_count": self.captcha_count,
            "rate_limit_count": self.rate_limit_count,
            "pending_penalty": self.pending_penalty,
            "last_job_at": self.last_job_at,
            "cooldown_reason": self.cooldown_reason,
            "jobs_completed": self.jobs_completed,
            "current_image": self.current_image or "",
        }
