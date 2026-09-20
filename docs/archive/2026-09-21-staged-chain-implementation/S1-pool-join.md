# S1 — L-1 pool join (landed 2026-09-21)

**Plan step:** `docs/archive/2026-09-20-dynamic-urls-and-worker-debug/` design.md §9 S1 · closes
`evidence.md` §4 (L-1) of that folder, per its own rule archived docs are not edited to catch up.

## What changed (net production diff: 2 lines in 1 file)

* `app/ui/panels/page_pool.py` — import `schedule_coro` from `app.services.run_state`; the
  `connect_page_pool` slot now calls `schedule_coro(self, do_connect_page_pool(self, ws_url))`.
  No new symbol, no new slot, no compatibility attribute (re-adding `_schedule_coro` would restore L-6).

## De-mask (L-6), same commit

* `tests/test_panel_browser_tabs.py` — the five `_schedule_coro=…` doubles deleted from every host;
  `test_pool_slots_connect_and_cooldowns` now spies on the production seam
  (`pool_panel.schedule_coro`) instead of replacing it (RULE 8, D-27).

## Tests

* new `tests/test_page_pool_join.py` (RED→GREEN): schedules on the real helper, source lock
  (`_schedule_coro` absent from the panel), reply vocabulary equivalence, coroutine joins the pool.

## Gate / docs

* `page_pool.py`: max_func_loc 16 unchanged, func_count unchanged, +1 line (import).
* Equivalence: `tests/test_page_pool.py`, `tests/test_run_state.py`, goldens — green unedited.
* `docs/current/SYSTEM_OF_RECORD.md` row 11 updated in this commit (RULE 17).
