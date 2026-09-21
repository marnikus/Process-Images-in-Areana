# Design — the pool never holds a worker no URL row owns (2026-09-21)

User report (screenshot + log): "i have 2 url only but the pool have 4 worker.
that is not correct. should be same as url or max as url never more. It mean
here is bug the pool add or hold more worker that should."

Baseline radon (6.0.1, this tree): `url_policy.py` `pool_exits A(5)`,
`_pooled_unchecked A(6)`; `reconcile.py` `_enforce_membership B(8)`,
`_remove_rows B(10)`; `url_queue.py` `exit_pool_for_unchecked A(5)`,
`commit_urls A(1)`. Every edited function stays ≤ CC 10, ≤ 30 LOC, nesting ≤ 4,
and no function in `url_queue.py` may grow past the file's baselined maximum
(`max_func_loc` 14).

## Reproduced first (RULE 16.6 step 1)

`/tmp/diag/orphan.py` — real `Bridge` + real `PagePool` + the real reconciler
pass with a realistic 32-hex tab id, one surviving row and three pooled pages
(the row's tab, a page whose row the pass had removed, and a page that never
had a row):

```
rows: 1 | pool: ['aaaaaaaa', 'bbbbbbbb', 'cccccccc']
report: Report(... removed=0, stale=2, ...)   # "2 stale" — and nothing left
```

So the pass *sees* the mismatch (its own summary says `2 stale`) and does
nothing about it: the pool only ever grew. That is the reported behaviour.

## Findings

* **F-1 rows lead, the pool does not follow.** `url_policy.pool_exits` looks
  only at *unchecked rows* — its docstring says so: "Tabs with no row are not
  the checkbox's business (manual pool joins keep working)". Every other way a
  row can disappear leaves its pooled page behind forever: the removal table
  (`tab_gone` after 2 misses, `invalid`, `pattern_mismatch`, duplicates), the
  ✕ button, an undo, a preset load. The pool is only ever emptied by the ✕ on
  the pool row, `clear_page_pool`, or unchecking a row that still exists
  (I-56). Nothing prunes it, so it accumulates across a whole session — the
  screenshot's `#7`/`#9` are exactly that: pages whose URL rows the log shows
  being removed ("🔻 URL removed … tab closed (2 reconciles)").
* **F-2 the zombies are not harmless.**
  * `pick_primary_ws` (`auto_connect`) takes the **first pooled page** with
    `is_connected` — verified directly (`/tmp/diag/primary.py`: an ownerless
    page inserted before the owned one wins the pick) — so the primary
    connection latches onto a page no row owns,
    and the `ensure_primary_connected` 500 ms tick keeps re-connecting it.
    That is the log's `CDP error: Connect failed for ws://…/2542E073… last=
    server rejected WebSocket connection: HTTP 500` / `❌ Chrome connection
    error` / `🔌 Chrome disconnected` storm (every ~2.5 s), and the failing
    `🔄 Resubmit … Not connected (FAILED)` cascade that follows: the jobs' page
    context belonged to a page the URL list had already dropped.
  * `page_recovery._reconnect_if_closed` keeps re-attaching the dead sockets
    (`🔌 CDP socket closed — reconnecting to the same tab …` every ~3 s), and
    `PagePool.status_snapshot` counts them, so Live Debug says
    "4 PAGES 2 STEADY — PARALLEL READY" and `2 of 2 rows can receive a job`
    while two of those four workers can never receive anything.
* **F-3 the count is the user's contract.** The URL list is the only place a
  worker is authorised; a worker count larger than the row count is a lie no
  matter how the extra pages got there.

## Decisions

* **D-1 (F-1) one membership rule, extended with the missing half.**
  `url_policy.pool_exits` returns `PoolExit(tab_id, reason, row)` and reports
  two reasons: `unchecked` (row still exists, checkbox off — I-56) and
  **`orphan`** (no row owns the pooled tab at all — the new half). The busy
  gate is unchanged (`busy_tabs` / `tab_has_live_job`, RULE 15 — nothing
  leaves mid-job), and `pool_exits` stays the ONE decision; its wording moves
  next to it (`exit_line` / `defer_line`) so both enforcers log the identical
  sentence.
* **D-2 (F-1, F-3) the same two enforcers, now both reasons.** The UI enforcer
  `url_queue.enforce_pool_membership` (renamed from `exit_pool_for_unchecked`,
  still called from `commit_urls`, the ONE row write path) makes a hand edit
  act at once — ✕ a row, uncheck it, undo it: its worker leaves in the same
  commit. The pass enforcer `reconcile._enforce_membership` catches everything
  else (removal table, sweep, preset load, import, a row replaced by undo),
  every pass, ≤ one interval.
* **D-3 (F-3) ownership, not liveness, decides.** The rule is "is a row
  responsible for this tab", not "did the last fetch list it". A pool page
  whose tab the fetch no longer lists but whose row still exists (the 2-miss
  window, or a deferred removal under a running job) stays: rows lead the
  pool by design, so the hysteresis and the busy deferral keep working. Once
  the row is gone, the page follows in the same pass.
* **D-4 (F-2) consequences, no new code.** With the orphans gone,
  `pick_primary_ws` can no longer latch the primary connection onto a page no
  row owns, the retry/hammering stops by itself, and the pool snapshot the
  Live Debug window renders equals the worker list the URL table authorises.
* **D-5 this supersedes one sentence of 2026-09-21 D-3.** "Tabs without any
  row are not the checkbox's business" is replaced by the user's contract: a
  manual "Add Selected Tab to Pool" is honoured while a row owns the tab, and
  a tab with no row (wrong host, pattern-filtered, or its row deleted) leaves
  the pool with a named reason instead of lingering as a fake worker. Nothing
  else of D-3/D-4 changes — the checkbox still owns membership, the busy gate
  still defers.

## Rejected alternatives (dishonest reductions, RULE 16.6)

* Prune only inside the reconciler pass — a ✕ on a URL row would leave a fake
  worker for up to one interval (60 s at the maximum setting) although the
  same commit already runs the leave half for unchecked rows.
* Prune everything the fetch did not list — a Chrome restart, a failed
  `/json/list` (empty answer) or a port change would evict every worker at
  once; ownership is the persisted truth, liveness is not.
* Re-create a row for every pooled page (pool == rows by construction) —
  that would resurrect rows the removal table just deleted (`tab closed`,
  `pattern_mismatch`) and let the pool re-authorise a URL the user's pattern
  excludes.
* Delete pages inside `sync_pool_presence` — it is the pure flagger the
  presence report and Live Debug read (S6); a membership decision does not
  belong there.
* Count only "steady" pages in the snapshot so the numbers match — the pool
  would still hold the zombie clients, sockets and reconnect loops (F-2).

## Files

| File | Change |
|---|---|
| `app/services/live/url_policy.py` | `PoolExit`, `_unchecked_exits` (the old `_pooled_unchecked`, now typed), `_orphan_exits`, `_exit_text` + `exit_line` / `defer_line`, `pool_exits` rewritten |
| `app/services/live/reconcile.py` | `_enforce_membership` uses the exits + the shared wording |
| `app/ui/panels/url_queue.py` | `exit_pool_for_unchecked` → `enforce_pool_membership` (both reasons), called from `commit_urls` |
| `tests/test_pool_follows_rows.py` (new, 10) | the rule + the user's scenario (both enforcers) |
| `tests/test_reparse_pool_gate.py` | D-3 section adapted to `PoolExit` |

## Tests first (RED at `5b05b89`)

* `test_a_pooled_worker_with_no_row_leaves_the_pool` — pool {A,B,C}, rows [A] →
  pass → pool {A}. *RED: today all three stay and the pass reports "2 stale".*
* `test_the_pool_never_holds_more_workers_than_rows` — the reported case: 4
  pooled pages (one offline, two ownerless), 2 rows → after one pass
  `len(pool._pages) == len(rows) == 2`, and the two zombies are named in the
  log. *RED: 4 vs 2.*
* `test_deleting_a_row_takes_its_worker_out_at_once` — the `remove_url` slot:
  page gone in the same commit + `🚪` line. *RED: the page stays until the
  next pass.*
* `test_an_orphan_under_a_live_job_defers_once` — busy orphan stays this pass,
  one `⏸ Pool exit deferred …` line, second pass (job gone) removes it.
* `test_pool_exits_reports_reasons_for_both_halves` — `PoolExit.reason`
  `unchecked` / `orphan`, `row` present only for the first; wording via
  `exit_line`.
* `test_stale_page_with_a_row_stays` — the 2-miss window is not a membership
  decision (D-3): a pooled page whose fetch-line vanished but whose row is
  still there does not leave.
* `test_deleting_a_row_takes_its_worker_out_at_once` /
  `test_clearing_the_last_row_empties_the_pool` — the UI enforcer through the
  real `remove_url` slot. *RED: the pages stayed until the next pass.*
* `test_a_manual_join_with_no_row_left_the_worker_pool` — D-5 semantics.

Verified after the fix with the real reconciler (`/tmp/diag/pool_vs_rows.py`),
the reported state (4 pooled workers, 2 rows, Chrome listing only the two owned
tabs):

```
URL rows: 2
pool BEFORE: total=4 steady=3
pool AFTER : total=2 steady=2
   🚪 Worker cccccccccccc left the pool — no URL row owns it
   🚪 Worker dddddddddddd left the pool — no URL row owns it
```
