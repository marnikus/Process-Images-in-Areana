"""Page status — steady/busy tracking for multi-page pool."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PageStatus(str, Enum):
    STEADY = "steady"
    BUSY = "busy"
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

    def is_free(self) -> bool:
        return self.status == PageStatus.STEADY and self.is_connected

    def is_busy(self) -> bool:
        return self.status in (
            PageStatus.BUSY,
            PageStatus.WAITING_GENERATION,
            PageStatus.WAITING_CAPTCHA,
        )

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
        }
