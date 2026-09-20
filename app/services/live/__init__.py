"""Live run services (S4+): the bus every queue write wakes, the feed a pass claims from,
the supervisor that keeps the run live (S5).

Facade re-exports only (RULE 16.0 waiver: no logic here). `supervisor`,
`reconcile`, `url_policy` and `debug_view` (S5/S6) are imported as modules
(`from app.services.live import reconcile`) — they pull the orchestrator /
planner in, so they are not re-exported symbol by symbol.
"""

from .bus import LiveBus, live_bus
from .feed import (
    ELIGIBLE,
    clear_row_assignments,
    commit_queue,
    eligible_images,
    recover_stale_processing,
    requeue_for_start,
    state_lock,
)

__all__ = [
    "LiveBus",
    "live_bus",
    "ELIGIBLE",
    "eligible_images",
    "commit_queue",
    "recover_stale_processing",
    "requeue_for_start",
    "clear_row_assignments",
    "state_lock",
]
