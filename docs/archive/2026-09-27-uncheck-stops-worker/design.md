# Fix: an unchecked URL row stops its worker at once (I-68)

*2026-09-27 — owner report: “Test if Job sending correct to the correct web page if url uncheck during
cooldown or just unchecked from worker list.” Observed: the Chrome URL was unchecked, yet the next
two jobs went to that Chrome page instead of the two Firefox pages.*

## 1. Root cause (reproduced before any fix)

The checkbox is the “use for job” gate (I-33): a tab may take a job only while a **checked** row owns
it. Two independent defects let an unchecked tab keep taking jobs:

1. **The gate was a pass-time copy.** `dispatch_parallel` computed `allowed = enabled_tab_ids(urls)`
   once and stored it in `DispatchCtx.allowed`. The sequential lane did the same with
   `BatchCtx.allowed`. The rows (`plan.urls`) were also copied, and already filtered to checked rows.
   Since I-57 the feeder pass stays open for as long as the queue has work, so an uncheck never
   reached the gate. The list copy made it worse: ✕ (remove) and undo replace `state.urls`, so the
   copy kept rows that no longer existed.
2. **Leaving the pool is not a gate.** Unchecking does take the tab out of the pool
   (`commit_urls` → `enforce_pool_membership`, I-56). The exception is a tab whose job is still on it
   (`current_image` set: generating, saving, the New Chat reset). Its exit is deferred to “the next
   reconcile”. When that job ends, `_finish_page_safely` wakes the bus (`page free`). The feeder's
   acquire runs synchronously on that wake. The reconciler, woken by the same event, first awaits a
   tab listing. So the feeder always won, and the frozen set handed it the unchecked tab.

The sequential lane had a third, smaller hole: *claim tab → wait out its cooldown → run*, with no
re-check after the wait.

RED at base (the new tests, run against the old code with the old call signature):

```
AssertionError: a job went to the unchecked Chrome tab:
  [('pic1.png','chrome'), ('pic2.png','fx1'), ('pic3.png','fx2'), ('pic4.png','chrome')]
```

This is the owner's report exactly: the real `Bridge.toggle_url` slot was clicked while Chrome's job
ran, and the next job still went to Chrome. The run was 6 of 7 dispatcher tests RED; only the “idle
uncheck” case passed, because there the pool exit alone keeps the tab out.

## 2. Design — one live gate, read at use

* **`auto_connect.live_rows(bridge)` / `live_allowed(bridge)`** are the single source of truth: the
  rows exactly as they are in `bridge.state.urls` at this instant. No run structure copies them any
  more. `DispatchCtx.urls/allowed` and `BatchCtx.urls/allowed` are deleted, and
  `dispatch_parallel(bridge, pool, images)` / `run_one_image_on_page(bridge, pool, img)` lost their
  snapshot argument.
* **`page_gate.py`** (new, split from `multi_page_dispatcher`, RULE 18.2) decides WHICH page may take
  a job: free **and** checked now. `FreeWaitSpec.allowed_now` is a callable evaluated on **every**
  attempt. A job already waiting inside `wait_free_in` therefore sees an uncheck on its very next
  attempt, and the acquire and the check happen under the same pool lock. The feeder
  (`_acquire_page`) supplies `lambda: ac.live_allowed(bridge)`.
* **`run_tab.py`** (new, split from `batch_orchestrator`, RULE 18.2) owns the sequential lane's tab
  claim (`resolve_and_claim_tab`, moved unchanged) plus `still_checked(bridge, tab_id)`.
  `batch_orchestrator._claim_ready_tab` runs *claim → cooldown wait → still checked?* If the tab is no
  longer checked, it claims again. That picks another checked tab, or stops with “No usable checked
  tab left” when none is left. It gives up after `_RECLAIM_TRIES = 3` if the checked tabs keep
  flipping (RULE 7: bounded).
* **Both directions:** a row re-checked mid-pass takes waiting work at once. This follows from the
  same live read and is tested.
* **Unchanged on purpose:** pool membership (I-56/I-58) still removes an unchecked idle tab at once
  and defers a busy one. A job already running on the tab is never aborted (RULE 15); unchecking
  means “no NEW job”. The supervisor's `plan_pass` keeps its fresh per-pass read, since it decides
  immediately.

Rejected: *finishing the deferred pool exit in the job's finally block.* It would narrow the race
but not close it: an uncheck during the post-job reset still leaves a window. It would also
duplicate the membership rule in a second place. The gate itself must be live.

## 3. Tests (`tests/test_uncheck_gate.py`, 11 — real PagePool / feeder / membership gate / Bridge)

| Test | Scenario |
|---|---|
| `test_the_report_uncheck_while_chrome_finishes_sends_the_next_jobs_to_firefox` | Uncheck while Chrome's job runs (exit deferred) → d, e go to fx1/fx2 |
| `test_unchecked_during_cooldown_the_tab_gets_nothing_when_the_timer_ends` | Chrome cooling, unchecked, still pooled, timer expires → no job |
| `test_uncheck_while_idle_takes_the_tab_out_at_once` | Worker-list uncheck while idle → pool exit, jobs to Firefox |
| `test_a_job_already_waiting_for_a_page_rereads_the_checkbox` | Job inside the free-page wait → keeps waiting for fx1 |
| `test_a_removed_row_stops_its_tab_too` | ✕ rebuilds `state.urls` → that tab gets nothing |
| `test_a_row_checked_mid_pass_takes_work_at_once` | Re-check → the idle tab takes the waiting image |
| `test_live_allowed_reads_the_rows_as_they_are_now` | Unit: `live_allowed` |
| 3 × `test_sequential_lane_*` | Uncheck during the cooldown wait → moves / stops / bounded give-up |
| `test_the_real_toggle_url_slot_stops_the_chrome_tab_mid_pass` | End to end through `Bridge.toggle_url` |

## 4. Gates

pytest 2,689 passed, JS 454 passed (was 2,677; +11 in `test_uncheck_gate.py`, +1
`test_a_broken_ui_never_stops_the_dispatcher`, which keeps the dispatcher's coverage ratchet at 90.7 % after the
well-covered gate moved to `page_gate.py` (100 %); the existing dispatcher tests now put rows in
`bridge.state.urls` via `with_urls`). jscpd 0.921 % (baseline 1.24 %). The quality gate shows only the 5 pre-existing `max_cc` ratchet
fails (main.py, json_store, bus, hashing, win_find), none in touched files. Every changed or new
function: CC ≤ 7, cognitive ≤ 8, nesting ≤ 2, ≤ 19 lines, ≤ 3 params.

RULE 18 sizes, before → after:

| File | Lines |
|---|---|
| `batch_orchestrator.py` | 460 → 391 |
| `multi_page_dispatcher.py` | 492 → 440 |
| `run_tab.py` (new) | 99 |
| `page_gate.py` (new) | 66 |
