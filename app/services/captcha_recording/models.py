"""Data and limits shared by captcha recording components."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import secrets

VALID_LABELS = frozenset({"unknown", "bot", "manual"})
FINAL_OUTCOMES = frozenset({
    "solved", "manual", "page_error", "token_stale", "auto_failed",
    "stopped", "interrupted",
})


@dataclass(frozen=True)
class RecordingLimits:
    poll_interval_sec: float = 0.5
    checkpoint_interval_sec: float = 2.0
    max_events: int = 2_000
    max_snapshots: int = 25
    max_snapshot_chars: int = 2_000_000
    max_body_chars: int = 65_536


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_session_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{stamp}-{secrets.token_hex(4)}"
