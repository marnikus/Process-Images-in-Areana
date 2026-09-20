# Quality budget — RULE 16 / RULE 18 numbers for this change

Plan-only companion to [`design.md`](design.md) · evidence in [`evidence.md`](evidence.md).
Every number below is read from the repo, not estimated: `tools/quality_baseline.json`,
`tools/jscpd_baseline.json`, `tools/verify_quality.py`, `tests/test_bridge_slots.py`.

---

## 1. Gate commands (bootstrap first — this checkout has no `.venv`/`node_modules`)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt radon vulture coverage cognitive-complexity
npm ci                                             # jsdom + acorn + jscpd (JS lane)

# per stage (S1…S5)
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -m "not slow and not e2e" -q
.venv/bin/python tools/verify_quality.py --changed --allow-legacy
npm run test:js

# coverage (absolute + per-file ratchet)
QT_QPA_PLATFORM=offscreen .venv/bin/python -m coverage run --branch --source=app -m pytest -m "not slow and not e2e" -q
.venv/bin/python -m coverage json -o coverage.json
.venv/bin/python tools/verify_quality.py --coverage-ratchet

# before push (all lanes, <3 min)
bash tools/pre_push_check.sh
```

---

## 2. Global floors (must not drop)

| Metric | Floor | Source |
|---|---:|---|
| Line coverage | **86.09 %** | `quality_baseline.json → coverage.line` |
| Branch coverage | **82.01 %** | `quality_baseline.json → coverage.branch` |
| Duplication | **1.240 %** (fails on growth) | `tools/jscpd_baseline.json` |
| Slot surface | **134 slots, exact set + exact per-panel packing** | `tests/test_bridge_slots.py:78-236,270` |
| Bridge direct methods | **≤ 10** | `tests/test_bridge_slots.py:276` |
| Vulture | 0 new unused-import findings @ min-confidence 90 | RULE 16.4 |

Duplication direction: this change **merges** two existing clones
(`queue_scan.selected_images:28` ≡ `batch_orchestrator._selected_images:398`) into
`live/feed.eligible_images`, so the expected delta is **negative**.

---

## 3. Per-file ratchet budget (existing files touched)

Growth of any of these maxima fails **even inside a baselined file**
(`tools/verify_quality.py:170-176,296-311`). `file_lines`/`func_count` are recorded but not enforced
for Python — they are tracked here anyway because RULE 18.2 is a stated ideal.

| File | func LOC ≤ | class LOC ≤ | methods ≤ | CC ≤ | nest ≤ | params ≤ | cov ≥ | Biggest edited symbol today | Headroom plan |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| `app/services/captcha/service.py` | 27 | 31 | 4 | 7 | 1 | 4 | **94.69** | `handle_captcha` 20 → 23 | +3 LOC, CC +1 (one guard clause), nesting stays 1 |
| `app/services/single_job_runner.py` | 26 | 18 | – | 9 | 3 | 4 | **83.45** | `check_security` 10 → 12, `_handle_security` 10 → 12, `wait_for_output` 19 → 21 | guard clauses only (nesting ≤ 2 kept) |
| `app/services/batch_orchestrator.py` | 17 | 10 | – | 7 | 2 | 3 | **92.51** | `prepare_batch` 15 → ~13 (takes the plan), `_claim_tab` 8 → 10, `run_batch`/`_abort_no_tab`/`_cancel_batch`/`_crash_batch`/`_selected_images` **deleted** (−33) | file 492 → ~445; every remaining symbol ≤ 17 |
| `app/services/run_state.py` | 18 | 7 | – | 7 | 2 | 3 | **82.09** | `_track_batch_future` **deleted** (−7); `schedule_batch` new ≤ 8 LOC, 2 params, CC ≤ 3 | file 417 → ~420 |
| `app/services/multi_page_dispatcher.py` | 29 | 9 | – | 8 | 2 | 4 | **88.47** | `_finalize_batch` 8 → 6 (no run-state write) | no growth |
| `app/services/auto_connect.py` | 19 | 9 | – | 9 | 4 | 4 | **100.0** | *unchanged* (planner reused as-is) | **do not add code here** — a 100 % floor means every new branch must be tested twice; new policy goes to `live/url_policy.py` |
| `app/services/cooldown_service.py` | 22 | 11 | – | 10 | 3 | 4 | **93.64** | *unchanged* (`tab_has_live_job`, `wait_for_tab_ready` reused) | no edits planned |
| `app/ui/panels/browser_tabs.py` | 20 | 76 | **7** | 7 | 2 | 4 | **89.13** | reconciler functions **move out** (`auto_scan_pass:374`, `plan_auto_sync:366`, `auto_prune_allowed`, `apply_auto_plan`, `prune_auto_rows`, `claim_auto_rows`, `report_auto_plan`, `plan_has_changes`, `join_new_tabs`, `do_auto_connect_scan` = 84 LOC of bodies ≈ −100 with separators); slot `auto_connect_scan` 8 → 8 (calls `live.reconcile_once`) | file 544 → ~440; methods stay 7; coverage may only rise |
| `app/ui/panels/run_control.py` | 19 | 115 | **10** | 6 | 2 | 3 | **82.77** | `start_run` 17 → **18** (`recover_stale_processing` +1, `schedule_batch(run_live)` ±0), `check_start_ready` 9 → **12** (already-live ⇒ wake, not refuse), `reset_image` 9 → 8, `reset_all` 8 → 9, `retry_failed`/`retry_image`/`clear_queue` shrink via `commit_queue` | **no new methods** (ratchet 10); net file 275 → ~270 |
| `app/ui/panels/queue_scan.py` | 19 | 86 | **10** | 7 | 2 | 3 | **52.24** | `run_folder_ai_request` **19 = cap** ⇒ guard swap must stay ≤ 19 (new predicate `feed.any_processing(images)` keeps it 1 line); `set_image_selected` 11 → 9, `bulk_select` 6 → 5, `selected_images` 4 → 2 (delegation) | no new methods |
| `app/ui/panels/url_queue.py` | 14 | 115 | **11** | 6 | 2 | 3 | **96.88** | `_dedupe_state_rows` 10 → 2 and `_add_missing_rows` 9 → 2 become delegations to `live/url_policy.py` (names kept — `app/ui/bridge.py:24-30` re-exports them); `commit_urls` 9 → 9 | no new methods; file 251 → ~240 |
| `app/ui/panels/page_pool.py` | 16 | 139 | **9** | 7 | 1 | 4 | **82.24** | **L-1 fix**: `connect_page_pool` 11 → 11 (`self._schedule_coro(…)` → `schedule_coro(self, …)`, import already in the file's neighbourhood); optional `wake("pool")` on `refresh_expired` (≤ +1 line) | no new methods, no LOC growth |
| `app/ui/panels/watcher_captcha.py` | 17 | 134 | **10** | 7 | 2 | 2 | **59.34** | `start_watcher`/`stop_watcher` +1 line each (`wake("watcher")`) | 11 → 11 LOC, no new methods |
| `app/ui/panels/watcher_solver.py` | 15 | 56 | **6** | 7 | 1 | 3 | **94.29** | unchanged (solver already scoped) | – |
| `app/ui/bridge_context.py` | 19 | 7 | – | 4 | 1 | 3 | **85.61** | `init_run_state` 8 → 10 (`_state_lock`, `_url_memory`); reconciler start hook ≤ +2 | CC ≤ 4 kept |
| `app/ui/bridge.py` | 15 | 95 | **10** | 3 | 1 | 5 | **94.0** | unchanged (no new Bridge methods — D-9) | – |
| `app/browser/cdp_arena/output.py` | 16 | 7 | – | 4 | 1 | 4 | **91.56** | unchanged (`_security_gate` already no-ops without a settler) | – |
| `app/ui/web/js/panels/cdp.js` | 17 / CC 5 / nest 2 / params 2 | – | – | – | – | – | – | **delete** `setInterval(autoConnectScan, 15000)` | `file_lines` 135 → 134, `func_count` 55 → 55 (JS ratchet enforces both — shrink only) |

**Rule for every edit above:** if a symbol would exceed its file cap, the body moves to a function in
`app/services/live/` (a new, unbaselined file) rather than growing the legacy symbol (RULE 16.5).

---

## 4. New files — hard limits only (unbaselined), RULE 18 ideals as the target

New symbols: func ≤ 30 LOC / params ≤ 4 / CC ≤ 10 / nesting ≤ 4 / class ≤ 150 LOC / ≤ 15 methods.
Targets below aim at the **RULE 18 ideal band** (func 4–20, file 150–300, CC ≤ 7).

### 4.1 `app/services/captcha/policy.py` (~35 LOC)

| Symbol | LOC | CC | Params | Killed by |
|---|---:|---:|---:|---|
| `watcher_enabled(bridge)` | 7 | 3 | 1 | `test_captcha_scope.py::scope_follows_switch` (invert ⇒ detection returns with the switch OFF) |
| `solver_running(bridge)` | 7 | 3 | 1 | `test_captcha_scope.py::reason_line_names_solver` |
| `captcha_in_scope(bridge)` | 3 | 1 | 1 | `test_captcha_scope.py::gate_blocks_probe` |

### 4.2 `app/services/live/bus.py` (~90 LOC)

| Symbol | LOC | CC | Params | Killed by |
|---|---:|---:|---:|---|
| `class LiveBus` (5 methods) | ≤ 60 | – | – | `test_live_bus.py` (wake/wait/throttle each asserted) |
| `LiveBus.attach(loop)` | 5 | 1 | 2 | `test_live_bus.py::wake_from_other_thread` |
| `LiveBus.wake(reason)` | 8 | 2 | 2 | same (no loop ⇒ no raise) |
| `LiveBus.wait(timeout)` | 10 | 3 | 2 | `test_live_bus.py::wait_returns_drained_reasons` |
| `LiveBus.throttle(key, sec)` | 6 | 2 | 3 | `test_live_bus.py::throttle_once_per_window` |
| `live_bus(bridge)` | 8 | 2 | 1 | `test_live_bus.py::one_bus_per_bridge` |

### 4.3 `app/services/live/supervisor.py` (~230 LOC)

| Symbol | LOC | CC | Params | Killed by |
|---|---:|---:|---:|---|
| `PassPlan` (dataclass) | 12 | – | – | `test_live_supervisor.py::plan_reads_live_state` |
| `run_live(bridge)` | 20 | 6 | 1 | `test_live_supervisor.py::{never_ends_on_empty, ends_on_cancel, ends_on_stop_after, wakes_on_event}` |
| `plan_pass(bridge)` | 14 | 4 | 1 | `test_live_supervisor.py::plan_reasons` (each of the 4 reasons) |
| `run_pass(bridge, plan)` | 12 | 4 | 2 | `test_live_supervisor.py::dispatches_parallel_when_2_pages` |
| `wait_reason(bridge, plan, bus)` | 12 | 4 | 3 | `test_live_supervisor.py::throttled_wait_line` |
| `set_run_state(bridge, value)` | 8 | 2 | 2 | `test_live_supervisor.py::single_writer_updates_appstate` |
| `is_live(bridge)` | 4 | 3 | 1 | `test_live_supervisor.py::stop_flags_end_loop` |
| `_announce_live` / `pass_tail` / `cancelled_tail` / `_end_run` | 6–10 each | ≤ 3 | 1 | goldens markers + `test_live_supervisor.py::tail_lines` |
| `BLOCKED_LINE` (reason → template table) | data | – | – | RULE 19 step 2: table, not if/elif |

### 4.4 `app/services/live/feed.py` (~150 LOC)

| Symbol | LOC | CC | Params | Killed by |
|---|---:|---:|---:|---|
| `ELIGIBLE` (tuple) | 1 | – | – | `test_live_feed.py::processing_not_eligible` |
| `eligible_images(images)` | 6 | 2 | 1 | `test_live_feed.py::{reset_requeued,pending_picked,completed_skipped}` |
| `any_processing(images)` | 4 | 2 | 1 | `test_live_feed.py::folder_ai_guard` |
| `recover_stale_processing(bridge)` | 12 | 4 | 1 | `test_live_feed.py::stale_processing_returns_to_pending` + `…::live_job_processing_kept` |
| `commit_queue(bridge)` | 9 | 2 | 1 | `test_live_feed.py::commit_wakes_bus` (delete ⇒ no wake) |
| `clear_row_assignments(bridge, ids)` | 10 | 3 | 2 | `test_live_feed.py::removed_row_unassigns_images` |

### 4.5 `app/services/live/reconcile.py` (~190 LOC)

| Symbol | LOC | CC | Params | Killed by |
|---|---:|---:|---:|---|
| `LiveDeps` (dataclass: `fetch_tabs`, `join_tab`, `commit`) | 8 | – | – | `test_live_reconcile.py::deps_injected_no_panel_import` (static guard: no `app.ui` import in `app/services/**`) |
| `Report` (dataclass) | 10 | – | – | `test_live_reconcile.py::report_counts` |
| `reconcile_loop(bridge)` | 14 | 3 | 1 | `test_live_reconcile.py::loop_ticks_and_stops` |
| `reconcile_once(bridge, source)` | 18 | 5 | 2 | `test_live_reconcile.py::{adds_row,removes_row,defers_live_job,empty_fetch_never_removes}` |
| `apply_reconcile(bridge, plan, removals)` | 16 | 5 | 3 | `test_live_reconcile.py::rows_committed_once` |
| `report_reconcile(bridge, report, source)` | 14 | 4 | 3 | `test_live_reconcile.py::manual_always_answers` |
| `start_reconciler(bridge)` | 8 | 2 | 1 | `test_live_reconcile.py::started_once` |

### 4.6 `app/services/live/url_policy.py` (~160 LOC, pure)

| Symbol | LOC | CC | Params | Killed by |
|---|---:|---:|---:|---|
| `RemovalSpec` / `Removal` (dataclasses) | 14 | – | – | `test_url_policy.py` fixtures |
| `advance_misses(rows, live_keys, misses)` | 10 | 3 | 3 | `test_url_policy.py::miss_counter_resets_on_return` |
| `removable_rows(spec)` | 18 | 8 | **1** (spec object — 5 inputs would break the params cap) | `test_url_policy.py::{tab_gone_after_2_misses,pattern_mismatch,invalid_status,duplicate,live_job_deferred,manual_row_kept}` |
| `remember(rows, memory)` | 8 | 3 | 2 | `test_url_policy.py::memory_bounded_200` |
| `restore_enabled(adds, memory)` | 8 | 3 | 2 | `test_url_policy.py::unchecked_tab_returns_unchecked` |
| `removal_lines(removals)` | 6 | 2 | 1 | `test_url_policy.py::reason_in_every_line` |
| `dedupe_rows(rows)` (moved) | 10 | 4 | 1 | existing `tests/test_url_selection.py` cases re-pointed (behaviour identical) |
| `add_rows(rows, adds, memory)` (moved) | 10 | 4 | 3 | `test_url_policy.py::{one_row_per_tab,restores_previous_enabled}` |

### 4.7 `app/services/live/__init__.py` (~30 LOC) — re-export facade only (RULE 16.0 waiver applies)

---

## 5. RULE 18 ideal-size check (the end-of-change recheck the brief asks for)

| Element | Ideal | This plan | Verdict |
|---|---|---|---|
| Function | 4–20 lines (~8–12) | every new symbol ≤ 20, most 6–14; the two 20-line ones (`run_live`, `removable_rows`) carry a named responsibility | ✓ |
| File | 150–300 (~200) | new files 35 / 90 / 150 / 160 / 190 / 230 — `policy.py` 35 and `bus.py` 90 are leaves (RULE 18.2 "under 150 normal and good for leaves") | ✓ |
| Module | 5–15 cohesive files | `app/services/live/` = 6 files that change together (one vocabulary: pass, wake, plan, reconcile); `app/services/captcha/` 6 → 7 | ✓ |
| Context file | 60–200 lines | `docs/current/*` untouched by this plan except row edits; the three plan docs live in `docs/archive/` (not context files) | ✓ |
| Legacy debt direction | – | `browser_tabs.py` 544 → ~440, `batch_orchestrator.py` 492 → ~445, `url_queue.py` 251 → ~240, `run_control.py` 275 → ~270, `queue_scan.py` 315 → ~305 | improves |
| Deviations needing `ideal-size:` comments | – | none planned; if `supervisor.py` passes 300 during implementation, the tails move to `live/tails.py` rather than an override comment | ✓ |

**RULE 19 commitment (order of remediation if a number is over):** nesting → CC → cognitive → size.
Concretely: `removable_rows` uses a reason/predicate table (step 2) instead of 4 nested `if`s;
`run_live` uses guard-`continue` clauses (step 1) instead of nested `if work:` blocks; no symbol is
split just to shrink a number (no `_part1/_part2`, no lambda dispatch — RULE 16.2 anti-gaming).

---

## 6. Test matrix

### 6.1 New test files (every new function gets a test that fails if it is deleted)

| File | Covers | Kind |
|---|---|---|
| `tests/test_captcha_scope.py` | D-1/D-3: switch OFF ⇒ no probe (assert the fake CDP `eval_calls` never contains the detect/visible payloads), no stats, no recording, no penalty, no pool `waiting_captcha`, no `🛡️`/`CAPTCHA_` log line, `SolveOutcome.status == "out_of_scope"`; switch ON ⇒ unchanged; flip mid-run takes effect on the next block | unit + integration |
| `tests/test_live_bus.py` | wake from a foreign thread, drained reasons, throttle window, one bus per bridge | unit |
| `tests/test_live_feed.py` | eligibility (pending/failed/selected/needs_review in; processing/completed/skipped out), `commit_queue` wakes, stale-`processing` recovery, `clear_row_assignments` | unit |
| `tests/test_live_supervisor.py` | never ends on empty queue, ends on cancel, ends after `stop_after`, wakes within one poll on `wake("queue")`, all four blocked reasons + throttle, `set_run_state` writes both `_run_state` and `state.run_state` | integration (fake bridge, no Chrome) |
| `tests/test_live_reconcile.py` | add/claim/remove while a run is live, live-job deferral, empty fetch never removes, manual scan always answers, `wake("urls")` on change | integration |
| `tests/test_url_policy.py` | the 4 removal reasons, hysteresis, memory bound + restore, reason in every log line, manual rows kept | unit (pure) |
| `tests/test_page_pool_join.py` (extends `tests/test_page_pool.py`) | **L-1**: `connect_page_pool` on a bridge *without* `_schedule_coro` schedules the join (regression pin for the `AttributeError`) | unit |
| `tests/js/test_cdp_no_scan_interval.mjs` | static guard: `cdp.js` contains no periodic `autoConnectScan` interval (single writer is Python) | JS lane |

### 6.2 Existing tests that must change (named, with the reason — no silent rewrites)

| Test | Why | Change |
|---|---|---|
| `tests/test_captcha_service.py` (15 `handle_captcha` calls) | bridges have no watcher ⇒ would now return `out_of_scope` | add `arm_watcher(bridge)` from the new `tests/fakes/watcher.py` to the fixtures that assert wait/manual/penalty; add one new test asserting the OFF path |
| `tests/test_captcha_boundaries.py:89-109,217` | `check_security` gated | arm the watcher in the 3 affected tests |
| `tests/test_captcha_job_lines.py`, `test_captcha_milestones.py`, `test_captcha_recording_service.py` | encounters only exist when in scope | arm the watcher fixture |
| `tests/test_single_job_runner.py:396,436,456,464` | monkeypatched `handle_captcha` + `check_security` assert | arm the watcher where the captcha path is the subject |
| `tests/characterization/harness.py:203-208` + `goldens/captcha.json` | an always-live loop never terminates; the captcha golden needs the switch ON | `RUNNERS = {"supervisor": run_live}`; `build_bridge` arms `_stop_after = True` (trace still ends, `run_state` still `idle`) and arms the watcher for the captcha scenario; regenerate with `UPDATE_GOLDENS=1` **after** reviewing the diff |
| `tests/characterization/test_batch_goldens.py:37,47` | markers `"Batch complete"` must survive | keep the string for a finished run (design §6.4) — markers unchanged |
| `tests/test_batch_orchestrator.py:171,321,449-454` | `_abort_no_tab` / `run_batch` move to the supervisor | re-point to `live.supervisor`; keep the `"No usable checked tab left"` assertion against the new waiting line |
| `tests/test_run_state.py:51-60` | pins the `co_name == "run_batch"` tracking heuristic (D-7 deletes it) | assert `schedule_batch` tracks + releases instead |
| `tests/test_multi_page_dispatcher_run.py:234` | `"Parallel batch complete"` string kept; `_finalize_batch` no longer writes run state | assert the log line, drop any run-state assertion |
| `tests/test_panel_browser_tabs.py:425-468` | `auto_prune_allowed` / `do_auto_connect_scan` move to `live/reconcile.py` | move those cases to `tests/test_live_reconcile.py`; keep the slot-level test on `auto_connect_scan` |
| `tests/test_url_selection.py`, `tests/test_url_queue_bugfixes.py` | I-33/I-37 helpers reused, `selected_images` becomes a delegation | expected green; adjust only if an import path moved |
| `tests/test_bridge_slots.py` | contract guard | **must stay green unchanged** (D-9: no new slots, packing identical) |

### 6.3 Characterization equivalence gate

Behaviour-preserving stages (S2, and the S4 move-out) run the whole existing suite **unchanged** as
the equivalence gate (RULE 16.6 step 3). Behaviour-changing stages (S1, S3) update goldens only with
a reviewed `UPDATE_GOLDENS=1` diff attached to the commit message.

---

## 7. Docs to update in the same change (RULE 17)

| Doc | Edit |
|---|---|
| `docs/current/AGENT_RULES.md` | RULE 20 amendment paragraph (Watcher OFF = out of scope; append, never renumber) |
| `docs/current/SYSTEM_OF_RECORD.md` | rows **3** (queue: reset re-queues), **6** (run controls: live run), **11** (CDP/auto-connect: Python reconciler, live pruning, JS interval removed), **12** (captcha scope), **21** (pass semantics + live URL gate); I-19/I-34 amended; **I-39…I-42** added; §7 module table (+`app/services/live/`, +`captcha/policy.py`); §8 test table; §10 pointer to this archive folder; "Last updated" line |
| `docs/README.md` | archive entry for `2026-09-20-live-processing-and-watcher-scope/` (plan → implemented status flip in S5) |
| `docs/current/QUALITY_RECHECK.md` | refreshed gate snapshot after S5 |
| `tools/quality_baseline.json` | re-record **only** in S5, commit message stating why (integrator step); expected: `browser_tabs.py`/`batch_orchestrator.py` maxima down, new files added |

---

## 8. RULE 16.7 acceptance checklist (fill in at the end of S5)

```text
[ ] No new function >30 physical LOC (all new symbols budgeted ≤20 — §4)
[ ] No new class >150 LOC or >15 methods (LiveBus 5 methods, ≤60 LOC)
[ ] No new function with >4 params (removable_rows uses the RemovalSpec object)
[ ] radon CC ≤10, cognitive ≤15, nesting ≤4 on every new/edited function (targets CC ≤8, nest ≤3)
[ ] overall line coverage ≥86.09 % and branch ≥82.01 % (never below baseline)
[ ] per-file coverage floors held (captcha/service 94.69, auto_connect 100.0, url_queue 96.88,
    batch_orchestrator 92.51, browser_tabs 89.13, run_state 82.09, run_control 82.77,
    single_job_runner 83.45, multi_page_dispatcher 88.47, queue_scan 52.24)
[ ] every new function has a test that would fail if deleted (§6.1 "killed by" column)
[ ] no new vulture findings; duplication ≤1.240 % (expected lower after the eligibility merge)
[ ] quality-override comments: none needed — if one appears, it names a real constraint
[ ] no metric gaming (no _part1/_part2, no **kwargs dodge, no lambda dispatch, no deleted decision)
[ ] RULE 18 ideals met or carrying an ideal-size: reason (§5)
[ ] RULE 19 order respected for any remediation (nesting → CC → cognitive → size)
[ ] stop/pause honoured by every new loop (RULE 7): run_live, reconcile_loop
[ ] guards that skip work never stall the stack (RULE 9): check_security, _handle_security,
    removable_rows deferral
[ ] one control per decision (RULE 10): Watcher switch is the only captcha control; the Python
    reconciler is the only periodic scan
[ ] SYSTEM_OF_RECORD.md + docs/README.md + AGENT_RULES RULE 20 updated in the same change (§7)
[ ] bash tools/pre_push_check.sh clean; 12 goldens green; 134-slot contract untouched
```

---

## 9. What this plan refuses to do (anti-gaming, stated up front)

1. **No** `run_live_part1/_part2` split if `run_live` grows — it moves a whole responsibility
   (`tails`) into its own file instead.
2. **No** new `**kwargs` seam to dodge the params cap — `RemovalSpec`/`PassPlan` are named parameter
   objects (RULE 19 step 4).
3. **No** deletion of a real decision to reach a CC number: the four blocked reasons, the four
   removal reasons and the two stop flags all stay visible as data tables.
4. **No** new Bridge methods (the 10-method cap and the frozen 134-slot surface are respected);
   all new surface lives in `app/services/live/` and `app/services/captcha/policy.py`.
5. **No** silent golden regeneration: every golden diff is reviewed and explained in the commit.
6. **No** growth of `app/services/auto_connect.py` (100 % coverage floor) — new policy is new file.
