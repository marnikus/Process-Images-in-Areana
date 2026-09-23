# Design — Reparse keeps its rows, re-check rejoins at once, one tab id (2026-09-21)

Three user reports against the merged tree (`d8fa79c`):

1. **Reparse** removes every URL row and never adds them back.
2. Re-checking a URL row does not return its tab to the worker pool.
3. The tab id in the POOL table does not match the id on the in-page **worker badge**.

Baseline radon (6.0.1, this tree): `reconcile.py` `_remove_rows B(10)`,
`_sweep_rows B(9)`, `_enforce_membership B(8)`, `_commit B(7)`,
`_join_and_sync B(6)`, `_pass A(3)`, `reconcile_loop A(2)`;
`page_pool.py` `do_connect_page_pool B(6)`, `leave_pool A(2)`;
`url_queue.py` `toggle_url A(2)`, `exit_pool_for_unchecked A(5)`,
`commit_urls A(1)`. Every edited function stays ≤ CC 10, ≤ 30 LOC, nesting ≤ 4.

## What was verified before designing (RULE 16.6 step 1)

Two production-faithful harnesses drove the real objects, and the *happy path*
is not broken:

* `/tmp/diag/prod_e2e.py` — real `Bridge`, real `start_url_reconciler` loop,
  real `CDPClient` (real `aiohttp`/HTTP `/json/list` fetch, real
  `connect_with_lock`, 32-hex target ids, mixed `localhost`/`127.0.0.1` ws
  hosts), real `auto_connect_scan`/`toggle_url` slots, fake websockets module:
  auto pass adds+joins 3 rows, manual Reparse sweeps (−3) and rebuilds (+3),
  uncheck drops the tab (`🚪`), re-check rejoins on the next auto pass with the
  next worker number, badge carries `#n` + the full id.
* `tests/js/page_harness.mjs` drives — the URL table renders every pushed
  snapshot, the checkbox calls `toggle_url`, Reparse calls
  `auto_connect_scan('manual')`.

So the reports describe **failure modes and display rules**, not a broken
happy path. Each one is now impossible by construction:

## Findings

* **F-1 a raise in the pool phase lost the rebuilt rows.** `_pass` ran
  `_sync_rows` (manual sweep **and** rebuild, in memory) → `_join_and_sync` →
  `_enforce_membership` → `_commit`. Any raise in the pool phase skipped
  `_commit`, so the pass never published the rebuilt rows; the in-memory list
  was already swept, and the next unrelated `_save_arena()` (checkbox, Add,
  preset, scan, run control) persisted and pushed the *empty* list — report 1,
  permanently.
* **F-2 one bad pass ended the reconciler loop.** `reconcile_loop` called
  `reconcile_once` bare, so the first escaping exception killed the loop for
  the rest of the session (`schedule_coro` only logs `Async task failed: …`):
  no auto pass rebuilt rows (report 1) and no auto pass rejoined a re-checked
  tab (report 2). I-47 already makes the *supervisor* loop "never ends by
  itself"; the reconciler violated the same rule.
* **F-3 the checkbox gate was asymmetric.** The leave half acted instantly
  (`commit_urls` → `exit_pool_for_unchecked` → `page_pool.leave_pool`); the
  join half only rode the next auto pass — i.e. it inherited F-2 and the
  configured interval (500…60000 ms). Report 2 is exactly that gap.
* **F-4 two display rules for one identity.** I-55 pins the badge to `#n` +
  the **full** tab id, while the pool row rendered `tab_id.slice(0,12)`
  (and the URL row's "linked tab" tooltip 8 chars). A real Chrome target id
  is 32 hex chars, so the pool could never show the same string as the badge —
  report 3. `PagePool.status_snapshot` also reported `PageInfo.tab_id`, which a
  later join path may have overwritten, while the badge reads the pool key.
* **F-5 an empty manual rebuild was silent.** When the fetch answered but no
  tab matched `url_pattern`, the sweep emptied the list and the pass logged
  only the generic summary — RULE 4 ("empty" vs "broken") was not honoured for
  the one pass the user triggered by hand.

## Decisions

* **D-1 (F-1) the pass commits its rows whatever the pool phase does.** New
  `_pool_phase(p, plan)` wraps `_join_and_sync` + `_enforce_membership` in one
  guarded block that logs `⚠ Pool update failed (…) — URL rows kept, next pass
  retries` and records `report.error`; `_pass` then always runs `_commit`. A
  per-socket `_join_each` keeps one bad tab from skipping the other joins
  (`⚠ Pool join failed (…)`), and new `_publish` remembers a failed
  `deps.commit()` (`bridge._reconcile_unsaved`) so the **next** pass publishes
  even when it has nothing of its own to change
  (`⚠ URL save failed (…) — the next pass retries`).
* **D-2 (F-2) the loop never ends by itself (I-47 shape).** `reconcile_loop`
  runs `_auto_pass`, which catches `Exception`, logs one warn line per distinct
  text (`_log_pass_error`, memo `bridge._reconcile_last_error`, cleared by a
  clean pass) and returns to the normal `bus.wait(interval)` sleep — the next
  interval retries and `CancelledError` still ends the task on the stop paths.
* **D-3 (F-3) the join half of the checkbox gate acts on the commit.**
  `commit_urls` (the ONE URL write path, so toggle, undo, preset load and
  redo all pass through it) now calls `enter_pool_for_checked`: for every
  checked row whose tab is not in the pool it schedules
  `page_pool.rejoin_checked_rows` through the one `schedule_coro` seam (one
  `fetch_tabs` for the batch, then the existing `do_connect_page_pool` per
  target — same mechanic as the reconciler: next worker number, badge,
  persisted wall-clock cooldown via `restore_page_state`), logs
  `♻️ Checked URLs not pooled — rejoining N tab(s) now` and wakes the live bus
  with `urls`. The reconciler pass stays the fallback for a tab Chrome had not
  listed yet; a tab already pooled, a row without `tab_id` and an unchecked row
  are all no-ops (no cancellation, RULE 15 untouched). One decision, two
  enforcers stays true.
* **D-4 (F-4) one rule for the id text: the full tab id.** `PagePool`
  reports the pool KEY as `tab_id` in `status_snapshot` (`_snapshot_entry(tid,
  page)` — the same string `assert_badges` badges), and the two JS renderers
  stop slicing: the pool Tab ID cell shows `#n` + the full id (title = the same
  string), the URL row tooltip shows the full linked id. Badge, pool row and
  tooltip now read the identical string for one tab.
* **D-5 (F-5) an empty manual rebuild says why.** `_summary` adds
  `⚠ Reparse: 0 of N open tab(s) match pattern 'X' — check the URL pattern in
  Settings` when a manual pass ends with no rows while tabs were fetched. The
  pattern stays the only eligibility rule (RULE 10); the line exists so
  "cleared and nothing came back" is diagnosable.

## Rejected alternatives (dishonest reductions, RULE 16.6)

* Catch the pool-phase error and return without committing — that is F-1
  verbatim: the rows stay lost.
* Sweep into a temporary list and swap after the joins — the swap still sits
  after the pool phase, so the window stays open, and it adds a second writer
  of `state.urls`.
* Rejoin from the JS checkbox handler — a second writer of pool membership
  (RULE 10) and CDP work in the page.
* Re-check via a second `auto_connect_scan` call — the interval knob would
  decide how fast a checkbox acts, and a manual-source pass would sweep the
  list on a checkbox click.
* Truncate the **badge** id to 12 chars instead — I-55 pins the badge to the
  full id (it is the reference a human reads off Chrome), so the table follows
  the badge, not the other way round.
* A pass watchdog that aborts a hung pass — aborting between the sweep and the
  commit re-creates F-1; CDP calls carry their own timeouts (30 s send, 10 s
  connect) and D-1 makes a late pass harmless.

## Files

| File | Change |
|---|---|
| `app/services/live/reconcile.py` | `_auto_pass`, `_log_pass_error`, `_pool_phase`, `_join_each`, `_publish`, `_empty_manual_note`; `reconcile_loop`, `_join_and_sync`, `_commit`, `_summary`, `_pass` edited |
| `app/ui/panels/page_pool.py` | `_sockets_by_tab`, `_live_sockets`, `_rejoin_one`, `rejoin_checked_rows` |
| `app/ui/panels/url_queue.py` | `_rejoin_targets`, `enter_pool_for_checked`; `commit_urls` calls it |
| `app/browser/page_pool.py` | `_snapshot_entry(tab_id, page)` reports the pool key |
| `app/ui/web/js/panels/page-pool/render.js` | Tab ID cell = full id (title keeps it) |
| `app/ui/web/js/panels/url-list/render.js` | "linked tab" tooltip = full id |
| `tests/test_reconcile_resilience.py` (new, 8) | D-1/D-2/D-5 |
| `tests/test_reparse_pool_gate.py` (17 → 21) | D-3 |
| `tests/test_page_pool.py` (+1) | D-4 identity of the snapshot |
| `tests/js/test_pool_tab_id.mjs` (new, 4) | D-4 render parity |
| `tests/js/test_run_badge.mjs` | the pinned 12-char slice expectation replaced by the full id |

## Tests first (RED at `d8fa79c`)

* `test_a_failed_pool_join_still_commits_the_rebuilt_rows` — a join raise on a
  manual pass: rows rebuilt, `deps.commit` ran, push emitted. *RED: the raise
  escaped `reconcile_once` and nothing was committed.*
* `test_a_joining_tab_does_not_stop_the_other_joins` — one bad socket among
  two: the good one still joins. *RED: same.*
* `test_a_failing_checkbox_enforcement_still_commits`, and
  `test_a_failed_save_is_retried_on_the_next_pass`. *RED: `_publish` missing.*
* `test_the_loop_survives_a_failing_pass` — a config raise on pass 1; the loop
  keeps passing and logs once. *RED: the loop task died.*
* `test_a_pass_error_is_logged_once_per_distinct_text`. *RED: no memo.*
* `test_an_empty_manual_rebuild_names_the_pattern` /
  `test_a_rebuilt_list_has_no_empty_note`. *RED: no such line.*
* `test_checking_a_row_schedules_the_rejoin_now`,
  `test_entering_the_pool_skips_a_pooled_tab_and_an_unlinked_row`,
  `test_the_instant_rejoin_puts_the_tab_back`,
  `test_the_instant_rejoin_says_when_the_tab_is_gone`. *RED: `toggle_url`
  scheduled nothing.*
* `test_snapshot_reports_the_pool_key_as_the_tab_id`. *RED: the snapshot
  reported the stale field.*
* `tests/js/test_pool_tab_id.mjs` (4) + the updated badge test. *RED: the cell
  rendered 12 chars.*
