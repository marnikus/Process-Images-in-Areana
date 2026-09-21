"""Page status — steady/busy/cooldown tracking for multi-page pool.

The **cooldown timer is the authority** (2026-09-21): `remaining_seconds` reads
the clock only, `is_cooling` is that value, and `is_free` refuses a page whose
timer still runs whatever the status label says. The status stays a label for
the UI (steady / busy / waiting…), never a second source of truth — that
divergence is what hid the user's countdown.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from app.core.cooldown import remaining_seconds as _remaining
from app.core.tab_alias import format_alias


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
    worker_no: int = 0  # pool join order, 1-based, assigned once by PagePool (D-3)
    alias_no: int = 0  # readable-id number, assigned once by PagePool, persisted (D-5)
    owner: str = ""    # logged-in account of this tab, from the owner probe (D-5)

    @property
    def alias(self) -> str:
        """Readable handle `{email}_{4 digits}` — '' until the pool numbers the tab."""
        return format_alias(self.owner, self.alias_no)

    @property
    def label(self) -> str:
        """What every view and log prints: the alias, else the short id (D-7)."""
        return self.alias or (self.tab_id or "")[:12]

    def is_free(self) -> bool:
        """Ready for a job: steady, connected, and **no live timer** (D-1)."""
        return (self.status == PageStatus.STEADY and self.is_connected
                and self.remaining_seconds() == 0)

    def is_busy(self) -> bool:
        return self.status in (
            PageStatus.BUSY,
            PageStatus.WAITING_GENERATION,
            PageStatus.WAITING_CAPTCHA,
        )

    def remaining_seconds(self, now: float | None = None) -> int:
        """Live countdown from the timer field only — never from the status (D-1)."""
        return _remaining(self.cooldown_until, now)

    def is_cooling(self, now: float | None = None) -> bool:
        """True while a live timer gates this tab, whatever the status says."""
        return self.remaining_seconds(now) > 0

    def clear_timer(self) -> None:
        """Drop the pause fields and nothing else (history stays)."""
        self.cooldown_until = 0.0
        self.cooldown_total = 0
        self.cooldown_reason = ""

    def try_expire(self, now: float | None = None) -> bool:
        """Flip an expired COOLDOWN to STEADY; never voids a live timer.

        Returns True only for a real COOLDOWN → STEADY flip (the value
        `refresh_expired` reports as "freed"), while stale timer fields of any
        other status are cleared silently.
        """
        if self.is_cooling(now):
            return False
        flipped = self.status == PageStatus.COOLDOWN
        self.clear_timer()
        if not flipped:
            return False
        self.status = PageStatus.STEADY
        self.current_job_id = None
        self.current_image = None
        self.last_steady_at = now_iso()
        self.error = None
        return True

    def to_dict(self) -> dict:
        return {
            "ws_url": self.ws_url,
            "tab_id": self.tab_id,
            "worker_no": self.worker_no,
            "title": self.title,
            "url": self.url,
            "status": self.status.value if isinstance(self.status, Enum) else str(self.status),
            "is_connected": self.is_connected,
            "current_job_id": self.current_job_id,
            "current_image": self.current_image or "",
            "alias_no": self.alias_no,
            "owner": self.owner,
            "busy_since": self.busy_since,
            "error": self.error,
            "jobs_completed": self.jobs_completed,
            **_cooldown_dict(self),
        }


def _cooldown_dict(p: "PageInfo") -> dict:
    """The cooldown/penalty half of the wire form."""
    return {
        "last_steady_at": p.last_steady_at,
        "cooldown_until": p.cooldown_until,
        "cooldown_total": p.cooldown_total,
        "captcha_count": p.captcha_count,
        "rate_limit_count": p.rate_limit_count,
        "pending_penalty": p.pending_penalty,
        "last_job_at": p.last_job_at,
        "cooldown_reason": p.cooldown_reason,
    }
