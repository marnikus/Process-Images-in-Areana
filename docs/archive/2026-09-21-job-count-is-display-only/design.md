# Job count is display-only — no routing by the number (2026-09-21)

Owner instruction (verbatim): *"remove all feature concept about job queueing. leave only job counting as
number for now. remove all other implementation about it. Only counting jobs for now for web page. Pool or
list link are not really rely on num of job anymore. implement this change"*.

## Research — what the number does today (measured, not guessed)

The counter is `PageInfo.jobs_completed`, incremented once per finished job by
`cooldown_service.register_job_done`, persisted per normalized URL in `config/cooldowns.json` (`stats`), restored
on join (`restore_page_stats`) and shown in three views (pool table `Jobs`, URL-list `Jobs` cell, Live Debug
line). Around that counter sits the **load-balancing concept (I-28)**: the counter is not a report, it is a
*decision input* — three routing sites pick the tab with the **fewest completed jobs**:

| Site | Code today | Decides |
|---|---|---|
| `browser/page_pool._pick_lowest_count` | `min(free, key=lambda p: p.jobs_completed)` | which free tab `get_free_page` / `acquire_free_page` hand out (single-mode + `wait_for_free_page`) |
| `services/cooldown_service._best_ready_id` | `min(free, key=lambda p: p.get("jobs_completed", 0) or 0)` | which tab `resolve_primary_tab` / `_resolve_allowed_tab` pick for a run — i.e. the URL-list row's tab |
| `services/multi_page_dispatcher._acquire_free_in` | `min(free, key=lambda p: p.jobs_completed)` | which checked tab takes the next image in parallel dispatch |

Display also *advertises* the concept: `page-pool/render.js` prints
`title="Jobs completed — next job goes to the free tab with the lowest count"`; `register_job_done`'s docstring
says "for load balancing"; `cooldown_store`'s module docstring says "counters (stats) for load balancing".

Tests pin it: `tests/test_page_pool.py::test_get_free_page_prefers_lowest_jobs`,
`::test_acquire_prefers_lowest_and_marks_busy`, `tests/test_cooldown_service.py::test_resolve_best_ready_uses_lowest_jobs_then_order`,
`::test_resolve_allowed_prefers_lowest_jobs_within_allowed`,
`tests/test_multi_page_dispatcher.py::test_acquire_free_in_takes_only_allowed_lowest_jobs`.

## Decisions

**D-1 — Routing is pool order, and only pool order.** The three sites pick the **first** free/ready tab in pool
order (join order = the `#n` worker number, I-55). No comparison of any kind against the counter — not even as
a tie-break, because a tie-break still makes the number decide who works next. Helper names say the rule:
`page_pool._pick_free`, `cooldown_service._first_ready_id`; `_acquire_free_in` takes `free[0]`.

**D-2 — The count stays, as a number.** `PageInfo.jobs_completed`, `register_job_done` (increment +
`last_job_at`), the per-URL persisted `stats` in `cooldown_store`, the join-time restore, and all three
displays stay exactly as they are. Only the sentences that promised routing change ("Jobs completed" is the
whole tooltip) and the two docstrings lose the words "load balancing".

**D-3 — Nothing else reads the number.** No URL-list matching, no receiver flag (`live/url_policy`), no
reconciler, no supervisor, no Job History read touches it — verified by the static guard in the new test file
(the routing helper bodies must not contain `jobs_completed`) and by the behavioural tests.

**D-4 — The pool summary log keeps `·jN`.** `batch_orchestrator.pool_summary` is a *report* of pool state, not
a decision; the number stays visible there.

## Rejected alternatives (dishonest reductions, RULE 16.6)

* **Keep the counter as a tie-break only** ("lowest wins, else pool order") — still a routing rule driven by the
  number, which is the concept the owner asked to remove; and it makes behaviour depend on history that has no
  operational meaning any more.
* **Delete the counter** — the owner explicitly keeps "job counting as number" and the three views show it.
* **A setting to choose order vs balancing** — two behaviours for one decision (the RULE that produced the
  round-4 report); the owner wants one behaviour now.
* **Silently drop the persistence too** ("count in memory") — the number would reset on every restart and the
  Jobs column would lie about the tab's history; the store is the counter's home, not part of the routing.

## Files

| File | Change |
|---|---|
| `app/browser/page_pool.py` | `_pick_lowest_count` → `_pick_free` (first free in pool order); both callers re-pointed; the module no longer mentions `jobs_completed` |
| `app/services/cooldown_service.py` | `_best_ready_id` → `_first_ready_id` (first steady+connected in pool order); 3 call sites; `register_job_done` docstring = counting for display |
| `app/services/multi_page_dispatcher.py` | `_acquire_free_in` takes `free[0]`; docstring says pool order + why |
| `app/persistence/cooldown_store.py` | module docstring: counters feed the Jobs columns (no balancing) |
| `app/ui/web/js/panels/page-pool/render.js` | Jobs cell tooltip = `Jobs completed` (the routing promise removed) |
| tests | new `tests/test_job_count_display_only.py` + `tests/js/test_job_count_display_only.mjs`; 5 existing tests re-pointed (renamed to the pool-order rule, same assertions on the same real objects) |

## Tests first (RED at `764d267`)

* `tests/test_job_count_display_only.py` — a pool whose *later* tab has the lower count returns the **first**
  free tab from `get_free_page` / `acquire_free_page`; `resolve_primary_tab` (free, cooling, unknown-preference
  and `allowed=` forms) picks the first ready in pool order; `_acquire_free_in` takes the first allowed free tab;
  `register_job_done` still counts and the snapshot still carries the number; the routing helpers' source must
  not contain `jobs_completed`.
* `tests/js/test_job_count_display_only.mjs` — the pool row renders the number with a display-only tooltip and
  no "lowest count" promise; the URL-list Jobs cell stays a plain number; no JS module mentions count routing.
* Re-pointed: `test_get_free_page_uses_pool_order_not_job_count`,
  `test_acquire_uses_pool_order_and_marks_busy`,
  `test_resolve_best_ready_uses_pool_order_not_job_count`,
  `test_resolve_allowed_uses_pool_order_within_allowed`,
  `test_acquire_free_in_takes_only_allowed_pool_order`.

## Outcome (landed 2026-09-21, `arena/01a0c40f-…`)

* routing sites: 3 → 0 reading the counter; `jobs_completed` now appears only in counting/restore/display paths
  (`register_job_done`, `restore_page_stats`, `_stats_count`, the snapshot, the three views).
* `tests/test_job_count_display_only.py` **9 passed** (RED: 8 of the 9 failed at `764d267`),
  `tests/js/test_job_count_display_only.mjs` **6 passed** (RED: 4 of 6 failed — the pool tooltip promised routing);
  the 5 re-pointed tests pass with the pool-order expectation on the same fixtures (the *same* counts that used
  to change the winner now change nothing).
* full suite **2,002 passed / 4 skipped** (pytest) and **354 pass / 4 skipped** (JS), coverage **88.32 line /
  84.98 branch**; the 5 re-pointed tests pass with the pool-order expectation on the same fixtures. Full gate table:
  `docs/current/QUALITY_RECHECK.md` addendum 2026-09-21c.
