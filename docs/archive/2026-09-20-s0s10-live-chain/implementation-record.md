# S0–S10 implementation record — live chain (code + tests + gates)

Repository: marnikus/Process-Images-in-Areana
Branch: `arena/01a0bf4d-process-images-in-areana` (from `528af87` = origin/main, squashed tree)
Plan authority: `docs/archive/2026-09-20-dynamic-urls-and-worker-debug/tdd-interfaces.md` (rev 3)
Drift authority: `docs/archive/2026-09-20-dynamic-urls-and-worker-debug/merge-note.md` (read first)
Round-1 plan: `docs/archive/2026-09-20-live-processing-and-watcher-scope/`
Current-doc authority: `docs/current/AGENT_RULES.md` (RULE 16 gates, RULE 18 ideals)

Stage-gated: no GREEN edit from a later stage is permitted before the previous
stage is fully green (tests + fast lane + docs in the same commit).

Adaptations vs the plan text (per the merge note — the plan is a dated record,
this file is the working truth):
- Slot surface is **135**, not 134 (`set_captcha_provider`, B10). §B's "0 new" holds; the number to assert is 135.
- Plan invariants I-39…I-46 land as **I-47…I-54** (mapping in the merge note §1).
- The "one eligibility rule" already exists as `app/core/run_scope.py` (I-44). S4 extends it; no second rule.
- Coverage floors are **86.36 line / 82.33 branch**; jscpd ceiling **1.24 %**.
- Py test files at S0: **125**; JS: **35** on disk, **29** listed (4 harnesses + L-7's 2 unlisted).
- L-1/L-5/L-6/L-7/L-8 all confirmed still open at S0.

Operating rule for every stage (RULE 16.6 + tdd-interfaces §0.1):
1. Freeze the interface boundary and measured budget (tdd-interfaces §1 + §D, re-measured at S0).
2. Write and run the named RED tests before production code exists; quote the RED failure in the commit.
3. Implement the smallest GREEN change through the named owner.
4. Refactor only after GREEN; run equivalence tests where listed.
5. Update current documentation in the same stage commit (RULE 17).
6. Run the stage gate. A failing gate blocks every later stage.
7. No test may double the seam it tests (D-27); every counting test ships a positive control.

Per-stage detail (interfaces, budgets, RED branches, equivalence): tdd-interfaces.md §S1…§S10.
Frozen seams re-run every stage: tdd-interfaces.md §A. Test ledger: §C. Headroom: §D (+ S0 re-measure below).

---

## S0 — Bootstrap and baseline only — DONE (2026-09-20)

Boundary: no production behaviour changes. Only: env bootstrap, runtime-data
untrack (hygiene repair), two test-only reproducibility fixes, this record, doc rows.

Baseline (measured, not assumed):
- Base `528af87` == origin/main; branch `arena/01a0bf4d-process-images-in-areana`.
- Python 3.11.2 (`.venv`), Node v22.22.3, PySide6 6.11.2 present but QtWidgets
  unimportable (no libGL) ⇒ the qt_compat **shim is active** in this env.
- pytest: **1617 passed, 8 skipped** (`QT_QPA_PLATFORM=offscreen`, no cache provider).
- JS: **240 pass, 0 fail** (`npm run test:js`, 29 listed files).
- Coverage (fresh): **87.05 line / 83.25 branch** — floors 86.36/82.33 hold.
- Quality gate full lane: **0 fails, 0 warns** (`verify_quality.py --allow-legacy --coverage-ratchet`).
- Slot surface: **135** (`tests/test_bridge_slots.py` green). Window set: 15 (GRID_VERSION 5).
- jscpd: **1.119 %** (23 groups) — ceiling 1.24 % holds.
- Goldens: 12/12 green inside the pytest run.

S0 repairs (all test/hygiene only; production untouched):
1. Untracked 6 runtime files the squashed commit had re-added
   (`config/app_state.json|captcha_stats.json|cooldowns.json|undo.json`, 2 `.pyc`),
   files kept on disk. Before: `test_no_runtime_data_is_tracked` failed.
2. `tests/test_qt_compat.py`: headless-only skip condition was package-presence
   (`find_spec("PySide6")`); it is now shim-active (`QFileDialog is None`), which is
   the tests' intent. +3 tests run in this env; qt_compat coverage 39.29 → 62.50 (floor 60.71).
3. `tests/test_qt_shim_fallback.py`: new `test_transport_import_without_qt` pins the
   CDP transport Qt fallback by forced ImportError (any env). transport coverage
   84.27 → 91.01 (floor 90.45). Both fixes assert behaviour (§16.3), not lines.
4. Gate env matches the recorded baseline: `cognitive-complexity` is NOT installed
   (baseline stores max_cog 0 for all 147 entries = lib-absent record; installing it
   fails 119 ratchet entries on tool drift, not code growth). Cognitive ≤15 is
   enforced per new/edited symbol by explicit scan at each stage gate (see S10 lane).

S0 re-measure vs tdd-interfaces §D (25 files, gate's own `current_maxima`):
- All enforced maxima match the recorded baseline except `single_job_runner.py`
  max_cc 9 → **7** (shrink, legal — B12). Soft-only moves (unenforced file_lines/
  func_count): run_state 417/33 → 423/34, run_control 275 → 279, queue_scan
  315/25 → 310/24, models 292/14 → 272/11, batch_orchestrator 492/38 → 489/37,
  multi_page_dispatcher 398 → 402. Everything else byte-identical to §D.
- L-1 open (`page_pool.py:147` still `self._schedule_coro`; exactly 1 hit in app/).
- L-6 open (5 `_schedule_coro=` doubles in `tests/test_panel_browser_tabs.py`).
- L-5 open (`index.html` winPagePool orphan, 15-window registries). L-7 open
  (2 unlisted `.mjs`). L-8 open (`WIN_ICONS` dead table).

Gate (all green, commands + output in `s0-baseline.md`):
`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` →
1617 passed, 8 skipped. `npm run test:js` → 240/0.
`.venv/bin/python tools/verify_quality.py --allow-legacy --coverage-ratchet` → 0 fails.
Docs: QUALITY_RECHECK S0 entry + docs/README archive bullet (this folder).

## S1 — L-1 page-pool scheduler defect — NEXT

Boundary: PagePoolMixin delegates its coroutine to the existing service scheduler; it owns no scheduler method.
Interface: `app.services.run_state.schedule_coro(bridge, coro)` remains the only scheduling seam used by the panel.
RED: `tests/test_page_pool_join.py::test_connect_page_pool_uses_service_scheduler`
builds a host with no `_schedule_coro`, spies on the module-level `schedule_coro`,
invokes the real slot, and asserts the coroutine was passed to the service scheduler.
The old code returns {ok:false} and the test fails. Plus the no-private-scheduler
source lock and the two equivalence tests (tdd-interfaces §S1.3).
GREEN: import `schedule_coro` into `app/ui/panels/page_pool.py` and replace
`self._schedule_coro(...)` with `schedule_coro(self, ...)`. Close the captured
coroutine in the test spy.
REFACTOR/EQUIVALENCE: remove the five fake `_schedule_coro` injections from
`tests/test_panel_browser_tabs.py` (L-6 de-mask, spy on the real seam instead).
Do not duplicate scheduling logic in the panel.
Gate: targeted test, panel-slot suite, then the fast lane. Update current defect
history and QUALITY_RECHECK. Slot surface stays 135.

## S2 — Watcher scope is a hard captcha gate — PENDING (needs S1 green)

Boundary: captcha detection is in scope only while the Watcher switch is ON.
Solver status affects wording only, never scope.
Interfaces: `captcha.policy.watcher_enabled/captcha_in_scope/solver_running/`
`has_solver_key/out_of_scope` (+ `wait_reason` in S3). `handle_captcha` becomes a
thin scoped entry (split, not a branch — CC 7 is the file max, D-26).
RED: `tests/test_captcha_scope.py` + `tests/test_watcher_off_zero_activity.py`
count detect probes, marks, stats, recordings, penalties, overlay calls,
security-dialog polls, and shield/captcha log lines. OFF ⇒ zero of each; ON is the
positive control and must produce activity.
GREEN: gate every pipeline site through policy; install no output security settler
when out of scope. Return `SolveOutcome(status="out_of_scope")` without probing.
Keep normal output timeout behaviour alive.
REFACTOR/EQUIVALENCE: retain wait-only pipeline behaviour while in scope; the guard
must not stall downstream work (RULE 9). Arm `watcher_on` in the golden harness so
goldens stay byte-identical.
Gate: captcha service, single-job runner, watcher tests, docs-current consistency.
Docs: amend RULE 20 + I-19/I-34/system-of-record row 12 (Watcher OFF = no pipeline
captcha activity; ON = detect/wait only). Lands plan I-40 as **I-48**.

## S3 — Capped captcha pause clock — PENDING (needs S2 green)

Boundary: only the per-page generation hard timeout pauses while an in-scope captcha
settle runs. The capped pause is per generation wait.
Interfaces: `core.pause_clock.PauseClock` + `paused_elapsed` (D-25: NOT in
output_wait.py — max_class_loc 4); `WaitSpec.pause` carrier; `captcha.policy`
cap trio (`pause_cap_seconds`, `wait_reason`, `WaitDeadline`).
RED: unit tests (zero/negative note, cap saturation, cumulative settles, paused
elapsed, expiry, timeout mapping) + browser-layer test with a real polling loop and
an OFF positive control whose clock stays zero.
GREEN: build PauseClock from `ctrl.pause_cap_s`, time only the settler through
`_settle_timed` (D-26 extraction), pass through PollSpec; subtract paused total only
in the hard timeout check. Cap expiry ⇒ `wait_timeout` ⇒ honest retryable failure.
REFACTOR/EQUIVALENCE: preserve `cooldown_service.wait_captcha_cleared` signature and
its pinned never-gives-up test. Do not widen CDPArenaController/WaitSpec signatures.
Gate: pause-clock, output wait, CDP integration, coverage ratchet for the touched files.
Docs: RULE 20 (bounded wait + capped pause), row 8 (knob doubles as cap), row 12.
Lands plan I-44 as **I-52**.

## S4 — Live queue feed and wake funnel — PENDING (needs S1 green; S2/S3 independent)

Boundary: one eligibility read model (EXTEND `core/run_scope.py` — no second rule)
and one queue mutation funnel feed a live run. Claim-time recheck prevents stale,
deselected, completed, or already-processing images from dispatching.
Interfaces: `live.bus.LiveBus` + `live_bus(bridge)`; run_scope extension
(predicate excluding live-`processing` + `recover_stale_processing` beside it);
`commit_queue(bridge, reason, undo)`; `run_state.schedule_batch` (replaces
coroutine-name sniffing).
RED: `tests/test_live_bus.py` (cross-thread wake, drained reasons, timeout, throttle),
`tests/test_live_feed.py` (eligibility incl. claim-time recheck), `tests/test_reset_requeues.py`
(reset single/all ⇒ pending + selected + wake + count line + undoable).
GREEN: route scan/select/retry/reset mutations through `commit_queue`; both resets
re-queue and log the count; delete `reset_image_state`'s `selected` parameter.
REFACTOR/EQUIVALENCE: keep output files separate from queue data; preserve undo
semantics; never dispatch a processing image twice. Goldens byte-identical.
Gate: queue panel, run-control, characterization tests.
Docs: rows 6/8/11. Lands plan I-41 as **I-49**, I-46 as **I-54**.

## S5 — Always-live supervisor and one run-state writer — PENDING (needs S4 green)

Boundary: a started run waits for work or a usable tab until the user stops it.
No batch tail self-ends the run.
Interfaces: `live.supervisor.set_run_state/run_live/plan_pass/is_live/wait_reason/`
`run_pass`/tails + `PassPlan`. Explicit `schedule_batch` replaces name sniffing.
RED: `tests/test_live_supervisor.py` (empty queue wait, no-tab wait, wake on new work,
stop-after-current, cancel-current, single active batch, state persistence, no
duplicate dispatch). Golden harness swaps only the runner registry, keeps its stop hook.
GREEN: replace `run_batch` entry with `run_live`; delete self-ending state writes;
route lifecycle through `set_run_state` (also fixes L-2: persist `AppState.run_state`).
Decide "Start while live" deliberately against the I-45 `batch_active` refusal.
REFACTOR/EQUIVALENCE: keep stop checks inside each wait; preserve pinned `Batch complete`
marker; do not alter slot names or packing.
Gate: supervisor tests, run-state tests, all characterization goldens, fast lane.
Docs: row 6 (run lifecycle), row 11. Lands plan round-1 I-39 as **I-47**.

## S6 — Python URL reconciler and user cadence control — PENDING (needs S1+S4 green)

Boundary: one Python reconciler owns periodic row/tab reconciliation. The configured
cadence is a floor; LiveBus wake triggers a pass immediately.
Interfaces: `live.url_policy` (removal/dedupe/add/remember/restore/lines) +
`live.reconcile.LiveDeps/reconcile_once/loop/start/last_pass_at` +
`live.debug_view.clamp_interval_ms/interval_ms/cadence`. Config key
`url_reconcile_interval_ms` default 5000, clamp 500…60000.
RED: `test_live_reconcile.py` + `test_url_policy.py` + `test_url_interval_setting.py` +
`tests/js/test_url_interval_control.mjs` (real control through `save_settings`).
GREEN: config default + `apply_url_interval`; URL List input + save button in new
`url-list/interval.js`; delete the old JS 15 s timer; move reconciliation out of
browser_tabs behind injected LiveDeps; boot from main_window (+1 line).
REFACTOR/EQUIVALENCE: services never import panels; `auto_connect.py` untouched
(100 % coverage); no frozen JS file grows (net-zero ledger).
Gate: reconciler tests, JS control test, UI wiring test, fast lane + `npm run test:js`.
Docs: rows 8/11/21. Lands plan round-1 I-42 as **I-50**.

## S7 — Receiver state and reset-visible URL behaviour — PENDING (needs S6 green)

Boundary: Python is the only owner of whether a URL row can receive a job. JS reflects
the published result only.
Interfaces: `UrlRow.receiver` (appended last); `live.url_policy.receiver_reason/`
`mark_receivers`. Serialization and both undo builders preserve receiver.
RED: Python tests (enabled/disconnected/no-tab/live-tab, persistence round trip,
undo/redo retention, checkbox recomputation, reconcile recomputation) + JS test
(real row renderer shows the marker only when receiver is false).
GREEN: recompute receiver in `commit_urls` and `reconcile_once`; publish to JS; add
inline non-receiver indicator + CSS (zero-line-growth edit in `rowHtml`).
REFACTOR/EQUIVALENCE: no run eligibility logic in JS; `auto_connect.py` untouched.
Gate: model/persistence/undo/URL queue tests, JS renderer test, coverage ratchet.
Docs: rows 19/21. Lands plan I-45 as **I-53**.

## S8 — Window catalog and Page Pool rescue — PENDING (needs nothing but a green tree; S9 needs it)

Boundary: grid catalog grows deliberately from 15 to 16 windows with one new
`live_debug` window. Existing Page Pool markup is moved, not recreated (L-5 rescue).
Interfaces: `core.window_catalog` (WINDOWS/WINDOW_IDS/WINDOW_TITLES/
LEGACY_WINDOW_IDS/GRID_VERSION 6); re-export shim in layout_service; 3 net-zero JS
registry appends; `winLiveDebug` element.
RED: `tests/test_window_catalog.py` (Python≡JS ids/order/titles/version, 16 windows,
v5 migration, default-tree validity, no page_pool orphan, every frozen PagePool id
present) + `tests/js/test_live_debug_panel.mjs` part 1 (grid mounts winLiveDebug;
pool panel binds; title-fit).
GREEN: extract catalog; default tree + leaf on the existing line; markup moved
verbatim; orphan deleted; dead `WIN_ICONS` deleted (−9 lines).
REFACTOR/EQUIVALENCE: retain every PagePoolPanel DOM id; no new slot, no new signal.
Gate: catalog/grid migration tests, all JS boot tests, quality ratchet.
Docs: row 19 (16 windows), data_model/storage notes. Lands plan I-43 as **I-51**.

## S9 — Live Worker and Queue Debug content — PENDING (needs S4+S5+S6+S7+S8 green)

Boundary: the new window presents derived information already available through
existing signals. It neither owns scheduling nor reimplements eligibility in JS.
Interfaces: `live.debug_view.live_view/next_queued/receiver_counts`; `prog["live"]`
(same-line swap); 4 new `live-debug/*.js` (facade/store/render/actions).
RED: Python payload tests (queued count, first eligible image, receiver counts, run
state, interval, last-pass age, read-only, no captcha wording while OFF) + JS part 2
(boot, existing-signal updates, worker-job join, cadence age, ticker with no bridge
traffic, read-only cadence, truthful empty state).
GREEN: publish live payload through existing `progress_updated`; consume
`page_pool_updated` + `arena_state_updated`; self-connect via `Boot.onBridgeReady`;
local 1 s render ticker over cached state.
REFACTOR/EQUIVALENCE: no `live_debug_updated` signal, no new slot, no bridge polling,
no second eligibility rule in JS. URL List remains the one writable cadence control.
Gate: Python payload tests, all JS tests, UI wiring test, coverage ratchet.
Docs: row 19 (window content), I-51/I-52/I-53 enforcement pointers.

## S10 — Test-discovery closure and release verification — PENDING (needs S1…S9 green)

Boundary: all planned behaviour is already implemented. This stage repairs test
integrity and proves the final integrated system.
Interfaces: JS test runner enumerates all `.mjs` tests or maintains an explicit
complete manifest checked against the filesystem (L-7). No production interface added.
RED: `tests/js/test_discovery_integrity.mjs` — discover every `tests/js/**/*.mjs`,
compare to the runner's executed manifest, fail on unlisted or stale entries. Must
first demonstrate the two currently omitted files, then make the runner complete.
GREEN: include every JS test (adopt L-7 orphans only if green, else record why),
remove stale exclusions, execute full Python + JS suites, record final quality report.
Do not refresh baselines unless an approved design decision forces a maximum change.
REFACTOR/EQUIVALENCE: full characterization harness; JS line/function ledger stays
net-zero for baselined files; 135 slot surface retained.
Gate: `bash tools/pre_push_check.sh`; full `verify_quality --allow-legacy
--coverage-ratchet`; pytest; `npm run test:js`; radon; explicit cognitive scan of new
symbols (≤15); vulture; jscpd. Record actual output in QUALITY_RECHECK.
Docs: QUALITY_RECHECK refresh, docs/README 15→16 line, archive checklists.

Final acceptance (tdd-interfaces §F + quality-budget §8.1):
- Watcher OFF performs no captcha activity; ON pauses a generation wait up to the cap.
- A live run does not end until Stop / Stop After Current; queue + URL changes observed live.
- URL rows stay Python-owned; receiver state truthful; user-entered unlinked rows persist.
- Live debug shows queue + workers using existing signals only. 135 slots, 16 windows.
- RULE 16 gates + RULE 18 recheck pass with no metric gaming (cognitive via explicit scan).
