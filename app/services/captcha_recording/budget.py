"""Write budget with a reserved tail, so terminal evidence is never dropped.

A long captcha encounter is exactly the case a comparison cares about, and it is
also the case that spends the most mutation/network rows. Regular rows therefore
hit a lower ceiling and the reserved tail stays available for the named edges.
"""

from __future__ import annotations

from typing import Any

from .models import PROTECTED_EVENT_KINDS, RESERVED_EVENTS, RESERVED_SNAPSHOTS


class Budget:
    """Count what one recording wrote and refuse rows that would lose its edges."""

    def __init__(self, limits: Any):
        self.limits = limits
        self.counts: dict[str, int] = {
            "event": 0, "mutation": 0, "network": 0, "snapshot": 0,
            "milestone": 0, "regular_snapshot": 0,
        }
        self.truncated: set[str] = set()

    def allow_event(self, kind: str) -> bool:
        """Regular rows stop early; states/milestones keep the reserved tail."""
        if self.counts["event"] >= self.limits.max_events:
            self.mark("events")
            return False
        if kind in PROTECTED_EVENT_KINDS:
            return True
        return self.counts["event"] < max(0, self.limits.max_events - RESERVED_EVENTS)

    def allow_snapshot(self, force: bool) -> bool:
        """Forced checkpoints are edges (detect/resolved) and keep their slots."""
        if self.counts["snapshot"] >= self.limits.max_snapshots:
            return False
        if force:
            return True
        return self.counts["regular_snapshot"] < max(0, self.limits.max_snapshots - RESERVED_SNAPSHOTS)

    def count_snapshot(self, force: bool) -> None:
        self.counts["snapshot"] += 1
        if not force:
            self.counts["regular_snapshot"] += 1

    def mark(self, reason: str) -> None:
        self.truncated.add(str(reason))

    def truncated_list(self) -> list[str]:
        return sorted(self.truncated)
