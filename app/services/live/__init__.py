"""Live run package (S4+): the always-live queue.

* `bus`  — `LiveBus` / `live_bus(bridge)`: the one wake event.
* `feed` — `commit_queue` (the one queue-write funnel), `eligible_images`
  (re-export of `core.run_scope.live_scope`), `queued_images` (under the
  retry cap), `recover_stale_processing`, `clear_row_assignments`.
* `supervisor` — `run_live` (the always-live loop, S5), `set_run_state`
  (the one run-state writer), `plan_pass` / `PassPlan`.

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
from .supervisor import PassPlan, plan_pass, run_live, set_run_state

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
    "PassPlan",
    "plan_pass",
    "run_live",
    "set_run_state",
]
