"""Live run services (S4+): the bus every queue write wakes, the feed a pass claims from,
the supervisor that keeps the run live (S5).

Facade re-exports only (RULE 16.0 waiver: no logic here). Later stages add
`reconcile` / `url_policy` / `debug_view` (S6+). `supervisor` is imported as
a module (`from app.services.live import supervisor`) — it pulls the
orchestrator in, so it is not re-exported symbol by symbol.
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
