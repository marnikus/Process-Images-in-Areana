# S9 implementation and verification

2026-09-20 · base `747e23c` (S8) · scope: read-only live worker/queue detail,
not S10 consolidation. Follow RULE 8/16/17/18, frozen slots and goldens.

## Pre-implementation findings / interface adjustments

- `live_view` will use `feed.eligible_images` (core owns the rule), row.receiver,
  cadence and run state only; never sample or mutate the pool.
- Existing pool rows include job/image/status/busy_since and cooldown time, but
  **not pause-clock evidence**. `busy_since` is job start, not captcha start.
  `PauseClock.total` is charged after each settle, not continuously. The UI must
  not fabricate absorbed/remaining seconds from the job's elapsed time.
  New UI serializer `pool_debug.pool_snapshot(bridge)` wraps one existing pool
  snapshot and reads registered controllers' clocks without changing them. It
  adds optional per-worker last-settled pause evidence, and a fail-closed scope
  flag. The pool class and PageInfo stay unchanged. The existing pool emitter
  and getter delegate with same-line substitutions. Missing clock means unknown,
  not zero; last-settled numbers are labeled and are not advanced by the ticker.
- Progress pushes have the complete live payload. To populate a newly opened UI
  without waiting for a mutation, the **existing** `get_arena_state` getter adds
  the same payload inside `progress.live`; normal arena_state_updated remains
  unchanged. No new slot or signal. One boot read, then pushes; Refresh reads
  only the pool. A 1-second UI tick recalculates elapsed/cooldown/cadence locally,
  with no bridge traffic. Existing PagePool refresh behavior stays untouched.
- Malformed payloads retain the last good snapshot with an explicit stale/error
  message; an empty pool is a valid snapshot that clears all worker lines.
- Watcher OFF suppresses new captcha wording even for a stale waiting row;
  existing Page Pool content remains under its original owner.

## Quality budget before edits

Gate measurements at S8: debug_view max func 9/CC5, layout_state max func19/CC6,
bridge max func15/CC3/class95, page_pool panel max func16/CC7/class139. Existing
bridge and page_pool methods get only same-line serialization substitutions;
layout_state gets a small initial snapshot builder and swaps cadence to live_view.
New functions target <=20 LOC, <=4 parameters, CC<=10; new data/view leaf files
stay below 150 lines where one responsibility does not warrant padding. The S8
LiveDebugPanel stub intentionally grows into the planned S9 facade (not baselined).
No baseline recording, no new quality override. Frozen arena-app/listeners.js and
URL controls are not edited. Test evidence and final measurements follow below.

## RED at S8

Before any production edit: `pytest tests/test_live_debug_view.py` → **11 failed**
(missing `live_view`, missing `pool_debug`, missing `progress.live`/`pause`).
`node --test tests/js/test_live_debug_panel.mjs` → **6 passed / 8 failed**:
all existing S8 tests stay green; new cases fail on missing real DOM content.
Tests drive actual bridge methods and real index.html script order. Clock/signal/
CDP test doubles are boundaries, not the functions under test.
