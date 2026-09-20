"""Live queue services (S4): the wake bus + the queue funnel.

RULE 16.0 waiver: this facade re-exports one name per symbol so panels import
from `app.services.live` — it holds no logic, only re-exports.
"""

from app.services.live.bus import LiveBus, live_bus
from app.services.live.feed import (
    ELIGIBLE,
    clear_row_assignments,
    commit_queue,
    eligible_images,
    push_queue_undo,
    recover_stale_processing,
)

__all__ = [
    "ELIGIBLE",
    "LiveBus",
    "clear_row_assignments",
    "commit_queue",
    "eligible_images",
    "live_bus",
    "push_queue_undo",
    "recover_stale_processing",
]
