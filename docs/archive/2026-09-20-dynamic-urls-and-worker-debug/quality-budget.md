# Quality budget — Dynamic URLs & Worker Debug Panel (round 2, PLAN ONLY)

RULE 16 (gates) + RULE 18 (ideal sizes) numbers for the single wave **W1** in `design.md` §9.
Baseline: `tools/quality_baseline.json` @ `6bbaf8b` (222 entries) · `tools/jscpd_baseline.json` 1.24 %
· round-1 budget (`../2026-09-20-live-processing-and-watcher-scope/quality-budget.md`) is **merged
into this one** — W1 replaces the S0…S5 staging, so this file is the single budget to check at the end.

> Gate-metric convention: JS `file_lines` comes from `tools/js_metrics.js` (`fileLines`), which counts
> one more than `wc -l` for these files (e.g. `cdp.js` = 135 gate / 134 `wc -l`). All numbers below
> are **gate** numbers.

---

## 1. Gate commands (bootstrap first — this checkout has no `.venv`/`node_modules`)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt radon vulture coverage cognitive-complexity
npm ci
# fast lane, after every step of W1:
.venv/bin/python tools/verify_quality.py --changed --allow-legacy --coverage-ratchet
# full lane, once at the end of W1 (step 12):
bash tools/pre_push_check.sh
.venv/bin/python tools/verify_quality.py --allow-legacy --coverage-ratchet     # all files
npm run test:js                                                               # 25 → 27 .mjs files
.venv/bin/python -m pytest -q                                                 # unit + integration
.venv/bin/radon cc app -n C -s                                                # nothing worse than C
.venv/bin/python -m cogapp -s 15 app 2>/dev/null || true                      # cognitive ≤ 15 (RULE 16)
npx jscpd app --reporters json --output /tmp/jscpd                            # ≤ 1.24 %
```

`--record-baseline` is **integrator-only** and is not part of W1 unless a maximum must move; if it is
used, the commit message states which maximum, why, and which decision in `design.md` §2 forced it
(`verify_quality.py:761-812`, RULE 16 §16.5 "never grandfathered").

---

## 2. Global floors (must not drop)

| Lane | Floor | Source |
|---|---|---|
| Coverage line | **86.09 %** | `quality_baseline.json` → `coverage.line` |
| Coverage branch | **82.01 %** | `coverage.branch` |
| Duplication | **1.240 %** | `tools/jscpd_baseline.json` |
| Frozen slot surface | **134 slots**, `EXPECTED_PACKING` sum, Bridge ≤ 10 direct methods, `bridge.py` ≤ 300 LOC | `tests/test_bridge_slots.py`, `tests/test_bridge_metaobject.py:41,47` |
| Window registry | Python ≡ JS ids/order/titles (16 after W1) | `tests/test_grid_layout.py:117-121` + new `tests/test_window_catalog.py` |
| Hard limits (every new symbol, any file) | func ≤ 30 LOC, class ≤ 150, params ≤ 4, methods ≤ 15, CC ≤ 10, cognitive ≤ 15, nesting ≤ 4 | `verify_quality.py:237` (JS), `check_*` (Python) |

**Expected direction after W1:** duplication **down** (round-1 §7.1 merges the eligibility clone pair
`queue_scan.selected_images:28-31` ≡ `batch_orchestrator._selected_images:374-377`; round-1 §5.4
deletes a JS interval), coverage **up** (new logic in new fully-tested files), JS lines **down by 1**
(`cdp.js` 135 → 134), Python `layout_service.py` **down ~28 lines** (catalog extraction).

---

## 3. Per-file ratchet budget — existing files touched

### 3.1 Python (maxima frozen; `file_lines`/`func_count` are recorded but **not** enforced — `verify_quality.py:170-176,296-311`)

| File | maxima that must NOT grow | Symbol spans today → after | Coverage floor | Lines |
|---|---|---|---|---|
| `app/core/layout_service.py` | func_loc **21**, cc 9, nest **4**, params 3 | `default_grid_tree` 21 → **21** (leaf added on an existing line); `parse_grid_payload` 17 → 17; `migrate_grid_tree` 16 → 16 | 97.56 | 300 → **~272** (table moved to `window_catalog.py`, re-export line added) |
| `app/core/models.py` | class_loc 74, func_loc 28, cc 3 | `UrlRow` 8 → 9 fields (dataclass attribute, no function span) | **100.0** | 292 → 293 |
| `app/ui/services/arena_serialize.py` | func_loc **23** | `urls_to_js` 14 → **15**; `settings_to_js` **23 → 23** (untouched) | **100.0** | 91 → 92 |
| `app/ui/services/undo_entries.py` | func_loc 17, cc 7 | `url_rows_from_js` 11 → 12; `arena_url_rows_from_js` 8 → 9 | 67.85 | 404 → 406 |
| `app/ui/panels/app_settings.py` | func_loc **18**, methods 10, cc 7, class_loc 118 | `save_settings` 16 → **17**; new `apply_url_interval` **7** (new symbol, hard limits) | 72.43 | 359 → ~368 |
| `app/ui/panels/layout_state.py` | func_loc 19, methods 14, class_loc 136 | `emit_arena_state` 10 → **11** | 85.34 | 281 → 283 |
| `app/ui/panels/run_control.py` | func_loc 19, methods 10, cc 6 | `reset_image_state` 8 → **8** (param deleted); `reset_all` 9 → 10 (log line); `reset_image` 11 → 11 | 82.77 | 275 → ~274 (round-1 `commit_queue` tail shrinks 8 slots) |
| `app/ui/panels/page_pool.py` | func_loc 16, params **4**, methods 9 | `connect_page_pool` 13 → **13** (one word) | 82.24 | 234 → 235 (import) |
| `app/browser/output_wait.py` | func_loc **23**, cc 8, nest 3, params 4 | `_check_timeout` 11 → **11** (line replaced); `wait_for_new_output_with_spec` 23 → 23; new `PauseClock.note` **8** (charges `min(seconds, cap − total)`, D-14R), `PauseClock.expired` **3**, `PauseClock.describe` **5**, `paused_elapsed` **5**, `_paused_elapsed` **4** (all new symbols ≤ 30 / CC ≤ 10); `WaitSpec` +1 field | 94.95 | 211 → **~250** |
| `app/browser/cdp_arena/output.py` | func_loc **16**, params **4**, cc 4 | `_run_wait` 14 → **15** (builds `PauseClock(cap=getattr(spec.ctrl, "pause_cap_s", 0.0))`); `_security_gate` 10 → **12**; `_map_wait_result` 10 → **11** and its params drop **4 → 3** (`(cdp, result, spec)`); `WaitSpec:29-35` and `mixins.wait_for_new_output:139-146` signatures **unchanged** (the cap rides `ctrl`) | 91.56 | 182 → ~187 |
| `app/services/captcha/service.py` | func_loc **27**, cc 7, params 4 | `_manual_wait` **27 → ~21** (the 7-line solved/stopped `if/else` at `:269-275` is extracted; the cap rides the existing `stop` argument at `:262`); new `_wait_outcome` **~14**; `_resolve_captcha` 8 → 9 (D-15 reason); `handle_captcha` 20 → 22 (round-1 scope gate) | 94.69 | 310 → ~316 |
| `app/persistence/config_manager.py` | class_loc 44, func_loc 13 | `DEFAULT_SESSION` module dict +1 key | 95.24 | 124 → 125 |
| `app/services/single_job_runner.py` | func_loc **26**, cc 9, nest 3 | round-1 gate edits: `check_security` 10 → 11, `_handle_security` unchanged; `wait_for_output` 19 → **20** (installs `ctrl.pause_cap_s` next to `security_settler:249`, cleared in the same `finally:257-261`); `_handle_captcha_outcome` 11 → **13** (maps `wait_timeout` → `RuntimeError(reason)`) | 83.45 | 902 → ~900 |
| `app/services/batch_orchestrator.py` | func_loc 17, cc 7 | round-1 §6.3 surgery (tail calls deleted, `_selected_images` deleted) | 92.51 | 492 → **~445** |
| `app/services/run_state.py` | func_loc 18, cc 7 | round-1: `_track_batch_future` deleted, `schedule_batch` added (**≤ 18**) | 82.09 | 417 → ~410 |
| `app/ui/panels/queue_scan.py` | func_loc 19, methods 10 | round-1: `selected_images` → 2-line delegation; 3 slot tails → `commit_queue` | 52.24 | 315 → ~305 |
| `app/ui/panels/browser_tabs.py` | func_loc 20, methods 7, class_loc 76 | round-1 D-10: reconciler + row helpers move out, delegations left | 89.13 | 544 → **~440** |
| `app/ui/panels/url_queue.py` | func_loc 14, methods **11** | round-1: `_dedupe_state_rows`/`_add_missing_rows` → delegations (methods count must not grow) | 96.88 | 251 → ~245 |
| `app/services/auto_connect.py` | **coverage 100**, nest **4**, cc 9 | **read-only reuse** (`enabled_tab_ids:203-209`) — no edit | 100.0 | 286 → 286 |
| `app/services/cooldown_service.py` | func_loc 22, cc **10**, params **4** | **untouched**: `wait_captcha_cleared:446-463` keeps its 4-param signature (at the file maximum) and its wait-only contract — the cap (D-14R) is composed into the `stop` predicate by `captcha/policy.WaitDeadline`, so `tests/test_cooldown_service.py:604-618` stays green **unedited**; `set_tab_image:158` unchanged | 93.64 | 787 → **787** |
| `app/browser/page_pool.py` | func_loc 23, class_loc 143, methods **15**, params 5(!) | unchanged (L-1 is in the *panel*, not the pool) | 88.78 | 207 → 207 |

### 3.2 JS — **net-zero ledger** (every baselined `.js` file: `file_lines` and `func_count` may not grow, `verify_quality.py:252-270`)

| File | lines before → after | funcs before → after | The edit |
|---|---|---|---|
| `js/sash-core/constants.js` | 25 → **25** | 3 → **3** | `{ id: 'live_debug', title: 'Live Worker & Queue Debug' },` appended to the `arena_presets` line; `VERSION: 6` on the existing return line (IIFE span 22 = file max ⇒ no new line allowed) |
| `js/sash-grid-windows/store.js` | 122 → **122** | 19 → **19** | `live_debug: 'winLiveDebug',` appended to the last `winElIds` line (`_collectPanels` span 14 = file max) |
| `js/arena-app.js` | 176 → **176** | 28 → **28** | `'LiveDebugPanel'` appended to the last `_PANEL_INITS` line (module const, not a function) |
| `js/panels/url-list/render.js` | 74 → **74** | 12 → **12** | receiver `<span>` inside the existing one-line `rowHtml` template |
| `js/panels/cdp.js` | 135 → **134** | 55 → **54** | round-1 §5.4: the 15 s `setInterval` is **deleted** (shrink ⇒ ratchet-safe) |
| `js/arena-app/listeners.js` | 168 → **168** | 51 → **51** | **untouched** — the new panel self-connects (D-22) |
| `js/panels/settings.js` | 252 → **252** | 48 → **48** | **untouched** — interval control lives in the new window (D-12) |
| `js/panels/page-pool.js`, `page-pool/{store,render,actions}.js` | 43/32/119/134 → **same** | 24/4/20/22 → **same** | **untouched** — the rescued markup keeps every element id (D-21) |
| `js/panels/image-queue.js` | 140 → **140** | 45 → **45** | **untouched** — Reset All behaviour is Python-side (D-16) |
| `js/core/boot.js` | 109 → **109** | 14 → **14** | **untouched** — `Boot.onBridgeReady`/`needBridge`/`panel` already suffice |
| `index.html`, `css/*` | ungated | ungated | orphan `winPagePool` div → `winLiveDebug` (+ queue head, interval control, worker job lines), 1 new `<link>`, 4 new `<script>` tags |

**Ledger total: 0 new lines and 0 new functions in any baselined `.js` file; −1 line, −1 function in
`cdp.js`.** Any step that cannot honour this is re-designed, not re-baselined (R16).

---

## 4. New files — hard limits only (unbaselined), RULE 18 ideals as the target

| File | Target LOC | Hardest symbol (budget) | The test that kills it if deleted |
|---|---:|---|---|
| `app/core/window_catalog.py` | 45 | module table only (no function > 5 LOC, CC 1) | `tests/test_window_catalog.py::test_python_and_js_tables_identical` |
| `app/services/live/debug_view.py` | 90 | `live_view` ≤ 20 LOC / CC ≤ 6 / params ≤ 2; `interval_ms` ≤ 8 / CC 3; `next_queued` ≤ 6 / CC 2; `clamp_interval_ms` ≤ 5 / CC 2 | `tests/test_live_debug_view.py::test_next_queued_is_first_eligible` |
| `app/services/live/bus.py` (round 1) | 90 | `LiveBus.wait` ≤ 18 / CC ≤ 5 | `tests/test_live_bus.py::test_wake_from_qt_thread_sets_event` |
| `app/services/live/supervisor.py` (round 1) | 230 | `run_live` ≤ 28 / CC ≤ 8 / nest ≤ 3; `plan_pass` ≤ 20 / CC ≤ 6 | `tests/test_live_supervisor.py::test_no_work_waits_and_never_ends` |
| `app/services/live/feed.py` (round 1) | 150 | `commit_queue` ≤ 14 / CC ≤ 4; `eligible_images` ≤ 6 / CC 2 | `tests/test_live_feed.py::test_commit_queue_wakes_loop` |
| `app/services/live/reconcile.py` (round 1 + interval/receivers) | 215 | `reconcile_once` ≤ 28 / CC ≤ 9 / params ≤ 3 (spec object); `reconcile_loop` ≤ 16 / CC ≤ 5 | `tests/test_live_reconcile.py::test_interval_read_every_pass` |
| `app/services/live/url_policy.py` (round 1 + receivers) | 185 | `removable_rows` ≤ 20 / CC ≤ 8 (predicate table, not if/elif); `mark_receivers` ≤ 10 / CC ≤ 4; `receiver_reason` ≤ 8 / CC ≤ 4 | `tests/test_url_policy.py::test_mark_receivers_flags_unchecked_and_offline` |
| `app/services/live/__init__.py` (round 1) | 30 | re-export facade (RULE 16.0 waiver) | import in every live test |
| `app/services/captcha/policy.py` (round 1 + D-14R/D-15/D-23) | 75 | `captcha_in_scope` ≤ 6 / CC 2; `wait_reason` ≤ 10 / CC ≤ 4; `has_key` ≤ 6 / CC 2; `pause_cap_seconds` ≤ 8 / CC 3; `WaitDeadline.stop_or_expired` ≤ 8 / CC 3, `WaitDeadline.expired` ≤ 3 | `tests/test_captcha_scope.py`, `tests/test_captcha_wait_reason.py::test_no_key_wording_names_the_paused_timeout`, `tests/test_captcha_wait_cap.py::test_deadline_ends_the_wait_at_the_cap` |
| `js/panels/live-debug.js` | 90 | `init` ≤ 20 LOC / CC ≤ 6 / params ≤ 1; ends `window.LiveDebugPanel = LiveDebugPanel` (I-35) | `tests/js/test_live_debug_panel.mjs::publishes itself` |
| `js/panels/live-debug/store.js` | 80 | `tick` ≤ 12 / CC ≤ 4; `cache` setters ≤ 8 | `…::ticker recomputes elapsed without a bridge call` |
| `js/panels/live-debug/render.js` | 130 | `workers` ≤ 24 / CC ≤ 8 / params ≤ 2; `queueHead` ≤ 14 / CC ≤ 4; `interval` ≤ 12 | `…::renders paused worker line + first image name` |
| `js/panels/live-debug/actions.js` | 70 | `saveInterval` ≤ 16 / CC ≤ 5 | `…::save calls save_settings with the clamped ms` |
| `css/live-debug.css` | 60 | ungated (`.url-not-receiver`, window strips) | rendered by the JS test's DOM assertions (class present) |

Every new Python symbol also gets a `# ideal-size:` comment only if it exceeds a RULE 18 ideal
(none of the above does).

---

## 5. RULE 18 ideal-size recheck (the end-of-change check the brief asks for)

| Ideal | Before W1 | After W1 | Verdict |
|---|---|---|---|
| **18.1 function 4-20 LOC** | 3 files carry functions > 20 LOC that this wave touches (`single_job_runner` 26, `output_wait` 23, `captcha/service` 27 — all frozen maxima, none grown) | no new symbol > 20 LOC except `run_live` (28) and `reconcile_once` (28), each with an `# ideal-size:` reason (loop body + one pass, splitting would scatter the wake/plan/act triad) | ✓ with 2 documented deviations |
| **18.2 file 150-300 LOC** | `layout_service.py` **300** (at ceiling), `single_job_runner.py` 902, `cooldown_service.py` 787, `browser_tabs.py` 544, `batch_orchestrator.py` 492, `undo_entries.py` 404, `run_state.py` 417 (legacy, reason comments) | `layout_service.py` → **~272** ✓; `browser_tabs.py` → ~440; `batch_orchestrator.py` → ~445; new files 40-215 ✓; `single_job_runner.py`/`cooldown_service.py` unchanged (legacy debt, not worsened — RULE 16 §16.5) | ✓ direction improved |
| **18.3 module 5-15 files** | `app/core` **13**, `app/services` **12** + 6 packages, `app/services/captcha` **6**, `app/browser` **23** (already over), `app/ui/panels` **16** (already over), `app/ui/services` **9** | `app/core` → **14** ✓; `app/services/live` → **7** ✓; `app/services/captcha` → **7** ✓; `app/browser` → **23 unchanged** (PauseClock folded into `output_wait.py`); `app/ui/panels` → **16 unchanged** (no new panel file) | ✓ two pre-existing over-ideal modules are **not worsened** (RULE 16 §16.5) |
| **18.2b sub-150-LOC files** | `bus.py` 90, `captcha/policy.py` 35 (round 1) | `window_catalog.py` 45, `debug_view.py` 90, `captcha/policy.py` 55, `live-debug/actions.js` 70, `store.js` 80 (`PauseClock` is **not** a new file — it lives in `output_wait.py`, 245 lines, inside the band) | deliberate: each is **one decision** (a table, a clock, a predicate trio, one window's actions/cache) — splitting further would scatter twins that always change together, which is what the 150-300 band protects against |
| **18.4 context 60-200 LOC per reading unit** | round-1 §3.1 module table | the debug window is read as 4 files × 70-130 LOC; `window_catalog.py` is a 45-line table read with `layout_service.py`'s 272 | ✓ |
| **RULE 10 one control per decision** | interval: none; receivers: none; pause: none; workers UI: **destroyed** (L-5) | one setting + one control (debug window), one receiver writer (`mark_receivers`), one pause owner (`PauseClock`), one worker table (`PagePoolPanel`) + one job view (`LiveDebugPanel`) | ✓ |
| **RULE 19 remediation order** | — | data before branches: `receiver` flag, `live` payload dict, `wait_reason` table, `PauseClock` value — no new if/elif chains; `removable_rows`/`wait_reason` are lookup tables | ✓ |

---

## 6. Test matrix

### 6.1 New test files (each new function gets a test that fails if the function is deleted)

| Test | Covers |
|---|---|
| `tests/test_page_pool_join.py` | **L-1**: `connect_page_pool` schedules via `run_state.schedule_coro` on a host **without** `_schedule_coro` (fails on `6bbaf8b`); the coroutine reaches the pool |
| `tests/test_window_catalog.py` | Python ≡ JS window tables (ids, order, titles, version); every id has an element id in `_collectPanels`; `live_debug` present; `default_grid_tree` leaf set ≡ `WINDOW_IDS` |
| `tests/test_pause_clock.py` | `note` accumulates, ignores ≤ 0, never raises; **charges at most `cap − total`** so a second settle in the same wait adds nothing (R22); `expired()`; `paused_elapsed` subtracts; `describe` wording (all in `output_wait.py`) |
| `tests/test_output_wait_timeout_pause.py` | a settle that blocks longer than `timeout` **does not** time out (clock charged); the same wait **without** a clock times out (Watcher-OFF equivalence); the failure text carries `+Ns captcha wait` and `paused_s` |
| `tests/test_captcha_wait_reason.py` | three-way `wait_reason` (ON+key / ON+no-key / OFF-unreachable); `_resolve_captcha` passes it through; the overlay still receives `timeout_sec` |
| `tests/test_captcha_wait_cap.py` | **D-14R**: a dialog that never clears ends the wait at `watcher_captcha_timeout_sec` ⇒ `SolveOutcome(status="wait_timeout")` ⇒ `_handle_captcha_outcome` raises ⇒ job FAILED (retryable), no penalty recorded, cooldown as usual; a Stop before the cap still yields `stopped`; a smaller/larger config value moves the cap with no restart; `wait_captcha_cleared` itself is called unchanged (spy asserts 4 args) |
| `tests/test_watcher_off_zero_activity.py` | **D-23**: with the switch OFF a visible dialog produces **zero** side effects — counted on spies: 0 detect probes, 0 `is_security_dialog_visible` polls, 0 overlays, 0 `mark_waiting`, 0 stats writes, 0 recordings, 0 penalties, 0 `🛡`/`CAPTCHA_*` log lines, `PauseClock.total == 0`, no `pause_cap_s` on the controller, and no captcha wording in `live_view` |
| `tests/test_url_interval_setting.py` | default 5000; clamp 500/60000; `save_settings` persists only when the key is present; `interval_ms` re-read per pass (a fake bridge whose value changes between passes changes the sleep); published in `progress_updated.live` |
| `tests/test_url_receivers.py` | `mark_receivers` flags unchecked / unlinked / offline rows; connected+enabled ⇒ receiver; `urls_to_js` publishes the flag; undo builders keep it; `commit_urls` recomputes |
| `tests/test_reset_requeues.py` | `reset_image` and `reset_all` ⇒ `pending` + `selected=True` + `commit_queue` + the count log line; undo restores prior statuses |
| `tests/test_live_debug_view.py` | `live_view` is read-only (no state mutation), `queued`/`next_image`/`receivers`/`url_interval_ms`/`last_pass_at` shapes; `next_queued` = first `eligible_images` entry |
| `tests/js/test_live_debug_panel.mjs` | boots the **real** `index.html` script list (like `test_boot_all_panels.mjs`): `window.LiveDebugPanel` published; grid mounts `winLiveDebug` (not destroyed — L-5 regression); queue head renders count + first image name; a `waiting_captcha` page renders the paused-timeout line; interval Save calls `save_settings` with the clamped ms; the 1 s ticker recomputes elapsed **without** a bridge call |
| `tests/js/test_url_list_receiver_icon.mjs` | `UrlListRender.rowHtml({receiver:false})` contains `.url-not-receiver` with the title; `receiver:true` does not; `render.js` line count unchanged (net-zero guard) |
| round-1: `tests/test_captcha_scope.py`, `test_live_{bus,supervisor,feed,reconcile}.py`, `test_url_policy.py` | round-1 features 01-04 (unchanged scope) |

### 6.2 Existing tests that must change (named, with the reason — no silent rewrites)

| Test | Change | Reason |
|---|---|---|
| `tests/test_grid_layout.py:245-247,253` | `15` → `16` (4 asserts) | the window set grows by one (D-20/D-21) — a deliberate contract change |
| `tests/test_grid_layout.py:117-121` | none (assert stays) | it already compares Python with the parsed JS table; both sides change together |
| `tests/test_grid_layout.py` imports | `from app.core.layout_service import …` keeps working (re-export); optionally import from `window_catalog` | catalog extraction (§3.1) |
| `tests/js/sash_harness.mjs:16-19` | `ALL_WINDOW_IDS` += `'live_debug'` | harness must mirror the registry |
| `tests/js/sash_harness.mjs:33-47` | `TITLE_SECONDARIES.live_debug = { pre: [], post: ['ldQueuedBadge'] }` (+ `BADGE_LIKE` if the badge is count-like) | `test_title_fit.mjs:107` iterates every window: the 96 px title-bar invariant must hold for the new title |
| `tests/js/test_title_fit.mjs:186` | none | asserts migrated leaf count ≡ `ALL_WINDOW_IDS.length` (self-consistent) |
| `tests/test_layout_service_full.py` | none | all asserts are `sorted(leaf_ids) == sorted(WINDOW_IDS)` (self-consistent) |
| `tests/test_panel_slots.py:220` | none | `reset_all()["ok"] is True` still holds (D-16 changes semantics, not the reply) |
| `tests/test_bridge_slots.py` | **none** | no slot is added, removed or renamed (D-20): `reset_all`, `save_settings`, `connect_page_pool` all exist |
| `tests/test_bridge_metaobject.py` | **none** | no signal added; `bridge.py` unchanged |
| `tests/test_cooldown_service.py:604-618` | **none** | the cap is composed by the caller (D-14R) — `wait_captcha_cleared` keeps its "never gives up on its own" contract and its 4-param signature |
| `tests/test_captcha_service.py` (never injects) | **none** expected | the pipeline stays wait-only; only the wait's *end* is now bounded — if an assertion pins the unbounded behaviour it is updated **by name** in the commit message, never silently |
| `package.json` → `scripts["test:js"]` | append the 2 new `.mjs` files (25 → 27) | the JS lane is an explicit list |
| characterization goldens (`tests/goldens/*`) | expected **unchanged**; regenerate only with a reviewed diff (`UPDATE_GOLDENS=1`) | no golden arms captcha-wait + timeout together; pinned log strings kept (round-1 R7) |

### 6.3 Equivalence gates (behaviour that must NOT change)

* Watcher OFF: identical job outcome and identical log lines as `6bbaf8b` **minus** the captcha noise
  (round-1 D-1) — and the generation timeout unchanged (clock 0), asserted by
  `test_output_wait_timeout_pause.py`.
* Pool panel behaviour: `PagePoolPanel` renders the same table/controls (same element ids) — asserted
  by booting the real script list in `test_live_debug_panel.mjs`.
* Grid persistence: a stored v5 15-window layout still loads, migrated to 16 leaves
  (`test_layout_service_full.py:264-289` already covers the mechanism; `test_title_fit.mjs:186` the JS side).
* Undo kinds: no new kind; `settings` undo covers the interval, `queue` undo covers both resets.
* `wait_captcha_cleared` contract: unchanged (still stop-honoured, still returns `True` when the dialog
  clears or the probe errors) — the bound is added **outside** it (D-14R).
* Watcher ON with a fast solve: identical outcome, logs and penalty as `6bbaf8b` — the cap only bites
  when the wait exceeds it.

---

## 7. Docs to update in the same change (RULE 17)

| Doc | Edit |
|---|---|
| `docs/current/SYSTEM_OF_RECORD.md` row 8 (Settings) | add "URL update interval (`url_reconcile_interval_ms`, 500-60000 ms, default 5000) — control in the Live Worker & Queue Debug window" |
| row 11 (CDP connection) | replace "scan on start + every 15 s" with the Python reconciler at the user-set interval + immediate passes on wake; JS 15 s interval deleted |
| row 12 (Security / CAPTCHA) | Watcher OFF = **zero captcha activity** (round-1 D-1 + D-23); Watcher ON = detect + wait + **generation timeout paused for that page, capped at `watcher_captcha_timeout_sec`** ⇒ at the cap the wait ends and the job fails retryable as `wait_timeout` (D-13/D-14R); no-key wording (D-15); `wait_captcha_cleared` itself unchanged |
| row 8 (Settings) / Watcher window | note that `watcher_captcha_timeout_sec` now doubles as the pause cap (one knob, RULE 10) and is read per wait ⇒ no restart |
| row 19 (Modern UI) | **15 → 16 windows**, add `live_debug` ("Live Worker & Queue Debug"), fix the stale `captcha_records` name (the id is `recordings`, `LEGACY_WINDOW_IDS`), note the L-5 rescue |
| row 21 (Job cycle & cooldown) | receiver flag = the row-level view of the existing run gate; reset semantics (D-16) |
| §5 invariants | amend I-19 / I-33 / I-34 / I-35 / I-37 / I-42; **add I-43…I-46** (`design.md` §10) |
| `docs/current/AGENT_RULES.md` RULE 20 | append (round-1 D-2 + D-13/**D-14R**/D-23): *"…the pipeline still never solves; with the Watcher ON it waits, and the waiting page's generation timeout is paused for that wait — bounded by `watcher_captcha_timeout_sec`, at which the job fails honestly (`wait_timeout`) instead of hanging. With the Watcher OFF there is no captcha activity of any kind: no probe, overlay, pool mark, stats, recording, penalty, log line or pause."* |
| `docs/current/QUALITY_RECHECK.md` | refresh with the step-12 numbers (tests, JS lane, size/complexity, slot contract 134, window contract 16, coverage, duplication) |
| `docs/README.md` | this folder's bullet (added with the plan) + the "current truth" line that says "UI 15 windows" → 16 |
| `docs/current/DOM_SELECTORS.md` | untouched (no arena.ai selector changes in this wave) |

---

## 8. RULE 16.7 acceptance checklist (fill in at the end of W1, step 12)

- [ ] Bootstrap done; equivalence baseline captured (§1) — numbers: ______
- [ ] `verify_quality --changed --allow-legacy`: **0 fails**; no ratchet breach in §3.1/§3.2
- [ ] JS ledger honoured: every baselined `.js` file's `file_lines`/`func_count` unchanged (or lower)
- [ ] No new slot, no new signal: `test_bridge_slots.py` + `test_bridge_metaobject.py` green **unedited**
- [ ] Window contract: Python ≡ JS ≡ `_collectPanels` (16), stored v5 layouts migrate, `test_title_fit` green
- [ ] `pytest -q` green; coverage line ≥ 86.09, branch ≥ 82.01; per-file floors of §3.1 held
- [ ] `npm run test:js` green with the 2 new files listed in `package.json`
- [ ] jscpd ≤ 1.240 %; `radon cc app -n C` shows no new C-or-worse symbol; cognitive ≤ 15
- [ ] Goldens unchanged (or the reviewed diff is pasted into the commit message)
- [ ] **Cap proven**: one image's worst case is `generation_timeout + watcher_captcha_timeout_sec`;
      a second captcha in the same generation absorbs no extra pause (R22); a cap-reached job fails as
      `wait_timeout` with the knob named in the reason
- [ ] **Watcher OFF proven to be silent**: `tests/test_watcher_off_zero_activity.py` counts zero side
      effects (D-23), including `PauseClock.total == 0`
- [ ] RULE 18 recheck table (§5) filled with the measured numbers, deviations carry `# ideal-size:` reasons
- [ ] RULE 17: every doc row in §7 updated **in the same commit series** as the code
- [ ] `bash tools/pre_push_check.sh` clean; `--record-baseline` unused (or justified in the commit message)
- [ ] Manual pass on a real Chrome: (1) interval change applies without restart, (2) captcha with
      Watcher ON pauses the timeout and the job still completes, (3) Watcher ON without a key waits for
      the manual solve with the honest reason, (4) Watcher OFF ignores the captcha and times out
      normally, (5) a captcha left unsolved past `watcher_captcha_timeout_sec` fails the job with the
      cap named in the reason and the tab cools down, (6) Reset All re-queues and a live run picks the
      images up, (7) the debug window shows
      workers/queue head and reacts to a tab added/removed, (8) the ⊘ icon appears on an unchecked or
      offline row and disappears when it becomes a receiver

---

## 9. What this plan refuses to do (anti-gaming, stated up front)

1. **No baseline re-record to make room.** `--record-baseline --refresh` is not a way to fit a feature;
   every JS edit is net-zero and every Python symbol stays under its frozen maximum (§3).
2. **No new slot/signal for the debug window.** The information rides existing payloads (D-22); if a
   future need appears, it is a contract review, not a quiet addition.
3. **No JS re-implementation of a Python rule.** Eligibility/receiver/next-image are computed once in
   Python and reflected (D-18, I-45, I-41).
4. **No second worker table.** The pool panel is rescued, not duplicated (D-21); the job-line list is
   a different view with no shared templates (jscpd is measured, not assumed).
5. **No timeout cap dressed as a pause.** The pause is exact, charged only around a real settle, and
   reported in the failure text and the UI (D-13/D-14R, I-44).
6. **No silent contract growth.** The window set changes 15 → 16 with every pinned test updated in the
   same commit and the reason recorded here (§6.2).
7. **No silent cap, no silent silence.** The cap is one existing user knob (`watcher_captcha_timeout_sec`),
   reported in the throttled pause line, the failure reason and the debug window; "Watcher OFF" is proven
   by a **counting** test (D-23), not by reading code and finding nothing.
8. **No docs-after-code.** RULE 17: §7 lands with the code, and the round-1/round-2 archive folders are
   never edited to catch up (a new folder supersedes, this one amends by naming D-1/D-6/D-9).
