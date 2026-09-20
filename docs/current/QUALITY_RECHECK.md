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

### 2026-09-20 S0 baseline (live chain S0–S10 starts; branch `arena/01a0bf4d-…` from `528af87`)

No production change. Bootstrap `.venv` (Python 3.11.2) + `npm ci` (Node v22.22.3);
untracked 6 runtime files the squashed base commit had re-added (kept on disk);
two test-only reproducibility fixes (`test_qt_compat` skipif now checks the active
shim, new `test_transport_import_without_qt`): pytest **1,617 passed / 8 skipped**,
JS **240/0**, coverage **87.05 / 83.25** (floors 86.36 / 82.33), full gate **0 fails**,
slots **135**, jscpd **1.119 %**. L-1/L-5/L-6/L-7/L-8 confirmed open; §D re-measured
(all enforced maxima hold, `single_job_runner` CC 9 → 7 shrink). Cognitive lib stays
uninstalled to match the recorded baseline (max_cog 0 × 147); new symbols get an
explicit ≤15 scan per stage. Evidence: `docs/archive/2026-09-20-s0s10-live-chain/`.

### 2026-09-20 S1 L-1 fixed (branch `arena/01a0bf4d-…`)

2-line production edit (`page_pool.py`: import + `schedule_coro(self, …)`); L-6 de-masked
(5 test doubles → spy on the real seam). RED observed then green: new
`tests/test_page_pool_join.py` 4/4. Full pytest **1,621 / 8 skipped** (goldens green),
coverage **87.06 / 83.28** (page_pool.py 83.18, floor 82.24), changed-lane gate **0 fails**,
page_pool maxima identical, cognitive ≤6 (edited slot 3/15), slots **135**.
SoR row 11 notes the repair. No JS touched.

### 2026-09-20 S2 Watcher scope gate (branch `arena/01a0bf4d-…`)

New `app/services/captcha/policy.py` (5 predicates, 100% covered) + 5 gate edits
(`check_security`, `_handle_security`, `wait_for_output`, the `handle_captcha`
D-26 split, `_watcher_running` 7→3). RED observed (ImportError, then behavioral),
then green: new scope/zero-activity files 11/11 (incl. the ON positive control).
Full pytest **1,639 / 1 skipped** (goldens byte-identical), coverage
**87.10 / 83.32** (service.py 94.84/94.76, sjr 84.84/83.82, signals.py
97.37/97.37), touched-file gate **0 fails**, maxima identical except unenforced
structure counts, cognitive ≤8 (edited/new ≤7), slots **135**.
SoR row 12 + I-19/I-34 amended, I-48 landed (plan I-40). No JS touched.

### 2026-09-20 S3 Capped captcha pause clock (branch `arena/01a0bf4d-…`)

New `app/core/pause_clock.py` (`PauseClock`, 100% covered) + `WaitSpec.pause` carrier
(span 3→4, at ceiling) + policy cap trio (`pause_cap_seconds` clamped 10…3600,
`wait_reason`, `WaitDeadline`) + `_wait_outcome` (solved ⇒ manual, cap ⇒ wait_timeout,
else stopped). RED observed (4 collection errors), then green: new files 23/23
(real short sleeps, no mocks; OFF positive control keeps its clock at zero).
Armed with recorded reason: `:130` (D-15 rewrites the no-key wording) + `:163`
(solving words need the keystore key AND the loop).
Full pytest **1,662 / 1 skipped** (incl. 15 hygiene; goldens byte-identical), coverage
**87.19 / 83.40** (baseline 86.36/82.33; pause_clock + policy 100), Python gate
**0 fails** (1 JS fail on untouched `captcha.js` is pre-existing — stash-proven),
output_wait maxima byte-identical (23/4/8/3/4), cdp_arena identical, service file max
21 (recorded 27), cognitive ≤8, slots **135**.
SoR rows 8 + 12, I-52 landed (plan I-44). No JS touched.

## Known debt carried (tracked in `docs/archive/2026-10-02-captcha-watcher-isolation/design.md` §7)

* `captcha_recording/` + Records window kept (F-1).
* `captcha/stats.py` `auto_*` counters no longer incremented (F-2).
