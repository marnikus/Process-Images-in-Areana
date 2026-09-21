"""Live run package (S4+): the always-live queue.

* `bus`  — `LiveBus` / `live_bus(bridge)`: the one wake event.
* `feed` — `commit_queue` (the one queue-write funnel), `eligible_images`
  (re-export of `core.run_scope.live_scope`), `queued_images` (under the
  retry cap), `recover_stale_processing`, `clear_row_assignments`.
* `supervisor` — `run_live` (the always-live loop, S5), `set_run_state`
  (the one run-state writer), `plan_pass` / `PassPlan` — import it as a
  submodule (`from app.services.live import supervisor`): it is NOT
  re-exported here because the dispatcher underneath it (`supervisor` →
  `batch_orchestrator` → `multi_page_dispatcher`) rides this package's bus
  and queue reader, and an eager re-export would make that a cycle (B-2).

Layer: services — imports core and sibling services only; never Qt or
panels (the undo push reaches the panel layer through a bridge seam).
"""

from .bus import LiveBus, live_bus
from .feed import (
    ELIGIBLE,
    PROCESSING_REFUSAL,
    clear_row_assignments,
    commit_queue,
    eligible_images,
    queued_images,
    recover_stale_processing,
    state_lock,
)

__all__ = [
    "LiveBus",
    "live_bus",
    "ELIGIBLE",
    "PROCESSING_REFUSAL",
    "clear_row_assignments",
    "commit_queue",
    "eligible_images",
    "queued_images",
    "recover_stale_processing",
    "state_lock",
]
