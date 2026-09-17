# Fix 2026-09-16 — New Start Waits for Active Cooldown (00:00 + ready)

User rule: pressing Start while a URL still shows a cooldown timer must not
run jobs — the batch waits until the timer reaches 00:00 and the tab status
is ready again.

## Implementation

- `cooldown_service.wait_for_batch_ready(pool, tab_ids, bridge)` (tested):
  batch-start gate; logs "New Start during cooldown — tab … must reach
  00:00 + ready first", then reuses `wait_for_tab_ready` per tab (tabs cool
  concurrently, so sequential waits sum to the max, not the total).
  Cancel aborts the start (returns False).
- `Bridge._do_run_batch` (single-mode fall-through only): after the parallel
  decision, ensures the primary page exists and awaits the batch-start gate
  before the first image. Cancel during the wait resets run state to idle.
  Parallel mode intentionally unchanged: ready tabs work immediately while
  cooling tabs wait (spec 03 independence, one shared queue).
- `cooldown_service.resolve_primary_tab(pool, tab_id)` (tested): when the
  captured tab id is empty (e.g. unparsable ws_url), adopts the single pooled
  page so the gate/finish can never be silently skipped.

`pytest 134 passed`, `verify_quality --changed --allow-legacy` 0 fails.
