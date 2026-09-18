"""Data and limits shared by captcha recording components."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import secrets

VALID_ACTOR_LABELS = frozenset({"unknown", "bot", "manual", "mixed"})
VALID_RESULT_LABELS = frozenset({"unknown", "passed", "failed"})
VALID_LABELS = VALID_ACTOR_LABELS  # compatibility for schema-v1 callers
FINAL_OUTCOMES = frozenset({
    "solved", "manual", "page_error", "token_stale", "auto_failed",
    "stopped", "interrupted",
})

#: Observed verdict at the solve edge — never a claim of server acceptance.
ACCEPTANCE_STATES = frozenset({
    "none", "accepted_candidate", "not_accepted", "page_error", "stale",
})

#: Terminal evidence is reserved so a long encounter can never lose its edges.
RESERVED_EVENTS = 50
RESERVED_SNAPSHOTS = 2
PROTECTED_EVENT_KINDS = frozenset({"state", "milestone", "solve_report", "warning"})


@dataclass(frozen=True)
class RecordingLimits:
    poll_interval_sec: float = 0.5
    checkpoint_interval_sec: float = 2.0
    max_events: int = 2_000
    max_snapshots: int = 25
    max_snapshot_chars: int = 512_000
    max_body_chars: int = 16_384


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_session_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{stamp}-{secrets.token_hex(4)}"
