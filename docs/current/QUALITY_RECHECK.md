# Quality re-check — 2026-09-21 (Reparse fresh sweep + checkbox pool gate)

Snapshot of the RULE 16 gates after the round (`docs/archive/2026-09-21-reparse-sweep-and-checkbox-pool/design.md`).

| Gate | Command | Result |
|---|---|---|
| Python tests | `QT_QPA_PLATFORM=offscreen python -m pytest tests -q` | **1,800 passed · 11 skipped · 0 fail** (+2: `tests/test_reparse_pool_gate.py` 17) |
| JS tests | `npm run test:js` | **282 pass · 0 fail** (286 subtests; the live-debug registry test spawns `.venv/bin/python` — absent in a bare sandbox it fails environmentally, also on the base commit; `npm ci` + a `.venv/bin/python` shim clears it) |
| Size/complexity | `radon cc -s` + per-function cognitive | new/edited functions: `pool_exits` CC 7 / cog 1 / 18 LOC, `_sweep_rows` CC 5 / cog 3 / 16 LOC, `_enforce_membership` CC 5 / cog 8 / 14 LOC, `_row_allows_rejoin` CC 2 / 7 LOC, `exit_pool_for_unchecked` CC 5 / cog 5 / 10 LOC, `_pooled_unchecked` CC 6→extracted / 4 LOC — all inside RULE 16 fail lines and RULE 18 ideals; `pool_exits` first landed at CC 11 (over the fail line) and was flattened per RULE 19 before review |
| Coverage | `coverage run --branch --source=app -m pytest` | **88.7 % line / 84.6 % branch** (gates ≥80 / ≥75); `url_policy.py` 100 %, `auto_connect.py` 100 %, `url_queue.py` 99.5 %, `reconcile.py` 96.8 % |
| Changed-file ratchet | `python tools/verify_quality.py --changed --allow-legacy` | no new findings from this round's files; the 134 `max_cog 0→N` ratchet lines are stale-baseline noise (cog recorded as 0 repo-wide) — identical on the untouched HEAD commit; the `url_queue.py` func/class-LOC growth was removed by moving the gate call into `commit_urls` |

## Addendum 2026-09-21 — Reparse keeps its rows / re-check rejoins / one tab id

Bugfix round on top of the snapshot above (`docs/archive/2026-09-21-reparse-rejoin-and-pool-tab-id/design.md`).

| Gate | Command | Result |
|---|---|---|
| Python tests | `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q` | **1,821 passed · 11 skipped · 0 fail** (+13 new: `tests/test_reconcile_resilience.py` 8, `tests/test_reparse_pool_gate.py` 17 → 21, `tests/test_page_pool.py` +1) |
| JS tests | `npm run test:js` | **287 pass · 4 skipped · 0 fail** (291 subtests; +4 `tests/js/test_pool_tab_id.mjs`, the pinned 12-char slice expectation in `test_run_badge.mjs` replaced by the full id) |
| Size/complexity | `radon cc -s` + per-function cognitive | new/edited: `_auto_pass` 3 LOC, `_log_pass_error` CC 2 / 6 LOC, `_pool_phase` CC 2 / 8 LOC, `_join_each` CC 4 / 13 LOC, `_publish` CC 4 / 13 LOC, `_empty_manual_note` CC 3 / 5 LOC, `_summary` CC 5, `_sockets_by_tab` CC 1, `_live_sockets` CC 2, `_rejoin_one` CC 3 / 8 LOC, `rejoin_checked_rows` CC 6 / 10 LOC, `_rejoin_targets` CC 3 / 4 LOC, `enter_pool_for_checked` CC 3 / 13 LOC, `_snapshot_entry` CC 1 — all inside RULE 16 fail lines and RULE 18 ideals; nothing added inside a class body (the `UrlQueueMixin` LOC ratchet stays put) |
| Coverage | `coverage run --branch --source=app -m pytest` then `coverage json` | **88.79 % line / 84.74 % branch** (gates ≥80 / ≥75); changed files: `reconcile.py` 97.7 %, `url_queue.py` 99.6 %, `browser/page_pool.py` 89.1 %, `ui/panels/page_pool.py` 83.9 % (floor 82.24) — all above their per-file floors |
| Changed-file ratchet | `python tools/verify_quality.py --changed-files <the 4 Python files> [--coverage-ratchet --coverage-file coverage.json]` | **✅ PASSED — no fails**, coverage ratchet included; identical result on the untouched base tree (both: 0 fails, 1 warn = missing `coverage.json`), i.e. the round adds no finding |
| JS lane | same tool with the two changed `.js` files | no finding for `page-pool/render.js` / `url-list/render.js`; the one JS fail (`panels/captcha.js max_cc 12 > 10`) is identical on the base tree (pre-existing) |
| Environment facts | — | the `max_cog 0→N` ratchet lines are the stale-baseline noise documented above (cog recorded as 0 repo-wide; identical on the untouched HEAD commit); `bash tools/pre_push_check.sh` additionally reports two `ratchet-coverage` drops (`app/browser/cdp/transport.py` 90.5→84.3 %, `app/ui/qt_compat.py` 60.7→39.3 %) — measured on the **stashed base tree in this sandbox** with identical values, i.e. the venv now has `websockets`/`PySide6-Essentials` where the baseline was recorded without them (the same family as the documented `libGL` floors), not a finding from this round; the bare `from PySide6 import QtWidgets` import still needs `libGL.so.1` |

**Baseline decision: `tools/quality_baseline.json` is NOT re-recorded** — nothing needed to grow
(every new symbol passes the absolute limits with room), so re-recording would only bake the current
coverage drift into the floors. The stale per-symbol entry `reset_stuck_page: 11` under
`app/ui/panels/page_pool.py` is inert (the symbol is deleted; per-symbol maps only gate legacy
downgrades) and is left for the next integrator refresh, exactly like round 3's entry.

Dishonest reductions rejected (RULE 16.6): catching the pool-phase error without committing (the rows stay lost),
sweeping aside and swapping after the joins (same window, second writer), rejoining from the JS checkbox handler
(second writer of pool membership), re-joining via a second `auto_connect_scan` (the interval would rule the
checkbox), truncating the **badge** instead of the table (I-55), and a pass watchdog (aborting between sweep and
commit re-creates the bug).

## Addendum 2026-09-21 — the pool never holds a worker no URL row owns (I-58)

Second bugfix round of the day (`docs/archive/2026-09-21-pool-follows-url-rows/design.md`).

| Gate | Command | Result |
|---|---|---|
| Python tests | `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q` | **1,838 passed · 4 skipped · 0 fail** (+10: `tests/test_pool_follows_rows.py`; the two `pool_exits` unit tests adapted to the new `PoolExit`) |
| JS tests | `npm run test:js` | **287 pass · 4 skipped · 0 fail** (291 subtests, unchanged — no JS touched this round) |
| Size/complexity | `radon cc -s` | `url_policy.pool_exits` CC 7, `_unchecked_exits` CC 6, `_orphan_exits` CC 4, `_exit_text` CC 5, `reconcile._enforce_membership` CC 8, `url_queue.enforce_pool_membership` CC 5 — all ≤10; every edited function ≤20 LOC (`url_policy.py` 293 lines, inside the 150–300 ideal) |
| Coverage | `coverage run --branch --source=app -m pytest` then `coverage json` | **88.79 % line / 84.74 % branch**; `url_policy.py` 98.9 %, `reconcile.py` 97.7 %, `url_queue.py` 99.6 % |
| Changed-file ratchet | `python tools/verify_quality.py --changed-files <url_policy, reconcile, url_queue, the new test> [--coverage-ratchet --coverage-file coverage.json]` | **✅ PASSED — 0 fails, 0 breaches** (coverage ratchet included); the `url_queue.py` per-symbol map is respected (new symbols only, none over the file's 14-LOC maximum) |
| Repo-wide lane | `python tools/verify_quality.py --changed --allow-legacy` | only the documented environment facts remain — the `max_cog 0→N` stale-baseline noise and the two `ratchet-coverage` floors (`transport.py`, `qt_compat.py`), both reproduced unchanged on the stashed base tree in this sandbox; the one JS fail (`panels/captcha.js max_cc 12`) is pre-existing and identical at base |

Reproduction kept for the record: `/tmp/diag/orphan.py` (1 row, 3 pool pages → the pass reported
`2 stale` and removed nothing) and `/tmp/diag/pool_vs_rows.py` (the reported 4-worker/2-row state → after
one pass `total=2`, two `🚪 Worker … left the pool — no URL row owns it` lines). `pick_primary_ws`
picking an ownerless page was verified directly (`/tmp/diag/primary.py`).

Dishonest reductions rejected (RULE 16.6): pruning only in the pass (up to a full interval of fake
workers after a ✕), pruning everything the fetch did not list (a Chrome restart would evict the pool),
auto-creating a row per pooled page (resurrects rows the removal table just deleted), deleting inside
`sync_pool_presence` (it is the pure presence flagger), and hiding the extras by counting only steady
pages in the snapshot (the zombie clients/sockets/reconnects would stay).

## What changed

* `app/services/live/url_policy.py` +24 (`pool_exits`, `_pooled_unchecked` — the ONE checkbox→pool decision),
  `app/services/auto_connect.py` +7 (`_row_allows_rejoin` — no auto-rejoin while unchecked),
  `app/services/live/reconcile.py` +34 net (`LiveDeps.leave_tab` seam, `Report.swept`, `_sweep_rows`, `_enforce_membership`,
  `_remove_rows` accumulates), `app/ui/panels/url_queue.py` +9 (`exit_pool_for_unchecked` riding `commit_urls`),
  `app/ui/panels/browser_tabs.py` (`live_deps` wires `leave_pool`), `app/ui/panels/app_settings.py` (log wording),
  `index.html` (Settings interval group + Reparse tooltips), `url-list/interval.js` (64/80 lines — mirrors both inputs),
  `settings.js` (payload carries the key only when the field parses). Slot surface unchanged.
* Invariant I-56 added; I-50 extended (manual sweep); rows 8 / 11 / 19 / 21 updated; history: `docs/README.md`.

---

# Quality re-check — 2026-10-02 (Captcha Watcher isolation + UI bugfixes)

Snapshot of the RULE 16 gates after the round. Re-run the commands before
every push (RULE 16 §16.6, `current/CODE_VERIFICATION.md`).

| Gate | Command | Result |
|---|---|---|
| Python tests | `python -m pytest -q -n 4` | 1,393 passed · 1 skipped · 3 environmental fails that also fail on `main` in this sandbox (`test_qt_shim_fallback::test_qt_widgets_import_success_arc` needs PySide6, `test_cdp_client_stub::test_connect_failure_emits_error` expects the IPv4-only connect message, `test_verify_quality_tool::…warns_loudly` xdist flake — passes alone) |
| JS tests | `npm run test:js` | 142 pass · 0 fail (was 141; −5 continue-click probe cases, +6 new suites/cases) |
| Size/complexity gate | `python tools/verify_quality.py --js` | **PASSED** — 0 fails. New symbols all inside the hard limits: `CaptchaWatcher` 14 methods / <150 LOC after extracting `_Encounter`; `Boot` as an object literal (the IIFE form tripped `js-max_cc`); `Dialog.promptEdit` instead of a 5th parameter; `render._renderRows(listId, names, handlers)` |
| Slot contract | `tests/test_bridge_slots.py` | 134 frozen slots (127 + 6 Watcher solver + `restore_default_blocks`); packing `queue_scan` 10 + `queue_scan_folder` 2, `blocks_stack` 11, `watcher_solver` 6 |
| Coverage | `coverage run --branch --source=app -m pytest` | **85.64 % line / 81.32 % branch** (floor was 84.47 / 80.27) — new modules: `captcha_watcher/` 93–100 %, `watcher_solver.py` 94 %, `queue_scan_folder.py` 97 %, `action_blocks_defaults.py` 100 %, `url_queue.py` 97 % |
| Changed-file ratchet | `tools/verify_quality.py --changed --base origin/main --allow-legacy --coverage-ratchet` (the pre-push hook lane) | **PASSED** after the integrator re-record (`--record-baseline`, see below) |

## What changed in the numbers

* −5 production modules/files: `captcha/solver.py`, `captcha/api_client.py`,
  `captcha_js/continue_click.js` (+ `build_continue_js`), the auto branches of
  `captcha/service.py`; −2 test modules.
* +5 modules `app/services/captcha_watcher/`, +`app/ui/panels/watcher_solver.py`,
  +`app/ui/panels/queue_scan_folder.py`, +`app/core/action_blocks_defaults.py`,
  +`js/core/boot.js`, +`js/panels/url-list/listeners.js`.
* `requirements.txt`: `2captcha-python>=1.5.0` (optional at runtime — lazy
  import; the app boots without it and the Watcher reports `sdk_available=false`).
* `tools/mutmut_scopes.txt` scope `captcha` now covers `app/services/captcha_watcher`.

## Baseline re-record (integrator step, reviewed)

`tools/quality_baseline.json` was re-recorded with `--record-baseline` in this
round because the per-file ratchet ("no growth, even inside the limits")
would otherwise reject legitimate additions: `BlocksStackMixin` 10 → 11 slots
(`restore_default_blocks`), `UrlQueueMixin` 9 → 11 methods (`_commit_urls`,
`_emit_url_presets`), `WatcherCaptchaMixin` +2 LOC (`solver_follow` calls),
`AppState.from_dict` nesting 1 → 2 (folder normalisation), and the JS
helpers in `dialog.js`, `block-store.js`, `arena-presets/*.js`,
`action-blocks.js`, `arena-app*.js`. Every value is inside the RULE 16 hard
limits (full-mode gate 0 fails); the per-file coverage floors moved to the
fresh run (`captcha/service.py` 91.1 → 89.6 % after deleting the covered
auto-solve branch, `queue_scan.py` 57.0 → 52.2 % after moving its two
best-covered slots to `queue_scan_folder.py` at 97 %), the global floor rose.
Removed files (`captcha/solver.py`, `captcha/api_client.py`) dropped out of
the baseline.

### 2026-10-03 follow-up re-record (B6 — global-name contract)

Re-recorded once more for the B6 fix (`bugfix-verification.md` §B6): 14
panel modules + `sash-grid.js` each grew by exactly the 3-line
`window.X = X` export, `boot.js` gained `panel(name)` (+21 LOC, 1 function),
`arena-app.js` gained `_panel()` + `window.App = App` (+10 LOC, 1 function).
All 20 rejected deltas were `file_lines` / `func_count` NO-GROWTH entries;
no symbol crossed a hard limit (`--js` full lane 0 fails). Fresh coverage
85.65 % line / 81.33 % branch — the floor 85.64 / 81.32 is kept.

### 2026-10-04 follow-up re-record (B8 — downloaded image lost to a transient page-context loss)

Re-recorded for the B8 fix (`bugfix-verification.md` §B8). Reviewed deltas:
`app/browser/cdp/transport.py` `max_class_loc` 116 → 120 (two `last_error`
attributes + the `_decode_reply` call in `evaluate`; the decoding itself
lives in module functions so the class stays at 9 methods),
`app/browser/visual_click.py` `max_nest` 1 → 2 (the recovery loop in
`_probe_json` is a `for` with early returns — inherent to a retry),
new `app/browser/page_recovery.py` (6 functions, max CC 8, max nest 2).
`download.py` kept CC 7 by extracting `_no_result`. Full lane `--js` 0 fails.
Fresh coverage **86.09 % line / 82.01 % branch** (floor raised from
85.65 / 81.33; `visual_click.py` 48.6 % → 78.7 % from the new runner tests).

### 2026-10-05 follow-up (B9 — broken FIND/HIGHLIGHT probe JS + saved-image outcome policy)

No baseline re-record was needed (`bugfix-verification.md` §B9): the
`_loop_blocks` change was split into `_absorb_block_result` /
`_record_failure` / `_soft_failures_forgiven` so `single_job_runner.py`
keeps its file maxima (max CC 9, max func 26 LOC); `dom_highlight_js.py`
changed by one character. Full lane `--js` 0 fails; `--changed
--coverage-ratchet` PASSED. Fresh coverage **86.15 % line / 82.14 % branch**
(floor 86.09 / 82.01 kept). New lanes: `tests/test_js_payload_syntax.py`
(every JS payload compiles — bracket scan always, `node --check` when
available) and `tests/js/test_dom_probes.mjs` (real probes executed);
`npm run test:js` 174 → 205 (the two existing un-wired probe suites are now
wired as well).

### 2026-10-06 follow-up re-record (B10 — Image Queue live status + captcha provider dropdown)

Re-recorded for the B10 fixes (`bugfix-verification.md` §B10). Reviewed
deltas — all feature growth, every symbol far inside the hard limits:
`app/services/captcha/key_store.py` (one key per provider: `CaptchaSettings`
gained `key_for` / `with_provider` / `with_key`, the store gained the legacy
migration → 9 methods, max CC 6, max nest 2, max func 14 LOC, class 92 LOC;
`_clean_keys` / `_merge_keys` / `_write_legacy_mirror` extracted to keep
`load` / `__post_init__` flat), `app/services/captcha_watcher/sdk_solver.py`
(`provider` / `provider_label` properties, `provider` ctor param → 7 methods,
5 params), `app/ui/panels/watcher_solver.py` (+`set_captcha_provider` slot →
7 slots, class 67 LOC; `push_solver_status` extracted), `service.py` /
`watcher.py` +3 LOC each. `persistence.py` kept its maxima (`_is_transient`
extracted; retry budget is a module constant, not a parameter). New modules:
`app/services/captcha_watcher/providers.py`, `app/services/job_events.py`.
The refresh also folded in earlier reductions that had not been re-recorded
(`single_job_runner.py` max nest 3 → 2, `url-list/actions.js` max nest 2 →
1). Full lane `--js` 0 fails / 0 warns; `--changed --coverage-ratchet --js`
PASSED after the re-record. Fresh coverage **86.37 % line / 82.34 % branch**
(floor raised from 86.09 / 82.01 to 86.36 / 82.33). New lanes:
`tests/test_state_push_resilience.py` (10), `tests/test_captcha_providers.py`
(20), `tests/js/test_queue_live_status.mjs` (8) and
`tests/js/test_captcha_provider_panel.mjs` (5) on the shared
`tests/js/page_harness.mjs`; `npm run test:js` 205 → 218; slot surface 134 → 135.

### 2026-10-07 follow-up (B11 — Action Blocks list empty under a `16 BLOCKS` header)

No re-record needed. The render layer of the Action Blocks window was
rewritten against the real `index.html` / `arena.css` DOM contract
(`bugfix-verification.md` §B11) and every touched file stays at or under
its recorded maxima: `block-render.js` 188 lines / 33 funcs / max func 14
LOC / CC 8 (was 195 / 33 / 22 / 9), `block-config.js` 110 / 19 / 13 / CC 5
(was 158 / 21 / 20 / 5; `renderHead` split into `_titleRow` / `_titleText`
to hold CC 5), `block-store.js` 326 / 46 / 23 / CC 8 (`_adoptList` extracted
so the async list loader keeps CC 8; `_tryLoadBuiltinFromBridge` and
`_catalogDefaults` folded), `action-blocks.js` 220 / 116 funcs (eleven dead
passthroughs removed to pay for `_listHandlers` / `highlightBlock` /
`_labelsFor` / `_statusOf`), `block-listeners.js` 61 / 16. Two new modules
carry the moved responsibilities and meet the hard limits on their own:
`block-views.js` (138 lines, 27 funcs, max func 13 LOC, CC 9 — job views,
footer counters, preset chips) and `block-fields.js` (154 / 20 / 20 / CC 6 —
field schema, input builders, form read/apply). Python: `action_blocks.py`
only changed three annotations to `ClassVar[tuple]` (no metric moves).
New lane: `tests/js/test_action_blocks_render.mjs` (10, whole page, the
Python default stack and builtin catalog executed as bridge replies);
`npm run test:js` 218 → 228; `tests/test_action_blocks_defaults.py` +2;
slot surface unchanged (135).

### 2026-10-08 follow-up (B12 — first run waited 120 s under "wait for finish generation" before pasting anything)

No re-record needed. `AWAIT_PROCESSING_IMAGE` left the WAIT_OUTPUT handler
(`bugfix-verification.md` §B12) for two new modules that meet the hard
limits on their own — `app/browser/processing_probe.py` (171 lines, 7
functions, one JS literal, max func 17 LOC, max CC 4, nesting 2 after
`split_selector_list` was split into `_mask_quotes` / `_split_depth0`; the
first cut was CC 11 / nesting 5 and the gate refused it) and
`app/services/await_processing.py` (156 lines, 12 functions, max func 17
LOC, max CC 6, params ≤ 4) — both **100 % line and branch** in the new
lanes. `single_job_runner.py` did not grow: `_handle_wait` lost its
`is_await` ternaries (file max CC 9 → 7), the AWAIT entry of the handler
map points at the new module, 939 lines / 79 functions as recorded. New lanes:
`tests/test_await_processing.py` (14), `tests/js/test_processing_probe.mjs`
(12, the generated probe executed in jsdom with a stubbed layout), one new
runner test; `npm run test:js` 228 → 240; pytest 1,536 → 1,554.
Characterization golden `happy_full` re-recorded deliberately (the block's
row is `running → success` on an idle fake page and the probe adds one
`evaluate`); the other eleven goldens are byte-identical. Slot surface
unchanged (135).

### 2026-10-09 follow-up (B13 — API keys in the public repo; `completed` images sent again)

No re-record needed. A: 1,126 runtime paths left the index (`config/` but
`.gitkeep`, `logs/`, `arena webpages/`, 50 `.pyc`); the guard is a test
(`tests/test_repo_hygiene.py`, 15, real `git ls-files`) plus pre-push step 0.
B: the run-scope predicate moved out of two files into `app/core/run_scope.py`
(44 lines, 3 functions, 100 % line + branch) and is re-checked at claim time
in `_run_sequential` (12 LOC, CC 5) and `_run_with_sem` (6 LOC); Start is
gated by `run_state.batch_active` in `check_start_ready` (12 LOC, CC 5).
C: `scanner.scan_folder` grew one responsibility (outputs per source) and
was split rather than fattened — `_checked_root` / `_output_rank` /
`_outputs_by_source` (max 11 LOC, CC 5), `scan_folder` 14 LOC / CC 6; the
first cut at CC 9 was rejected. The same-day validation pass (every rule
re-read, the diff re-audited) unified the claim-time check with the Start
predicate (`in_run_scope`, RULE 10), collapsed the `_AI` family vocabulary
into `naming.parse_ai_output` (RULE 16.4 — `scanner._AI_FAMILY_RE` and
`folder_ai._STRIP_RE` deleted), made an empty scan log as empty (RULE 4)
and, when `models.py` touched 301 lines, moved progress counting to
`core/progress.py` (49 lines, 4 functions; `models.py` 272). No ratchet
maximum grew in any touched file; `queue_scan.py` lost its
`selected_images` alias (one call re-hosted, RULE 18.1). New
lanes: `tests/test_run_scope.py` (15), `tests/test_run_control_gate.py` (6,
real `start_run` against a live `Future`), `tests/test_scan_resume.py` (13,
real files through scanner → model → merge → scan workers),
`tests/test_progress.py` (3),
`tests/test_queue_thumbnails.py` (8 — the never-blocking thumbnail contract,
real PNGs; added when deleting the covered alias pushed `queue_scan.py`
under its per-file coverage floor: the floor is met with behaviour, not by
keeping dead lines), 5 tests across the orchestrator / dispatcher /
run_state files, +1 naming; pytest 1,554 → 1,621;
`npm run test:js` unchanged (240); coverage 86.55 / 82.63 → **87.03 / 83.25**.
Goldens byte-identical; slot surface unchanged (135).

### 2026-09-20 S0 baseline + S1 (L-1 pool join) — chain `…dynamic-urls-and-worker-debug/tdd-interfaces.md`

**S0 (measured at base `528af87`, branch `arena/01a0bfba-…`, Python 3.11.2,
Node 22.22.3, fresh `.venv` + `npm ci`, no baseline refresh, no override).**
`pytest -q -n 4`: **1,612 passed · 11 skipped · 1 failed** — the failure is
`tests/test_repo_hygiene.py::test_no_runtime_data_is_tracked`: the root
commit tracks `config/{app_state,captcha_stats,cooldowns,undo}.json` and two
`.pyc` (I-43 regression; no key material inside — grepped). `npm run test:js`
**240 pass / 0 fail** (29 of 35 `.mjs` listed; the two unlisted tests
`test_captcha_saved_page.mjs` + `test_title_fit.mjs` pass when run by hand —
L-7 stays open for S10). Coverage **86.89 % line / 83.21 % branch** (floor
86.36 / 82.33). Slot surface 135. `verify_quality.py --changed --allow-legacy
--coverage-ratchet` at base: `main` shares no diff → full-file fallback,
**119 `ratchet-max_cog 0→N` fails** because every `max_cog` in
`tools/quality_baseline.json` is `0` (the baseline was recorded without
`cognitive-complexity` installed); plus 2 per-file coverage floors below
baseline **at the untouched base tree** (`qt_compat.py` 60.7 → 39.3 %:
`PySide6.QtWidgets` needs `libGL.so.1`, absent in this sandbox;
`cdp/transport.py` 90.5 → 84.3 %). Both are environment facts, recorded, not
gamed — no baseline was refreshed. RED proof of L-1 at base:
`tests/test_page_pool_join.py` 3 failed / 1 passed
(`{'ok': False, 'error': "'Host' object has no attribute '_schedule_coro'"}`).

**S1 GREEN.** `app/ui/panels/page_pool.py`: import `schedule_coro` on the
existing `run_state` import line and `self._schedule_coro(...)` →
`schedule_coro(self, ...)` — 2 lines, no new symbol; `current_maxima`
byte-identical to base (func 16 / class 139 / methods 9 / CC 7 / cog 6 /
nest 1 / params 4 / 234 lines / 14 funcs). L-6 de-masked:
`tests/test_panel_browser_tabs.py` lost its five `_schedule_coro=` host
attributes; `test_pool_slots_connect_and_cooldowns` spies on the real
`page_pool.schedule_coro`. Control: with the production edit reverted the
new file + the de-masked test fail 4 / pass 1; with it 74 pass across
`test_page_pool_join`, `test_panel_browser_tabs`, `test_panel_slots`,
`test_page_pool`, `test_run_state`, `test_bridge_slots`,
`test_bridge_metaobject`. Hygiene: the six tracked runtime files were
`git rm --cached` (files stay on disk) → `test_repo_hygiene` 15 pass.
Full lane after S1: pytest serial **1,617 passed · 11 skipped · 0 failed**
(under `-n 4` only the already-documented xdist flake
`test_verify_quality_tool::…warns_loudly` — passes alone); `npm run test:js`
240 / 0; `compileall` + `pyflakes` clean; `vulture @90` clean; radon
`connect_page_pool` A (4). Coverage **86.91 % line / 83.25 % branch**
(page_pool.py 82.24 → 83.18 %). `verify_quality.py --changed --base main
--allow-legacy --coverage-ratchet` on the one changed app file: no size,
CC, nesting or params movement; the only remaining lanes are the three
environment facts above (`max_cog 0→6` = base value, and the two untouched
files' `libGL` coverage floors). Goldens untouched; slots 135.

### 2026-09-20 S2 (captcha scope = the Watcher switch, D-23) — same chain

**RED first.** `tests/test_captcha_scope.py` (11 tests) could not even collect
(`ImportError: cannot import name 'policy'`); `tests/test_watcher_off_zero_activity.py`
(the D-23 counting test through the real `CaptchaService` + real
`wait_captcha_cleared`, with a positive ON control): OFF run failed
`'stopped' == 'out_of_scope'` and the whole-job variant hit `TimeoutError`
(the pipeline waited on the dialog with the Watcher OFF — the defect in one
line); the ON control passed before any production edit, so the counters
are proven to count. Lesson kept in the file: a *pure no-op* `asyncio.sleep`
patch makes the forever-visible-dialog loop spin without yielding and
`asyncio.wait_for` can never cancel it — the fakes yield with
`await real_sleep(0)` and the scope fake's dialog clears after three polls,
so a wrongly-scoped wait fails fast instead of hanging the suite.

**GREEN.** New `app/services/captcha/policy.py` (54 lines, 5 functions, max
7 loc / CC 3, 100 % covered): `watcher_enabled` (the sole reader of the
switch, fail-closed), `captcha_in_scope` (== the switch, never key/loop),
`solver_running`, `has_solver_key` (wording only), `out_of_scope()`. Five
gate edits, no new branch beyond the guard: `service.handle_captcha` →
scope guard + `_handle_captcha_scoped` (the old body, unchanged),
`_watcher_running` delegates to policy (7 → 3 lines);
`single_job_runner.check_security` returns False before any probe,
`_handle_security` emits `Skipped (Watcher off)` and returns,
`wait_for_output` installs `security_settler` only in scope
(`cdp_arena/output._security_gate` untouched — it only reads the attribute).
`SolveOutcome` docstring lists the status vocabulary incl. `out_of_scope`;
`_handle_captcha_outcome` needed no change (it raises only on the named
statuses). Mutation control: with `captcha_in_scope` forced `True` the two
new files fail 9 / pass 5; restored 14 / 14.

**Existing tests that assumed the ON path.** 21 tests in
`test_captcha_service`, `test_captcha_boundaries`,
`test_captcha_recording_service`, `test_single_job_runner` and the
characterization golden `test_captcha_pause_resume` failed after GREEN
because their bridge fakes never set `watcher_enabled` — the switch was not
load-bearing before S2. Each fake now arms `watcher_enabled: True` with a one-line
reason; `harness.build_bridge(..., watcher_on=True)` sets it on the real
`ConfigManager` for the captcha golden only. The chaos test
`test_every_helper_absorbs_failures` keeps every other config read
exploding (`boom`) while the scope read answers — the gate itself is the one
read that must not fail open. **All golden files are byte-identical.**

**Lane after S2.** pytest `-n 4` **1,638 passed · 4 skipped · 0 failed**
(+17 new, 0 removed); `npm run test:js` 240 / 0; `pyflakes` + `vulture @90`
clean. Coverage **87.02 % line / 83.39 % branch** (S1: 86.91 / 83.25;
`service.py` 94.76 → 94.84, `single_job_runner.py` 83.82 → 84.84).
`verify_quality.py --changed-files` on the four touched app files: no
size / CC / nesting / params ratchet moved — `service.py` max_func_loc stays
27 (`_manual_wait`, S3 shrinks it), `single_job_runner.py` max_cc 9 → **7**
(`check_security` A 4, `_handle_security` A 4, `wait_for_output` B 6),
`file_lines` +8 / +7 / +4 within RULE 18 bands (`single_job_runner.py`
946 keeps its ideal-size header). Remaining fails are only the three
environment facts (`max_cog 0→7/8/8` — verified equal to the base tree's
values by measuring the stashed tree; the two `libGL` coverage floors).
Docs in the same commit: RULE 20 amendment (scope paragraph),
SYSTEM_OF_RECORD row 12 + I-19 / I-34 wording + new **I-48** + services
module row, `docs/README.md` footer.

### 2026-09-20 S3 (captcha ⇄ generation timeout — the capped pause, D-14R / I-52) — same chain

**RED first.** `tests/test_pause_clock.py` (8) and
`tests/test_output_wait_timeout_pause.py` (5) could not collect
(`ModuleNotFoundError: app.core.pause_clock`); `tests/test_captcha_wait_reason.py`
(4) failed on the missing `policy.wait_reason` / `pause_cap_seconds`;
`tests/test_captcha_wait_cap.py` (6) failed on the missing `policy.time`
seam and `DID NOT RAISE RuntimeError` for `wait_timeout` — with the wait
unbounded the cap tests are wrapped in `asyncio.wait_for(..., 5)`, so at base
they end in `TimeoutError`, which *is* the defect. One assertion was
corrected in RED (`"cap" in "captcha"` — the uncapped `describe()` check now
asserts `"(cap"`).

**GREEN.** New `app/core/pause_clock.py` (55 lines, one class, 6 methods,
max 9 loc / CC 4, 100 % covered). `policy.py` 54 → 99 lines:
`pause_cap_seconds` (one knob, 10…3600, default 300), `wait_reason` (a
2-row lookup keyed on `has_solver_key`, RULE 19), `WaitDeadline`
(`expired`, `stop_or`). `output_wait.WaitSpec` gains `pause` (class span
**4** = the recorded file maximum, `LoopState` untouched,
`wait_for_new_output_with_spec` byte-identical); `_check_timeout` 11 → 12
loc / CC 4 → 6 (file max 8) and stamps `paused_s` + `pause_note`.
`cdp_arena/output.py`: `_settle_timed` (CC 2) keeps `_security_gate` at
CC **4** / nest 1; `_timeout_text` keeps `_map_wait_result` at 4 params;
`_run_wait` passes `pause=` on the existing `PollSpec` line.
`captcha/service.py`: `_manual_wait` **27 → 22** loc (file `max_func_loc`
drops), `_wait_outcome` (3 branches: manual / wait_timeout / stopped),
`_wait_timeout` + `_stop_pred` deleted (the deadline owns the `None` stop),
`_resolve_captcha` now takes its wording from `policy.wait_reason`.
`single_job_runner.py`: the clock is installed next to the settler **only
in scope** and both leave through `_drop_wait_hooks` in the same `finally`;
`_handle_captcha_outcome`'s growing `if` chain became the
`_CAPTCHA_FAILURES` status → error lookup — CC **6 → 4** (the plan allowed
≤7). Mutation controls: loop ignores the clock → 1 fail; cap not composed
into `stop` → 4 fail; settle not charged → the new
`test_cdp_arena.py::test_settle_inside_the_wait_is_charged_to_the_pause_clock`
fails (the four RED files alone could not see that mutant — it was added
for exactly that reason, through the real `CDPArenaController` and the
real loop, RULE 8).

**Existing tests.** Two D-15 wording assertions in `test_captcha_service.py`
followed the new rule (no key ⇒ “solve it in Chrome”, never “solving”; the
watcher-labels test now stores a key because the wording follows the key,
not the loop). `cooldown_service.py` and its pinned never-gives-up test
(`tests/test_cooldown_service.py:604-618`) are **unedited**;
`test_wait_captcha_cleared_is_called_unchanged` locks the 4-positional-arg
call. Goldens byte-identical (no golden contains `Timeout`; the harness ctrl
stubs `wait_for_new_output`).

**Lane after S3.** pytest serial **1,662 passed · 4 skipped · 0 failed**
(+24 new); `npm run test:js` 240 / 0; `pyflakes` on every touched file
clean (the two unused re-exports at `output_wait.py:13` pre-exist at base);
`vulture @90` clean. Coverage **87.11 % line / 83.51 % branch** (S2: 87.02 /
83.39; `pause_clock.py` + `policy.py` 100 %, `service.py` 94.84 → 95.24,
`single_job_runner.py` 84.84 → 85.71, `output_wait.py` 94.95 → 95.02,
`cdp_arena/output.py` 91.56 → 91.52 — within the per-file lane, no
ratchet raised). `verify_quality.py --changed-files` on the seven touched
app files: **no** size / class / CC / nesting / params maximum moved
(`output_wait.py` 23 / **4** / 8 / 3 / 4; `cdp_arena/output.py` 16 / 7 /
**4** / 1 / 4; `service.py` max_func_loc **22**; `single_job_runner.py`
max_cc 8, 956 lines under its ideal-size header); the only fails are the
same three environment facts (`max_cog 0→N`, equal to the base tree's
values by measurement; the two `libGL` coverage floors). Docs in the same
commit: RULE 20 amendment (bounded wait, capped pause), SYSTEM_OF_RECORD
rows 8 + 12, core/services module rows, new **I-52**, `docs/README.md`
footer. `evidence.md` §2.1 lives in an archived plan folder and is
therefore not edited (archived plan docs are never caught up).

### 2026-09-20 S4 (live queue core + every reset re-queues, D-6R / I-49 / I-54) — same chain

**Plan re-budget applied (merge-note §2).** The plan's `feed.eligible_images`
would have been a third eligibility rule next to `core/run_scope.py` — the
merged tree already deleted both clones. So the live rule is
`run_scope.live_scope` / `LIVE_STATUSES` (= `RUNNABLE_STATUSES` minus
`processing`) **in the same module**, and `feed.eligible_images` /
`feed.ELIGIBLE` are identity re-exports (`is`-asserted by the tests). A
source lock forbids any `("pending", "failed"…)` tuple outside
`run_scope.py`. `queue_scan.selected_images` no longer exists, so the
plan's delegation test was dropped for that lock.

**RED first.** `tests/test_live_bus.py` (6), `tests/test_live_feed.py`
(10), `tests/test_reset_requeues.py` (6, real `Bridge` via the golden
harness) all failed to collect (`ModuleNotFoundError: app.services.live`);
the reset test's defect line at base is `reset_image_state(img, False)`.

**GREEN.** New `app/services/live/` (3 files): `bus.py` 88 lines —
`LiveBus` (6 methods, max 11 loc / CC 4; `wake` is `call_soon_threadsafe`,
`wait` drains the reasons, `throttle` takes an injectable clock) +
`live_bus(bridge)`; `feed.py` 102 lines — `commit_queue(bridge, reason,
undo=True)` (3 params, CC 2: recalc → save → undo-if-user → wake, under the
bridge `RLock`, never across an `await`), `recover_stale_processing`
(reads `pool.status_snapshot()["pages"][*]["current_image"]`, the same
fact `set_tab_image` writes), `clear_row_assignments`, `state_lock`;
`__init__.py` re-export facade. `core/run_scope.py` 51 → 66 lines
(`LIVE_STATUSES`, `live_scope`). Funnel tails: `run_control` (`retry_failed`,
`reset_all` + count line, `retry_image`, `reset_image` — the two id loops
became `find_image` lookups), `queue_scan` (`clear_queue_images`,
`run_scan_merge`, `run_scan_new_batch`, `set_image_selected`,
`bulk_select`), `app_settings` (`import_preset`, `load_arena_preset` —
`undo=False`, the file's 18-line max shrank to 17). `reset_image_state(img)`
— the parameter is gone (signature lock). `run_state`: `_track_batch_future`
(coroutine-name sniffing) deleted, `schedule_batch` added; `start_run` uses
it and calls `recover_stale_processing` first. `bridge_context.init_run_state`
creates `_live_bus`, `_state_lock` and the `_push_queue_undo` seam (the
funnel's undo push reaches `queue_scan.push_queue_undo` without a services →
ui import). Mutation controls: `selected=False` in the reset → 3 fail; funnel
never wakes → 5 fail; live rule keeps `processing` → 1 fail.

**Existing tests that changed (reasons recorded in-file).** Three spies on
`rc.schedule_coro` became `rc.schedule_batch` (`test_run_control_gate`,
`test_panel_slots`); `test_run_state::…tracks_batch` now asserts the
opposite of the deleted sniffing (a coroutine named `run_batch` is **not**
tracked by `schedule_coro`; `schedule_batch` tracks any name);
`test_file_dialogs` preset fake gained `images=[]` (the funnel counts the
queue). No test asserted `selected is False` after a reset.
**Goldens byte-identical** (the harness never resets mid-run; `logs` are
excluded from the compare).

**Lane after S4.** pytest serial **1,683 passed · 4 skipped · 0 failed**
(+22 new); `npm run test:js` 240 / 0; `pyflakes` on every touched file
clean (the `app_settings.py:310` unused `e` pre-exists); `vulture @90`
clean. Coverage **87.33 % line / 83.82 % branch** (S3: 87.11 / 83.51;
`live/bus.py` 96.97, `live/feed.py` 94.81, `run_scope.py` 100,
`run_control.py` 88.36). jscpd `app/` **1.24 % → 1.106 %** (23 groups; the
L-4 clone family is gone). `verify_quality.py --changed-files` on the nine
touched app files: **no** ratchet maximum moved — `run_control.py` /
`queue_scan.py` `max_methods` stay **10**, `app_settings.py` `max_func_loc`
18 → **17**, `run_state.py` 18 / 7 unchanged; the panels shrank
(275 → 273, 315 → 304, 359 → 358). Remaining fails are the same three
environment facts (`max_cog 0→N`, two `libGL` coverage floors). Docs in
the same commit: SYSTEM_OF_RECORD rows 3 + 6, new **I-49** + **I-54**
(numbers per merge-note §1), services / core module rows,
`docs/README.md` footer.

### 2026-09-20 S5 (always-live run — `live/supervisor.run_live`, one run-state writer, D-5 / D-8 / I-47) — same chain

**RED first.** `tests/test_live_supervisor.py` (12 — the plan's 9 plus the
retry-cap rule, a `Start while live` gate test and the `stop after → pass
finishes` case) failed to import (`ModuleNotFoundError:
app.services.live.supervisor`). The loop is driven with a 5 ms bus poll, a
fake throttle clock and a yield-only `asyncio.sleep`; the tests themselves
wait real time through `env.sleep`.

**Design deviations from the plan, recorded.** (1) *Retry cap* — the plan's
`ELIGIBLE` includes `failed`, which under a run that never ends means an
image failing for a real reason would be re-sent forever; `core/run_scope.
in_live_scope(img, max_attempts)` reads the existing knob
`settings.retries.max_attempts` (RULE 10: the knob existed, unused), a
`failed` image rests once its attempts are spent, Retry / Reset return it to
`pending` which always runs. Positive control: `max_attempts=2`, a `failed`
image at 2 attempts is out, at 1 in, a `pending` image at 9 in. (2) *Pass
tail* — `🏁 Batch complete` / `🏁 Batch cancelled by user` stay pinned for
Stop-after / Cancel; a normal pass logs `🏁 Pass complete — run stays live
(N queued)`. (3) *Goldens* — the 12 scenarios run through
`RUNNERS["supervisor"]` and are **byte-identical without `UPDATE_GOLDENS`**;
the harness arms `_stop_after` when the first pass has finished every planned
image or the loop enters a wait state (that is exactly what the old
one-batch run did by itself). (4) *`all cooling`* — a COOLDOWN page with
`cooldown_remaining > 0` or a busy-like page counts; an expired cooldown does
not (`add_page` registers a steady page — the S5 test builds its cooling
page on the live object).

**GREEN.** `app/services/live/supervisor.py` 181 lines, 13 funcs, max 21 loc
(`run_live`, CC 7 ≤ 8, nest 3), `plan_pass` CC 7, params ≤ 3, `PassPlan`
span 8, no bridge reference in the plan. `set_run_state` writes the
attribute **and** `AppState.run_state` (L-2) then emits. `batch_orchestrator.py`
489 → **433** lines / 37 → 32 funcs (`run_batch`, `_run_guarded`,
`_cancel_batch`, `_crash_batch`, `_finish_batch`, `_abort_no_tab` gone;
`run_pass(bridge, plan)` 7 loc; `prepare_batch(bridge, plan)` copies the
plan; `_await_batch_gate` no longer writes state; `pool_summary` public,
reused by the wait lines; **no `_run_state` in the file**).
`multi_page_dispatcher._finalize_batch` log + emits only, `max_func_loc`
stays **29**. `run_control` 273 → 274 lines (+`run_is_live`, 21 funcs; the
five run slots route through `set_run_state`; `check_start_ready` lost its
`already running` branch; class 108 → 106). `queue_scan` guard →
`in_flight` + `PROCESSING_REFUSAL` (same size). `core/run_scope.py` 66 → 81
lines (+`in_live_scope`, `_attempts_left`; max CC 4). `feed.py` 102 → 127
(+`retry_cap`, `queued_images`, `in_flight`; `commit_queue` counts under the
cap). `live/__init__.py` facade re-exports the supervisor. Mutation
controls: no-work ends the run → 1 fail; persisted `run_state` not written →
1 fail; retry cap ignored → 1 fail; Start while live reschedules → 1 fail;
throttle removed → 1 fail.

**Existing tests that changed (reasons in-file).** `test_batch_orchestrator`:
13 lifecycle assertions — `_run_state == "idle"` after a pass body became
`"running"` (a pass never writes state, D-8); `test_finish_batch_lines` /
`test_cancel_and_crash_batch` / `test_run_batch_shell` → one lock that the
tails are gone and the file has no `_run_state`; `prepare_batch` /
`_load_run_settings` / `_run_guarded` tests follow the new plan-taking
signatures; `_pool_summary` → `pool_summary`. `test_multi_page_dispatcher_run`
2 assertions (tail logs + emits only). `test_run_control_gate::
test_running_label_still_wins…` → `test_start_while_live_wakes_the_loop_
instead_of_refusing`. The `app_settings.py` coverage lane (72.43 → 72.0 %,
a −1-line rounding artefact of S4's shorter `import_preset`) is restored by
a real test of `export_preset` / `refresh_users` (`test_panel_slots`),
not by a baseline edit.

**Lane after S5.** pytest serial **1,693 passed · 4 skipped · 0 failed**
(+10 net; then +1 = 1,694 with the `export_preset` test); `npm run test:js`
240 / 0; `pyflakes` clean on every touched file; `vulture @90` clean.
Coverage **87.48 % line / 84.11 % branch** (S4: 87.33 / 83.82; `app_settings.py` back to 74.67;
`supervisor.py` 93.65, `feed.py` 93.18, `run_scope.py` 100,
`batch_orchestrator.py` 92.65, `run_control.py` 89.57). jscpd `app/`
**1.101 %** (23 groups). `verify_quality.py --changed-files` on the eight
touched app files: **no** ratchet maximum moved (`multi_page_dispatcher.py`
29 / 8 / 4 unchanged; `batch_orchestrator.py` 17 / 7 unchanged and 56 lines
shorter); the only fails are the same environment facts (`max_cog 0→N`,
two `libGL` coverage floors). Docs in the same commit: SYSTEM_OF_RECORD row
6, §3 state 22 + flow, module rows, **I-47**; AGENT_RULES RULE 7 / 10 / 13
corollaries; `docs/README.md` footer.

### 2026-09-20 S6 (dynamic URLs — Python-owned reconciler + interval setting, D-4 / D-10 / D-12R / I-50) — same chain

**RED first.** Four new test files failed to import / run before any
production line: `tests/test_url_policy.py` (25 — the plan's 9 branches, two
of them parametrised: the 4-reason table, dedupe shapes, the S7 seam
`owns_run_tab ≡ enabled_tab_ids`), `tests/test_live_reconcile.py` (11 — real
`Bridge` from `tests/characterization/harness.build_bridge`, fakes only behind
the `LiveDeps` seam; includes the source lock `test_the_js_timer_is_gone`),
`tests/test_url_interval_setting.py` (11) and
`tests/js/test_url_interval_control.mjs` (7, incl. the frozen url-list
line-count guard 38 / 73 / 105 / 48 / 166 / 62 / 137).
`ModuleNotFoundError: app.services.live.url_policy` / `…reconcile` /
`…debug_view`; JS 0 / 7.

**GREEN.** `app/services/live/url_policy.py` (171 lines, 16 functions, max
func 11 LOC, CC 4, **100 % covered**): `REMOVAL_RULES` is a tuple of four
`(reason, predicate)` pairs — `duplicate` / `invalid` / `pattern_mismatch` /
`tab_gone` — and `removable_rows` has no `elif` (source-locked); busy tabs
(`cooldown_service.tab_has_live_job`) are deferred, never-linked rows kept,
`advance_misses` gives a closed tab two reconciles, `remember` /
`restore_enabled` bounded at 200; `dedupe_rows` / `add_rows` moved from
`panels/url_queue` (2-line delegations stay for `bridge_mod._dedupe_state_rows`
/ `_add_missing_rows` callers; the private `_tab_already_owned` folded into
`add_rows`). `app/services/live/reconcile.py` (232 lines, 17 functions, max
func 19 LOC, CC 6, params ≤3, 96.5 %): `LiveDeps` (4 callables), `Report`,
`start_reconciler` (idempotent, mirrors `solver_start`), `reconcile_loop`
(reads `interval_ms` **every pass**; `bus.wait` so `interval` / `start` wake
it), `reconcile_once` (owns the `_auto_scan_running` flag; a `_Pass` object
carries the step context instead of 5-arg helpers — the gate's `max_params 4`
caught the first draft). `app/services/live/debug_view.py` (40 lines, 100 %):
`clamp_interval_ms` = the one clamp owner, `interval_ms`, `cadence`.

**UI land (thin).** `browser_tabs.live_deps` / `start_url_reconciler` /
`auto_scan_pass` (2-line delegation); `do_auto_connect_scan`, `plan_auto_sync`,
`auto_prune_allowed` (the idle-only prune), `prune_auto_rows`,
`claim_auto_rows`, `apply_auto_plan`, `plan_has_changes`, `report_auto_plan`,
`join_new_tabs` deleted — **544 → 458 lines, 41 → 36 functions**, `max_cc` 7
untouched. `url_queue.commit_urls_system` (persist + emit, no undo — I-37).
`app_settings.apply_url_interval` (7 LOC, CC 2; `save_settings` 16 → 17 ≤
file max 18). `layout_state.emit_arena_state` + `prog["live"] =
debug_view.cadence(bridge)` (10 → 11). `config_manager.DEFAULT_SESSION` +
`url_reconcile_interval_ms: 5000`. `main_window._build_ui` + 1 call (the
recordings-bridge temp folded so `max_class_loc` 123 stays — the ratchet
caught the +1). No new `@Slot` (D-20: `app_settings` stays at 10, surface
135). JS: `cdp.js` `setInterval(autoConnectScan, 15000)` deleted (135 → 134
lines, 55 → 54 funcs — both down); `arena-app.js` `'UrlInterval'` appended to
the last `_PANEL_INITS` line (175 lines / 28 funcs unchanged); new
`url-list/interval.js` (58 lines, 7 methods, max CC 3) binds its own ids via
`Boot.bindOnce*`, loads from the pushed `progress_updated.live` (no slot
round-trip), respects focus, saves through `Boot.needBridge('save_settings')`;
`index.html` mounts `🔁 every [ ] ms  Save` inside `urlCooldownBar`.

**Existing tests adapted, with reasons.** `test_panel_browser_tabs.py`:
`test_auto_scan_plan_apply_report` + `test_auto_prune_allowed_and_join`
replaced by `test_live_deps_wires_the_ui_seam` (their subjects no longer
exist — the plan/apply/report body is now covered by
`test_live_reconcile.py` against a real bridge); `test_auto_scan_pass_end_to_end`
asserts the new log vocabulary (`🤖 Reconcile:` / `Reconcile skipped`) and that
a failed fetch keeps the row; `test_browser_tab_slot_guards` unchanged (the
slot still answers `pending` while a pass is in flight).
`test_url_selection.py`: `_tab_already_owned` assertions → `_add_missing_rows`
returning 0 for owned tabs (same fact, public helper). `test_bridge_slots.py`
`_do_auto_connect_scan` stays in `NEVER_SLOTS` (a guard against a name, not a
dependency on it). Two coverage-only additions where the ratchet showed the
moved-out lines had been carrying the file: `test_popup_and_primary_guards`
(browser_tabs — popup with no targets / raise failure / broken pool / primary
tick guards) and two lines in `test_url_queue_add_remove_toggle_edit_test`
(`test_url` non-http branch, `get_url_presets` failure).

**Lane after S6.** pytest serial **1,743 passed · 4 skipped · 0 failed**
(+49 net vs S5); `npm run test:js` **247 / 0** (+7); coverage **87.73 % line /
84.33 % branch** (S5: 87.48 / 84.11; `url_queue.py` 100, `browser_tabs.py`
89.83 ≥ its 89.1 floor);
jscpd `app/` **1.088 %** (23 groups, S5 1.101). `verify_quality.py
--allow-legacy --changed-files` on the 13 touched app files: **0 fails** on
the size/complexity/JS lanes; with `--coverage-ratchet` the only fails were
the two sandbox `libGL` floors (`transport.py`, `qt_compat.py`) plus the two
moved-code dips fixed by the coverage tests above — no baseline touched, no
override. Docs in the same commit: SYSTEM_OF_RECORD rows 8 / 11 / 21, module
row, **I-50**, archive pointer; AGENT_RULES RULE 10 corollary;
`docs/README.md` footer.

### 2026-09-20 S7 (receiver flag + the ⊘ icon — one Python owner, D-18 / I-53) — same chain

**RED first.** `tests/test_url_receivers.py` (14 — the plan's 8 plus the
`busy` reason, the reconciler-marks-after-presence case and a legacy-file
load) failed with `AttributeError: 'UrlRow' object has no attribute
'receiver'` / `module … has no attribute 'mark_receivers'`;
`tests/js/test_url_list_receiver_icon.mjs` 0 / 6 (the class never appeared).

**GREEN — no new production file.** `UrlRow.receiver: bool = False`
appended **last** (`models.py` `max_class_loc` 74 unchanged, positional
constructors survive, old `arena.json` loads with `False`).
`url_policy.receiver_reason` (a guard ladder over the four gates — CC 4;
reads `enabled_tab_ids`, source-locked against re-implementing the run
gate), `receiver_title` (the `RECEIVER_TITLES` lookup) and `mark_receivers`
(the one writer, returns the changed count so nothing is spammed) — file
171 → 231 lines, still `max_func_loc` 11 / CC 4 / **100 % covered**.
`urls_to_js` + `"receiver"` (14 → 15 ≤ file max 23); both undo builders +
`receiver=` (11 → 12, 7 → 8 ≤ 17); `debug_view.annotate_receivers` adds the
`receiver_title` tooltip to the pushed rows at emit (`emit_arena_state`
11 → 12 ≤ 19); `commit_urls` / `commit_urls_system` call `mark_receivers`
first, so a checkbox flip is instant; `reconcile._commit` marks after
`sync_pool_presence` and commits when only receivers changed (`_pass` split
into `_sync_rows` + `_pass` to keep the pass ≤ 12 LOC; an empty fetch still
never touches rows). JS: one `${u.receiver === false ? … : ''}` inside the
existing single `rowHtml` template line — `render.js` **74 lines / 12
functions unchanged** (`test_render_js_did_not_grow` counts with
`tools/js_metrics.js` itself, not a regex); `.url-not-receiver` (3 lines) in
the existing `arena.css`. No new slot (135).

**Existing tests adapted.** None — the field is additive. The S7 test
helper `pool_with(connected=False)` flips `is_connected` after `add_page`
(which always connects), the same order `sync_pool_presence` produces at
runtime.

**Lane after S7.** pytest serial **1,757 passed · 4 skipped · 0 failed**
(+14); `npm run test:js` **253 / 0** (+6); coverage **87.77 % line / 84.38 %
branch** (S6: 87.73 / 84.33; `models.py`, `arena_serialize.py`,
`url_policy.py`, `debug_view.py` 100); jscpd `app/` **1.086 %**.
`verify_quality.py --allow-legacy --changed-files` on the nine touched app
files: **0 fails**; `--coverage-ratchet` adds only the two sandbox `libGL`
floors. Docs in the same commit: SYSTEM_OF_RECORD rows 19 / 21, module row,
**I-53**, archive pointer; AGENT_RULES RULE 13 corollary; `docs/README.md`
footer.

### 2026-09-20 S8 (window contract 15 → 16 + the L-5 rescue, D-21 / I-51) — same chain

**RED first.** `tests/test_window_catalog.py` (7) failed with `ImportError:
cannot import name 'window_catalog' from 'app.core'`;
`tests/js/test_live_debug_panel.mjs` 1 / 6 (no `winLiveDebug`, no 16th
registry row, `WIN_ICONS` still present).

**GREEN.** New `app/core/window_catalog.py` (58 lines, 100 % covered):
`WINDOWS` — the one ordered 16-row table — with `WINDOW_IDS` /
`WINDOW_TITLES` **derived** (the two hand-written lists had drifted on
`recordings`' position, L-8), `LEGACY_WINDOW_IDS` (unchanged: no `page_pool`
alias — the panel is rescued, not registered, D-21), `GRID_VERSION = 6`,
`default_grid_tree` (`live_debug` in the last column split, every split sums
to 100). `layout_service.py` **300 → 258 lines**, `max_func_loc` still 21,
re-exports the six names so `layout_state`, `undo_entries`,
`window_preset_service` and six test modules import unchanged; coverage
97.6 → **99.6 %** (three never-exercised migration branches — a non-dict
tree, a max-depth v5 tree that cannot take the 16th leaf, a split with
non-list children — now have tests instead of a baseline edit). Same-line
appends only in the frozen JS: `constants.js` **25 / 22** (row + `VERSION:
6`), `store.js` **122 / 14**, `arena-app.js` **176** (`'LiveDebugPanel'`),
`sash-core/tree.js` 106 (the four preset trees take the 16th leaf, sizes
re-summed); `sash-grid.js` **123 → 114** (dead `WIN_ICONS` deleted).
`index.html`: the Page Pool markup — declared `data-window="page_pool"`, an
id no registry knew, so `SashGrid.render()`'s `replaceChildren` destroyed
it on the first paint (L-5: the worker table was never visible) — now sits
inside the registered `#winLiveDebug` ("Live Worker & Queue Debug") with
its inner ids untouched (`PagePoolPanel.init()` still binds the three
buttons — locked by test). New `js/panels/live-debug.js` (10 lines, the
registered shell; S9 fills it) + `css/live-debug.css`. L-7 closed:
`test_title_fit.mjs` and `test_captcha_saved_page.mjs` are in `test:js`.

**Existing tests adapted.** `tests/test_grid_layout.py` window counts
15 → 16 (4 assertions); `tests/test_panel_slots.py` canonical `v` 5 → 6;
harness `ALL_WINDOW_IDS` + `TITLE_SECONDARIES` gain `live_debug` (the
title-fit suite now runs with 16 windows).

**Lane after S8.** pytest serial **1,765 passed · 4 skipped · 0 failed**
(+8); `npm run test:js` **269 / 0** (+6 new, +10 L-7 previously unlisted);
coverage **87.80 % line / 84.47 % branch** (S7: 87.77 / 84.38); jscpd
`app/` **1.086 %**. `verify_quality.py --allow-legacy --changed-files` on
the eight touched app files: **0 fails**; `--coverage-ratchet` adds only
the two sandbox `libGL` floors. Docs in the same commit: SYSTEM_OF_RECORD
row 19, module row, **I-51**; AGENT_RULES RULE 10 corollary;
`docs/README.md` footer.

### 2026-09-20 S9 (Live Worker & Queue Debug — the window's content, D-20 / D-22) — same chain

**RED first.** `tests/test_live_debug_view.py` (7) failed with
`AttributeError: module … has no attribute 'live_view'`;
`tests/js/test_live_debug_panel.mjs` part 2 (6 appended — allowed for test
files, D-24a) 0 / 6 (the S8 stub had no strips, no listeners).

**GREEN — no new slot, no new signal, no Python file added.**
`live/debug_view.py` 55 → 92 lines, still **100 % covered**: `next_queued`
(pure, over `core/run_scope.live_scope` — the ONE rule), `receiver_counts`
(reads S7's flag; a monkeypatched `mark_receivers` proves it is never
recomputed), `live_view` (`cadence` + `queued` / `next_image` / `receivers`
/ `run_state`, `captcha_cap_sec` only while the Watcher is ON — D-23's
observability half; `max_func_loc` 11, CC 3). `layout_state.emit_arena_state`
is a same-line swap `cadence` → `live_view` (**10 lines, unchanged**;
`arena_state_updated` carries no new key — locked by test). Four new JS
files, complete inside the stage (D-24): `panels/live-debug.js` 52 lines /
13 funcs (self-connects to `progress_updated` + `page_pool_updated` through
`Boot.onBridgeReady`; idempotent `init`; `arena-app/listeners.js` frozen at
193 lines — asserted), `live-debug/store.js` 54 (the two payloads + a 1 s
ticker that never calls the bridge), `live-debug/render.js` 64 (strips; the
worker line is job-centric, no template shared with `page-pool/render.js` —
jscpd fell 1.086 → **1.079 %**), `live-debug/actions.js` 15 (the window's
only bridge traffic: the Refresh button's `get_page_pool_status` read; a
source lock forbids `save_settings` — D-12R). Refactor before the gate:
`store.workerLines` and `render._jobText` first measured **CC 11** (fail
> 10) → split into `_workerLine` / `_captchaText` / `_idleText`; max CC in
the four files is now 7. Markup: three strips inside `#winLiveDebug` above
the rescued pool table (no `<input>` — asserted); `live-debug.css` +22 lines.

**Existing tests adapted.** `tests/test_url_interval_setting.py` pinned the
exact key set of `progress_updated.live`; S9 grows it, so the assertion is
now a superset check (S6's three keys ⊆ the payload, `cadence` ⊆ `live`).
`test_live_debug_panel.mjs` test 4 (S8) loads the three submodules the
facade now needs.

**Lane after S9.** pytest serial **1,772 passed · 4 skipped · 0 failed**
(+7); `npm run test:js` **275 / 0** (+6); coverage **87.82 % line / 84.48 %
branch** (S8: 87.80 / 84.47); jscpd `app/` **1.079 %**; goldens (12) and
`test_bridge_slots` (135, Σ unchanged) green. `verify_quality.py
--allow-legacy --changed-files` on the six touched app files: **0 fails**;
`--coverage-ratchet` adds only the two sandbox `libGL` floors. Docs in the
same commit: SYSTEM_OF_RECORD row 19 (what the window shows), I-52 / I-53
enforcement pointers, module row; `docs/README.md` footer.

### 2026-09-20 S10 (consolidation — the chain verified as a whole) — same chain

**The three RED checks, run against the final tree.**

1. *Docs match the code.* Every enforcement file named by I-47…I-54 exists
   (`find app tests tools` per invariant — 0 missing); every stage commit
   touched `docs/current/` in the same change (`git show --stat` per commit:
   S0+S1 `57cfae1` 2 files, S2 `a632537` 3, S3 `ec4f2f7` 3, S4 `e2ab4c6` 2,
   S5 `e02cc5d` 3, S6 `4169de6` 3, S7 `06798d6` 3, S8 `071295b` 3,
   S9 `a534532` 2 — RULE 17). SYSTEM_OF_RECORD §11 said "15 windows" until
   this stage; now 16 with the `live_debug` row.
2. *No stage grew another stage's JS.* The net-zero guards re-run on the final
   tree: `test_url_interval_control.mjs` + `test_url_list_receiver_icon.mjs`
   **13 / 0** (frozen `url-list/*.js`, `render.js` 74 / 12,
   `arena-app/listeners.js` 193 all unchanged).
3. *L-7 orphans adopted.* `package.json` `test:js` lists **34 of 38** `.mjs`
   files; the 4 unlisted are harnesses (`fake_dom`, `page_harness`,
   `sash_harness`, `user_layout`), both former orphans run green inside the
   lane (S8).

**The full lane (`bash tools/pre_push_check.sh`, the whole gate).** Repo
hygiene ✅ (no `config/` / keys / `.pyc` tracked, I-43) · pytest serial
**1,772 passed · 4 skipped · 0 failed** (S0 base: 1,612) · `npm run test:js`
**275 / 0** (S0: 240) · coverage **87.82 % line / 84.48 % branch** (S0:
86.89 / 83.21; plan floors 86.09 / 82.01) · jscpd `app/` **1.078 %** (S0:
1.240 % floor) · `test_bridge_slots` **Σ 135** — no stage added a slot or a
signal (D-20) · goldens (12) byte-identical throughout.
`verify_quality.py --changed --base origin/main --allow-legacy
--coverage-ratchet` (the hook lane): **0 real fails**; the two reported
`[ratchet-coverage]` lines are `app/browser/cdp/transport.py` 90.5 → 84.3 and
`app/ui/qt_compat.py` 60.7 → 39.3 — both are the sandbox's missing
`libGL.so.1` (the Qt import path cannot execute here; unchanged since S0,
identical on the untouched base). The same lane on the nine new/rewritten
Python modules only: 0 fails. RULE 16.6 step 4 (radon is not installed in the
sandbox; measured with the gate's own `compute_cc_simple`): every new module's
worst function ≤ CC 7 — `pause_clock` 4 · `window_catalog` 1 · `bus` 5 ·
`feed` 6 · `supervisor` 7 · `reconcile` 7 · `url_policy` 6 · `debug_view` 4
· `captcha/policy` 3.

**Baseline decision: `tools/quality_baseline.json` is NOT re-recorded** —
by the owner's S0 instruction (no new baseline, no overrides) and because
nothing needs it: every ratchet was met against the old maxima, the legitimate
*downward* moves the plan expected happened in the tree (`captcha/service.py`
`_manual_wait` 27 → 22, `layout_service.py` 300 → 258, `sash-grid.js`
123 → 114, `batch_orchestrator.py` 489 → 433) and are simply unclaimed
headroom, and the new files carry no baseline entry at all (they are judged
by the absolute limits, all met). An integrator who re-records later gets the
smaller numbers for free; the only lines a re-record would "fix" are the two
`libGL` floors, which must not be lowered — they are a machine fact, not a
code fact.

**The ten stages in one table.**

| Stage | Commit | What landed | py · js · cov line/branch · jscpd |
|---|---|---|---|
| S0+S1 | `57cfae1` | baseline; L-1 pool join through the real seam; L-6 de-masked | 1,612 · 240 · 86.89/83.21 · 1.240 |
| S2 | `a632537` | captcha scope = the Watcher switch (D-23, I-48) | 1,633 · 240 · 87.03/83.42 · 1.240 |
| S3 | `ec4f2f7` | capped captcha pause `PauseClock` (D-14R, I-52) | 1,657 · 240 · 87.19/83.60 · 1.240 |
| S4 | `e2ab4c6` | `live/bus` + `live/feed` `commit_queue`; every reset re-queues (I-49, I-54) | 1,679 · 240 · 87.35/83.89 · 1.106 |
| S5 | `e02cc5d` | always-live run `live/supervisor` (I-47) | 1,694 · 240 · 87.48/84.11 · 1.101 |
| S6 | `4169de6` | Python-owned URL reconciler + interval setting (D-12R, I-50) | 1,743 · 247 · 87.73/84.33 · 1.088 |
| S7 | `06798d6` | receiver flag + ⊘ icon, one owner (D-18, I-53) | 1,757 · 253 · 87.77/84.38 · 1.086 |
| S8 | `071295b` | one window table, 16 windows, L-5/L-7/L-8 (D-21, I-51) | 1,765 · 269 · 87.80/84.47 · 1.086 |
| S9 | `a534532` | Live Worker & Queue Debug content (D-20/D-22) | 1,772 · 275 · 87.82/84.48 · 1.079 |
| S10 | this commit | consolidation — docs verified, no baseline change | 1,772 · 275 · 87.82/84.48 · 1.078 |

**RULE 18 recheck (final tree).** Module counts: `core` **16** (plan: 15 —
the tree already carried `action_blocks_defaults.py` from B11, noted in the
merge-note), `services/live` **6** (plan said 7 counting `__init__`),
`captcha` **6**, `browser` **23** unchanged, `ui/panels` **15** unchanged.
No production function above 30 LOC was added in any stage; the largest new
functions are `default_grid_tree` 21 and `_manual_wait` 22; no new class
above 120 LOC; params ≤ 4 everywhere (S6's `_Pass` context object). Latent
defects: **L-1, L-5, L-6, L-7, L-8 all closed**; L-2 (run-state writer) closed
by S5, L-3/L-4 by S4/S6.

### 2026-09-20 review of the chain (RULE 16 / 18 / 19, real tools)

Full per-file statistics: `current/metrics_report_2026-09-20-s0-s10-chain.md`.
radon / cognitive-complexity / vulture installed in the sandbox for the first
time; the chain's new Python averages radon **A (2.8)**, max CC 10
(`reconcile._remove_rows`, at the line), max cognitive 8, max nesting 3, max
params 4, max function 22 lines, max class 57 lines / 6 methods; jscpd
1.119 → 1.078 % with 0 clones touching new files; vulture 0 new (2 hits at
`bridge.py:24` pre-exist at `528af87`). One §16.3 defect found and fixed:
`supervisor._crash_tail` had zero hits — `test_live_supervisor.py` gained
`test_a_crashing_pass_ends_the_loop_loudly_and_idles` (verified to fail when
the log line is removed); `supervisor.py` is now 100 % line. Lane: pytest
**1,773 / 0**, JS 275 / 0, coverage 87.83 / 84.48. Debt named: this file is
795 lines against RULE 18.4's 200 — recommended S11 housekeeping moves the
per-stage entries to the archive and leaves the ten-stage table here.

### 2026-09-20 run-status badges + worker-id overlay (D-1…D-6, I-55)

Design and the per-symbol recheck: `archive/2026-09-20-run-badges-and-worker-overlay/design.md` §3 / §5.
RED-first: `tests/test_worker_numbering.py` (5 — join order 1, 2, 3; a revive keeps
its number; removal never reuses; `to_dict` / snapshot carry it),
`tests/test_worker_badge.py` (10 — builder markers incl. `pointer-events:none`,
z-index below the watcher, `textContent` only, idempotent replace; the payload
registry `node --check`s both builders; `assert_badges` counts one per connected
page with a client, skips the rest, swallows errors; join asserts; disconnect
captures the client *before* `remove_page`; a reconciler pass re-asserts),
`tests/js/test_run_badge.mjs` (5 — four-state mapping, hidden while running,
every `[data-run-badge]` painted, bind-once, exactly two slots in `index.html`,
`_PANEL_INITS`, CSS modifiers; pool row and live line lead with `#n`).
New: `browser/worker_badge.py` 69, `services/live/worker_badges.py` 65,
`js/core/run-badge.js` 32. Legacy touched and **shrunk**: `PageInfo.to_dict`
22 → 16 (`_cooldown_dict`), `PagePool.add_page` 23 → 19 (`_revive`),
`disconnect_page_pool` 13 → 12 (`leave_pool`); `finish_pool_join` is `async`.
Measured: max CC 6 / cog 5 / params 4 / nest 2; gate fails = only the
`max_cog`-0 baseline artefact (file maxima pre-exist: 2 / 11 / 6) and the two
`libGL` floors. Lane: pytest **1,790 / 0** (4 skipped), JS **280 / 0**,
coverage 87.89 / 84.54, jscpd 1.072 %, Σ slots 135. Baseline not re-recorded.

### 2026-09-21 run-cycle ON/OFF badge + idle-worker instant start (A-1…A-4, B-1…B-4, I-57)

Design, root cause and per-symbol recheck: `archive/2026-09-21-run-cycle-badge-and-instant-dispatch/design.md`.
RED-first: `tests/test_instant_dispatch.py` (6 — the reported bug: an image
queued mid-pass starts on the idle tab while the other tab is held; a freed
tab is taken on the wake with the poll stretched to 5 s; queue order kept;
no double send + `claim_denied`; Cancel / Stop-after stop the feeder; a single
image on a 2-tab pool goes parallel), `tests/test_live_debug_view.py` (+1
`wait_reason`), `tests/js/test_run_badge.mjs` (6, rewritten to ON/OFF + sub-label).
`multi_page_dispatcher.py` 402 → 447 lines but **simpler**: file max LOC 29 → 18
(`run_one_image_on_page` split into claim / `run_claimed_image` /
`_run_and_record`), max cog 8 → 5, nest 2, CC 8 unchanged; `_create_tasks` /
`_run_with_sem` / the semaphore replaced by `_feed_tasks` / `_serve` /
`_take_next` / `_start_on_free_page` (all ≤ 9 lines); `FreeWaitSpec.wake_wait`
+ `_gave_up`. `batch_orchestrator._try_parallel` 16 lines, one condition fewer.
`live/__init__` no longer re-exports `supervisor` (the dispatcher now imports
`live.bus` / `live.feed`; eager re-export would be a cycle). Gate fails = only
the `max_cog`-0 baseline artefact (dispatcher 8 at base → 5 now; orchestrator 8
unchanged) and the two `libGL` floors. Lane: pytest **1,797 / 0** (4 skipped),
JS **281 / 0**, jscpd 1.071 %, goldens byte-identical, Σ slots 135.

## Addendum 2026-09-21 — readable tab ids + a countdown that never hides (I-59)

The user-reported round (`docs/archive/2026-09-21-readable-tab-ids-and-live-countdown/design.md`, D0-1…D0-3 + D-1…D-7),
TDD from a RED suite at `8db8ec6`.

| Gate | Command | Result |
|---|---|---|
| Python tests | `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q -p no:randomly` | **1,936 passed · 4 skipped · 0 fail** (+98 net: `tests/test_tab_alias.py` 47, `test_cooldown_timer_visible.py`, `test_tab_owner.py`, `test_page_pool_alias.py`, `test_restart_identity.py`, `test_pool_join_identity.py`, `test_probe_selectors.py` +2, `test_worker_badge.py` +2, `test_captcha_watcher.py` +2, `test_ui_wiring.py` +1); 15 legacy assertions re-pointed to the new rule (9 parked-debt / wording in `test_cooldown_service.py`, `test_cooldown_branches.py`, `test_captcha_service.py`, 2 join-log lines in `test_page_pool_join.py` / `test_reparse_pool_gate.py`, 2 badge call-count asserts in `test_worker_badge.py`) — none deleted |
| JS tests | `npm run test:js` | **309 pass · 4 skipped · 0 fail** (313 subtests; new `tests/js/test_countdown_visible.mjs` 11, `test_tab_label_views.mjs` 10 incl. the log-line source guard; `test_pool_tab_id.mjs`, `test_run_badge.mjs`, `test_url_interval_control.mjs`, `test_url_list_receiver_icon.mjs` re-pinned to the label / the new module sizes) |
| Size/complexity | `radon cc -s` + per-function cognitive | new/edited: `tab_label_of` 8 LOC, `PageInfo.label` 2, `normalize_owner`/`format_alias`/`email_from_probe`/`next_alias_no` ≤ 15 each, `AliasBook` 8 methods ≤ 8 LOC, `_stack_penalty` 12 / CC 3, `_materialise_debt` 9 / CC 2, `_arm_timer` 8 / CC 3, `resolve_owners` 9 / CC 3, `_read_owner` CC 3, `_assign_alias` CC 3 — all inside the RULE 16 fail lines and the RULE 18 ideals |
| Coverage | `coverage run --branch --source=app -m pytest tests -q` then `coverage json` | **88.09 % line / 84.73 % branch** (gates ≥80 / ≥75; ratchet floor 86.36 / 82.33 — no decrease); new/changed modules: `owner_probe.py` 100 %, `page_status.py` 100 %, `worker_badges.py` 100 %, `probe_selectors.py` 100 %, `tab_alias.py` 93.3 %, `tab_owner.py` 93.5 %, `cooldown_service.py` 93.1 %, `cooldown_store.py` 87.8 % |
| Changed-file ratchet | `python tools/verify_quality.py --changed-files <19 changed app/.py files>` | **✅ PASSED — 0 fails** (1 warn = `coverage.json` was not regenerated at that moment) |
| Whole-repo gate | `python tools/verify_quality.py --coverage-ratchet` | 1 fail, **identical on the untouched base tree**: `app/ui/web/js/panels/captcha.js max_cc 12 > 10` (measured at base with `node tools/js_metrics.js`: `CC>10 1`) — pre-existing, not a finding of this round |
| JS lane | same tool on the 12 changed `.js` files | **✅ 0 fails** — the round added three small modules (`panels/url-list/cells.js` 92 lines, `panels/page-pool/cells.js` 38, `panels/page-pool/ticker.js` 34, `core/tab-label.js` 19) so no frozen file grew: `page-pool/render.js` 119 → 95, `page-pool/actions.js` 134 → 121, `page-pool/store.js` 32 → 31, `url-list/render.js` 74 → 46; the ratchet sees no growth anywhere |

RULE 18 recheck (the user's "recheck at the end if code fit"): the first shape put `tab_label` **inside**
`PagePool` and the gate caught it (`class PagePool LOC 152 > 150`, `methods 16 > 15`) — fixed by making it a
module-level `tab_label_of(pool, tab_id)` over the pool's public read API (`get_page`), not by a waiver; the JS
side landed first with `page-pool/actions.js` at 146/134 and `store.js` at 41/32 and was then split the same way
(the countdown cell, the 1 s ticker and the tab-label formatter are their own small modules, mirroring the
`url-list/cells.js` precedent). No `--record-baseline` was run: nothing needed to grow.

Dishonest reductions rejected (RULE 16.6): showing the countdown only while `status == cooldown` (that is the
bug), letting the debt tick down during a job (the pause would expire unseen), materialising the debt only in a
reconciler pass (up to one interval of a "ready" tab with hidden time on it), storing the number in the pruned
`entries` map, allocating it in a render path, reading the account from the RSC payload, and rewriting every
`tab_id[:12]` log line in the codebase (the views and the tab-lifecycle lines are the reference surface).

## Addendum 2026-09-21 — Stop / Cancel / Clear time are one reset pipeline (I-60)

The user-reported round (`docs/archive/2026-09-21-stop-cancel-reset-pipeline/design.md`, D-1…D-7),
TDD from a RED suite at `71970e1` (the three test files were written first and failed on
`ModuleNotFoundError: app.services.tab_reset` / missing `url-list/reset.js`).

| Gate | Command | Result |
|---|---|---|
| Python tests | `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q -p no:randomly` | **1,966 passed · 4 skipped · 0 fail** (+30 net: `tests/test_tab_reset.py` 21, `tests/test_tab_reset_seam.py` 9); 1 legacy assertion re-pointed, none deleted (`test_panel_browser_tabs.py::test_reset_stuck_page_paths` → `test_clear_time_paths` — its `current_image ⇒ job alive` refusal *was* the reported bug F-1) |
| JS tests | `npm run test:js` | **333 pass · 4 skipped · 0 fail** (337 subtests; new `tests/js/test_reset_actions.mjs` 24 — incl. 4 page-harness tests that drive the real per-row pass; `test_tab_label_views.mjs` re-pointed: the label check follows the log lines to the new owner and the no-hand-slicing rule now covers both files; `package.json` `test:js` gained the new file) |
| Size/complexity | `python tools/verify_quality.py --changed-files …` (its own AST metrics) + `node tools/js_metrics.js app/ui/web/js/panels --json` | new Python symbols: 33 functions in `tab_reset.py`, longest 17 LOC (`clear_time`), ≤4 params, CC ≤10, nesting ≤2; new/edited JS: `reset.js` longest 12 LOC (`_onClear`), max CC 9, depth ≤2, params ≤4 — every limit met with room, and every symbol near the RULE 18 ideal (4–20 LOC) |
| Coverage | `coverage run --branch --source=app -m pytest tests -q` then `coverage json` | **88.14 % line / 84.85 % branch** (base `71970e1` measured the same way: 88.09 / 84.73 — the round moves both **up**; floors 86.36 / 82.33) |
| Changed-file lane | `python tools/verify_quality.py --changed-files app/services/tab_reset.py app/ui/panels/page_pool.py app/ui/panels/run_control.py --allow-legacy` | **no size/complexity/ratchet fail on the round's own files** (exit ≠ 0 only for the 4 inherited coverage lanes below). Those 4 were re-measured at the base commit `71970e1` in a clean worktree with base `coverage.json` and the *same* command on those same 4 paths: **identical fails and numbers** (`cdp/transport.py` 90.5→84.3, `cooldown_store.py` 93.9→87.8, `cooldown_service.py` 93.6→93.1, `qt_compat.py` 60.7→39.3) — pre-existing coverage drift against `tools/quality_baseline.json`, not a finding of this round; round 3 never saw them because the tool reads `coverage.json` only in the changed-file lanes and no report existed then |
| Whole-repo gate | `python tools/verify_quality.py --coverage-ratchet` | 1 fail — `app/ui/web/js/panels/captcha.js max_cc 12 > 10`; that file is **not in this round's diff** (`git diff --name-only`), so its max_cc is byte-identical on the base tree |
| JS lane | same tool on the changed JS paths (`url-list/reset.js`, `url-list/actions.js`, `url-list.js`, `page-pool/actions.js`) | **4 JS files checked, 0 JS fails** — `url-list/actions.js` 166 → 149 lines, `url-list.js` 137 → **136** lines with its function count unchanged at 37, new `url-list/reset.js` 144 lines; the six other url-list modules (incl. `cells.js`) are untouched |
| Goldens | `tests/characterization/test_batch_goldens.py` | byte-identical: the round adds no writer to the run pipeline — the dispatcher, `_finish_cancelled` and the batch loop are untouched; only the UI layer parks tabs (the plan's D-2) |

RULE 18 recheck (the user's "recheck at the end if code fit"): the first shape put the row's cells in
`url-list/cells.js` (91/100 lines — no headroom) plus a `_fillStatusCell` delegate in the frozen facade; the JS
ratchet caught the second one (`func_count grew 37→38`) and the fix was to **not add a function** — the per-row
pass calls `this._reset.fillStatusCell(...)` inline, so the facade came out one line *shorter* than before
(137 → 136). The Python lane caught the first `_clear_under_job` (5 params > 4) → the pool is resolved from the
bridge inside `_drop_timer(bridge, tab_id)`. `tab_reset.py` is 362 lines against the 150–300 ideal with a stated
reason at the top (one cohesive pipeline; a split would duplicate the park, its field reset and its three log
lines) — the same shape as `cooldown_service.py` (866) and `run_state.py` (422). No `--record-baseline` was run:
nothing needed to grow.

Dishonest reductions rejected (RULE 16.6): clearing the stale fields inside `request_tab_abort` (it would kill
the cooperative abort for live jobs), making Stop always `force_reset_page` (yanking a tab from under a running
job — a second writer of page state), parking synchronously inside the Qt slots (the New Chat reset is async and
bounded at 15 s), giving Cancel its own "steady, no cooldown" path (two behaviours for one user action is what
produced the report), writing `UrlRow.status` from Python (it is the CDP validation status the row-removal policy
rules on), and adding a second "stop penalty" setting next to the pause (one meaning, one knob).

## Addendum 2026-09-21b — Job History window merged from `arena/01a0c3a5` (I-61)

The 17th window arrived as a branch (`d6b3d5a` window + `bb0c996` quality pass) whose merge base is this
branch's fork point `d8fa79c`; it was merged (`3aaa740`) and then integrated with the two conventions this
branch owns — the readable tab label (I-59) and the pool worker number (I-55).

| Gate | Command | Result |
|---|---|---|
| Conflict | `git merge FETCH_HEAD` | exactly **one** conflicting file: `package.json` `test:js` (both sides appended a file to the one-line list) → the union, their `test_job_history_panel.mjs` after `test_live_debug_panel.mjs` and this branch's four files kept, then re-validated as JSON (40 files). Every other file auto-merged — the new window touches different lines than the reset pipeline |
| Python tests | `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q -p no:randomly` | **1,992 passed · 4 skipped · 0 fail** (+26 from the merged `tests/test_job_history.py`) |
| JS tests | `npm run test:js` | **347 pass · 4 skipped · 0 fail** (351 subtests; +3 label tests added here) |
| Coverage | fresh `coverage run --branch --source=app` + `coverage json` | **88.31 % line / 84.96 % branch** (before the merge 88.14 / 84.85; floors 86.36 / 82.33) — the two new Python files are **100 %** (`services/job_history.py` 196 statements, `panels/job_history.py` 23) |
| Changed-file lane (merged Python) | `tools/verify_quality.py --changed-files <8 files> --allow-legacy --no-js` | **no fail on the merged files** (incl. `job_history.py`, which carries its `# ideal-size` reason header at 332 lines); the 4 reported fails are the same inherited coverage lanes proven base-identical in the addendum above |
| JS lane | same tool on the 5 `job-history*.js` files | **5 files checked, 0 JS fails** |
| Whole-repo gate | `tools/verify_quality.py --coverage-ratchet` | 169 files, 1 fail — the unchanged pre-existing `app/ui/web/js/panels/captcha.js max_cc 12 > 10` |

**Dependency check (the merge's real work).** The feature brings two cross-feature reads, both now verified and
locked by tests:

* **pool → history:** `job_history.worker_no_of(pool, tab_id)` reads `PageInfo.worker_no` (I-55, the `#n` badge
  number) at record time through the pool API — the `Tab #` cell shows `#n` and falls back to `—` once the tab is
  gone (`tests/test_job_history.py::test_worker_no_variants`).
* **URL list / worker table → history:** the merged `job-history/render.js` printed `tab_id.slice(0, 8)`, which
  violates I-59 ("`{email}_{4 digits}` in the worker table AND the URL list AND all tab-referencing views"). It now
  renders `window.TabLabel.of(e.tab_id)` (one formatter, the pool snapshot's label, the short id as fallback) with
  the full hex in the tooltip, and `tests/js/test_tab_label_views.mjs` gained a **Job History** block (label, pool
  worker number beside it, gone-tab fallback) plus `job-history/render.js` in both rule lists (no hand-sliced tab
  ids; `TabLabel.of(` required). RED verified by reverting the one-line change: 3 subtests fail, then 13/13 pass.

* **Settings mirror → one save:** the merged `job-history/limit.js` bound a *second* listener to `settingsSaveBtn`,
  so one Settings Save fired two `save_settings` slots (two payloads, two undo entries, two log lines) where the
  house pattern (D-1's interval mirror) is one panel-owned save whose payload carries the mirrored key. Fixed by
  dropping the second binding and adding the mirror to `SettingsPanel._buildSettingsPayload()`
  (`job_history_limit` beside `url_reconcile_interval_ms`), **line-neutral inside the JS ratchet** — `settings.js`
  stays at 251 lines with its `max_func_loc` unchanged (the ratchet rejects any growth of a baselined file, and the
  first two attempts grew it 252→254 and 252→257). Locked by a new test: one click → exactly one `save_settings`
  carrying `job_history_limit` (RED: "one save per click, got 2").

Two "Clear" buttons now live side by side in the UI and were checked for ambiguity: the Job History **Clear**
empties the log behind a confirm (`clear_job_history`), while the URL-list **Clear time** (I-60) zeroes one tab's
countdown — different labels, different windows, different slots; no shared wording.

## Addendum 2026-09-21c — the job counter is display-only (I-28 rewritten)

Owner instruction: remove the *job-queueing* concept, keep the counting as a number, and stop the pool / URL-list
link from relying on the number — design `docs/archive/2026-09-21-job-count-is-display-only/design.md`.

| Gate | Command | Result |
|---|---|---|
| Tests first | `pytest tests/test_job_count_display_only.py` + `node --test tests/js/test_job_count_display_only.mjs` at `764d267` | RED: **8 failed** of 9 (every pick returned the lowest-count tab; `_pick_lowest_count` / `_best_ready_id` still existed) and JS **4 failed** of 6 (the pool tooltip promised routing) |
| Python tests | `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q -p no:randomly` | **2,002 passed · 4 skipped · 0 fail** (+10 net: new file 9, one extra dispatcher test), with 5 existing tests re-pointed **and renamed** to the new rule on the same fixtures (none deleted) |
| JS tests | `npm run test:js` | **354 pass · 4 skipped · 0 fail** (358 subtests; the new file registered in `package.json`, 41 files) |
| Coverage | fresh branch run + `coverage json` | **88.32 % line / 84.98 % branch** (before 88.31 / 84.96 → the removal moves both **up**; floors 86.36 / 82.33) |
| Changed-file lane | `tools/verify_quality.py --changed-files <4 py + page-pool/render.js> --allow-legacy` | **no size/complexity fail** — the round only *removes* code (`page_pool.py` −6 lines net, `cooldown_service.py` and `multi_page_dispatcher.py` shrink, no baselined file grows). The 4 reported fails are the inherited coverage lanes already proven base-identical (addendum above) |
| Whole-repo gate | `tools/verify_quality.py --coverage-ratchet` | unchanged single fail, the pre-existing untouched `captcha.js max_cc 12 > 10` |
| Behaviour equivalence where it matters | the 5 re-pointed tests | same fixtures, same real `PagePool`/`PageInfo` objects — only the *expectation* changed from "lowest count wins" to "pool order wins", which is the point of the change |

Rejected dishonest reductions (RULE 16.6): keeping the counter as a tie-break (still routing by the number),
deleting the counter (the owner keeps it), a setting to switch order/balancing (two behaviours for one decision),
and dropping the persistence so the number would reset every restart (the store is the counter's home; the
`Jobs` column would lie about the tab's history).

## Addendum 2026-09-21d — Firefox beside Chrome (I-62)

Owner request: Firefox as a second supported browser, same host/port *setting*, per-browser data dir + launch
command, a panel that covers both, parity with the Chrome CDP operations, both connectable and poolable at once —
design `docs/archive/2026-09-21-firefox-browser-support/design.md`.

| Gate | Command | Result |
|---|---|---|
| Tests first | the 4 new Python files + `tests/js/test_browser_selector.mjs` before implementation | RED: `ImportError: cannot import name 'bidi'` / `'endpoints'` (2 collection errors), 24 profile/bidi/endpoint tests failing, 9 slot-payload tests failing, JS **8 failed of 8** |
| Python tests | `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q -p no:randomly` | **2,036 passed · 4 skipped · 0 fail** (+34 net: profiles 9, bidi 8, endpoints 8, config slots 9) |
| JS tests | `npm run test:js` | **362 pass · 4 skipped · 0 fail** (366 subtests; the new file registered in `package.json`, 42 files) |
| Coverage | fresh `coverage run --branch` + `coverage json` on this branch | **88.30 % line / 84.79 % branch** (floors 86.36 / 82.33); the new files: `browsers.py` 96/93, `bidi.py` 82/62, `endpoints.py` 73/56 — the BiDi client is exercised through a real socket, the uncovered lines are the defensive `except` arms |
| Changed-file lane | `tools/verify_quality.py --changed-files <7 py + 4 js>` | **no size/complexity fail.** Three findings were fixed, not waived: `build_command`/`launch_commands` 6/5 params → one `endpoint` dict (≤4), `bidi.evaluate`/`navigate` 5 params → an `Endpoint` NamedTuple, and `PagePool` 16 methods > 15 → the pool's browser is set through the same `_host`/`_port` assignment the endpoint push already uses (no new method) |
| Whole-repo gate | `tools/verify_quality.py` (fresh coverage.json in place) | **1 fail — the pre-existing untouched `captcha.js max_cc 12 > 10`** (base-identical drift carried since the JS ratchet; `captcha.js` is not part of this round) |
| Real transport, not a stub | `tests/test_bidi.py` | the fake Remote Agent serves `POST /session` **and** the session socket on ONE port (hand-rolled RFC 6455 upgrade + frame loop) and enforces the `session.new`-first rule, so the client is tested against a socket, not a mock |
| Freeze check | `tests/test_browser_config_slots.py::test_browser_support_added_payloads_not_bridge_slots` | the slot table stays exactly 137 — browser support adds payload keys, never slots |

Protocol honesty (RULE 4): Firefox's CDP was deprecated in 129 and removed in 141; the registry therefore treats
BiDi as a first-class protocol, the panel names the missing CDP-only operations per browser, and an ESR 128/140
launch that re-enables CDP is detected by probing — not by assuming.

## Addendum 2026-09-21e — Firefox over the DevTools RDP socket (I-62, round 8)

Owner report: the round-7 Firefox connection "is not working as expecting" — a `--remote-debugging-port` Firefox is a
Remote Agent session, and the Remote Agent sets `navigator.webdriver = true` for the whole browser (Firefox bug
1719505, fixed in 101). Round 8 replaces that channel for Firefox with the legacy DevTools RDP socket
(`--start-debugger-server`), which does not.

What was added (all RED-first, `app/browser/rdp/` + the seams that call it):

| Piece | Where | Numbers |
|---|---|---|
| RDP codec (UTF-16 length prefix, exact reads, leftover re-buffer, `select` deadlines) | `app/browser/rdp/wire.py` | 177 lines, line cov. 93% |
| Socket (greeting, paired replies, event queue, typed `noSuchActor`) | `app/browser/rdp/connection.py` | 148 lines, 87% |
| Packet parsers + the click-only expression (identity = `browsingContextID`) | `app/browser/rdp/actors.py` | 227 lines, 100% |
| Client + facade (`(value, reason)`, one stale-actor retry, long strings) | `app/browser/rdp/client.py` | 244 lines, 91% |
| Prefs / `user.js` writer (opt-in, idempotent, owner's lines kept) | `app/browser/rdp/profile.py` | 104 lines, 96% |
| Handle rules (an `rdp://` tab is not dialable) | `app/browser/protocols.py` | 58 lines, 93% |
| Registry (`debug_flag`/`prefs`/`stealth`, Firefox row, `debug_arg`) | `app/browser/browsers.py` | 94% |
| Detection CDP → RDP → BiDi, `TargetRef` host, `evaluate`/`click` dispatch, `enabled_targets` | `app/browser/endpoints.py` | 75% (was 74.8% before the round) |
| Panel: prefs block, stealth line, Prepare Profile, per-browser debug flag | `index.html`, `browser-connection.js` | JS lane 0 fails |
| Tab panel: RDP listing + diagnose + fix tip for the active browser | `app/ui/panels/browser_tabs.py` | — |
| Payload keys (`prefs`, `prefs_file`, `user_js`, `stealth`) + `prepare_profile` on the existing slot | `app/ui/panels/cdp_tools.py` | slots unchanged (137) |

Evidence: `fakes/rdp_stub_server.py` is a **real** fake DevTools server on one TCP port (greeting, `listTabs`,
`getTarget`/`attach`, `requestTypes`, `evaluateJSAsync` + `evaluationResult`, legacy `evaluateJS`, long-string
`substring`, rotating/expiring actors, byte-counted-prefix mode, silent mode) — so the client is exercised over a real
socket, including three attach/detach cycles against one browser session. Acceptance: `navigator.webdriver` stays
untouched by this channel and **no generated Firefox command contains `--remote-debugging-port`** (test-pinned);
click-only actions; a plain Save never writes a profile, only Prepare Profile does (idempotent, additive).

Gates: pytest **2,108 passed / 11 skipped** (environment-conditional skips only: Qt-metaobject + verify-quality
ancestor lanes), JS **369 tests / 365 pass / 0 fail / 4 skipped**, coverage **88.31 % line / 84.76 % branch**,
`verify_quality.py --changed-files` 0 fails, whole-repo lane only the pre-existing `captcha.js max_cc 12 > 10`, and
`js_metrics` 0 new violations across 95 files. RULE 16 fixes during the round: `tab_of_descriptor` CC 11 → split into
`text_field`/`int_field`; `RdpClient` 16 methods → 15 (`_supports_async` folded into `_eval_once`, where the
`requestTypes` negotiation belongs).

Honest limits, named in the design doc §5: RDP has no input synthesis (a trusted click needs the OS), no screenshot,
no file-chooser, and no CDP-style `Network.*` — the panel lists those under `unavailable` instead of pretending.

## Addendum 2026-09-21f — every browser, one pass + Firefox that actually connects (I-62, round 9)

Owner, pasting the loop: `CDP error: URLError http://localhost:9224/json/list: Not Found` → `❌ Chrome connection
error` → `+0 added, …, 1 stale`, plus "i cn not connect the Firefox brawser". Two defects, one shape: the
execution client never learned *protocols* (it asked every endpoint for Chrome's HTTP tab list) and only one
endpoint was scanned per pass. Design: [`2026-09-21-every-browser-one-pass/design.md`](../archive/2026-09-21-every-browser-one-pass/design.md).

| Piece | Where | Numbers |
|---|---|---|
| Handle grammar (CDP / `rdp://…/ctx-N` / BiDi `#ctx`), attach, list, evaluate, diagnose, per-channel failure classification, named refusals, scan line | `app/browser/attached.py` (new, 447 lines) | 85% line |
| Protocol-routed listing: `enabled_targets` = every enabled browser at `base + offset`, `probe_order` per row, `ScanUnavailable` | `app/browser/endpoints.py` | 97% line / 97% branch |
| The client actually attaches: `RemoteMixin` (RDP attach/detach, `is_connected`, attachment-following `_endpoint_handle`) | `app/browser/cdp/remote.py` (new) | 79% line |
| Channel declarations on the client / DOM refusals by name | `app/browser/cdp/client.py`, `cdp/dom.py` | 88% / 92% |
| Registry lookups the routing needs (`browser_for_port`, `profile_for_protocol`) | `app/browser/browsers.py`, `protocols.py` (D-8: the rdp-handle refusal deleted) | 92% / 88% |
| One listing seam + honest connect reasons + browser-named pool rows + per-browser diagnose | `app/ui/panels/browser_tabs.py` | 84% line / 86% branch |
| Pool join on any channel (`connect_pool_client`, `pool_page_info`, `own_tab_info`) | `app/ui/panels/page_pool.py` | 86% |
| Settings payload `scan_targets` + `scan_line`, protocol pushed on Save | `app/ui/panels/cdp_tools.py` | 69% line (unchanged surface) |
| Per-tab identity for any channel | `app/services/run_state.py` | 83% |
| Scan line, tab tags, receive breakdown | `browser-connection.js` (292), `cdp/cdp-render.js` (121), `cdp/cdp-listeners.js` (130) | JS lane 0 fails |

Evidence: `tests/fakes/rdp_stub_server.py` counts every byte it receives, so "no HTTP on a DevTools socket" is a
hard assertion (`GET ` and `/json` never appear), and `enabled_targets` is driven against a **real** CDP stub
(`FakeChrome`) and a **real** fake Firefox at the same time in one pass. New suites: `tests/test_attached.py`
(20), `tests/test_browser_scan.py` (12), `tests/test_pool_rdp_join.py` (7), `tests/js/test_browser_one_pass.mjs`
(8, now part of `npm run test:js`). The JS suite was proven RED against the pristine `741b771` files (0 pass /
8 fail) and restored to 8/8, so every assertion is real.

Acceptance, mapped: (1) a manually started Firefox **connects** — `connect_tab` accepts `rdp://…/ctx-N`, attaches
one socket, logs the one "🦊 Attached …" line, `client.evaluate(...)` runs the job path's actions in that tab and a
detach leaves the browser running; the `rdp://` refusal of round 8 is gone (D-8). (2) One pass lists Chrome
(`base+0`), Firefox (`base+1`) and Edge (`base+2`), each over its own protocol, skips a browser switched off in
Settings, and reports a down browser once per distinct reason — never once per pass. (3) No HTTP request can reach
an RDP socket, and a Firefox answering HTTP but not its DevTools socket is explained with `--start-debugger-server`
plus why `--remote-debugging-port` is disqualified (Bug 1719505) — the same classification serves `Diagnose` and
the connect failure line. (4) Round-8 stealth rules hold: click-only over `evaluate`, no spawned browser, no
geckodriver/Selenium/Playwright, `navigator.webdriver` untouched; BiDi stays detected-but-refused-by-name. (5) A
pass no enabled browser answered raises `endpoints.ScanUnavailable` to the reconciler ("Reconcile skipped"), so an
unusable pass can never look like "every tab closed" and advance removal misses.

Gates: pytest **2,147 passed / 11 skipped** (143.5 s), JS **377 tests / 373 pass / 0 fail / 4 skipped**, coverage
**89.14 % line / 84.57 % branch** (baseline 86.36 / 82.33 — the line lane never decreased; branch is 2.2 points above
the 75 % floor), `verify_quality.py --changed-files` **0 fails**, whole-repo lane only the pre-existing untouched
`captcha.js max_cc 12 > 10`, and `js_metrics` worst levels on the three touched JS files: loc 17 / cc 10 / depth 2.
RULE 16 work during the round: `renderScanLine` extracted (loc 10, cc 10) and `browserTag` (loc 4, cc 3); in Python
`_rdp_session_line` split out of `diagnose`, `pool_page_for` shared by the three join paths, and `reconcile_tabs`
separated from `live_tab_rows` so each keeps one responsibility.

Honest limits, named in the design doc §4: BiDi is detected, listed and refused **by name** (driving it would flag
the browser); RDP has no input synthesis, screenshot or file chooser — the panel lists those gaps instead of
timing out; a Firefox row whose endpoint is closed yet whose tab is still trusted by the settings is reported, not
silently dropped; the app still never starts a browser.

## Known debt carried (tracked in `docs/archive/2026-10-02-captcha-watcher-isolation/design.md` §7)

* `captcha_recording/` + Records window kept (F-1).
* `captcha/stats.py` `auto_*` counters no longer incremented (F-2).
