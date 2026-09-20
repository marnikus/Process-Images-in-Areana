"""Live run services (S4+): the bus every queue write wakes, the feed a pass claims from.

Facade re-exports only (RULE 16.0 waiver: no logic here). Stages add
`supervisor` (S5), `reconcile` / `url_policy` / `debug_view` (S6+).
"""

from .bus import LiveBus, live_bus
from .feed import (
    ELIGIBLE,
    clear_row_assignments,
    commit_queue,
    eligible_images,
    recover_stale_processing,
    state_lock,
)

__all__ = [
    "LiveBus",
    "live_bus",
    "ELIGIBLE",
    "eligible_images",
    "commit_queue",
    "recover_stale_processing",
    "clear_row_assignments",
    "state_lock",
]
