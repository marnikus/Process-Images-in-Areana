"""app.services.live — the live-run core (S4+).

Facade re-exports only (RULE 16.0 waiver: this module intentionally holds no
logic — every symbol lives in `bus.py` / `feed.py`; tests import from those).
"""

from .bus import LiveBus, live_bus
from .feed import (
    clear_row_assignments,
    commit_queue,
    eligible_images,
    recover_stale_processing,
    reset_to_pending,
    set_undo_hook,
)

__all__ = [
    "LiveBus",
    "live_bus",
    "clear_row_assignments",
    "commit_queue",
    "eligible_images",
    "recover_stale_processing",
    "reset_to_pending",
    "set_undo_hook",
]
