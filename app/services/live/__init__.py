"""Live run package (S4+): the always-live queue.

* `bus`  — `LiveBus` / `live_bus(bridge)`: the one wake event.
* `feed` — `commit_queue` (the one queue-write funnel), `eligible_images`
  (re-export of `core.run_scope.live_scope`), `recover_stale_processing`,
  `clear_row_assignments`.

Layer: services — imports core and sibling services only; never Qt or
panels (the undo push reaches the panel layer through a bridge seam).
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
    "clear_row_assignments",
    "commit_queue",
    "eligible_images",
    "recover_stale_processing",
    "state_lock",
]
