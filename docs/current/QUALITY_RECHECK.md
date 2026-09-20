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

## Known debt carried (tracked in `docs/archive/2026-10-02-captcha-watcher-isolation/design.md` §7)

* `captcha_recording/` + Records window kept (F-1).
* `captcha/stats.py` `auto_*` counters no longer incremented (F-2).
