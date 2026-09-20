# Evidence — Dynamic URLs & Worker Debug Panel (round 2, PLAN ONLY)

**Written:** 2026-09-20 · **Branch:** `arena/01a0bc3b-process-images-in-areana` · **Code base for every citation:** `6bbaf8b`
**Status:** research record for `design.md` in this folder. **No production code was changed.**

Chronology note (same as round 1): some `docs/current/` footers carry dates ahead of the git
history (up to 2026-10-05). Citations below are to the **working tree at `6bbaf8b`**, which is the
only truth this plan was researched against.

Round 1 (`docs/archive/2026-09-20-live-processing-and-watcher-scope/`) is the base plan; this round
**amends** three of its decisions (D-1, D-6, D-9) and adds two features. Its evidence file is not
repeated here — only what is new.

---

## 1. Item 01 — the URL refresh cadence is not a setting today

| Fact | Evidence |
|---|---|
| The only periodic URL refresh in the shipped app is a **JS timer**: `setInterval(() => this.autoConnectScan(), 15000)` | `app/ui/web/js/panels/cdp.js:33` (round 1 §5.4 deletes it; the Python reconciler replaces it) |
| A 500 ms JS retry tick also exists (primary-tab reconnect) and stays | `app/ui/web/js/panels/cdp.js:34` |
| Round 1 hard-codes the reconciler cadence at **5 s** with no user surface | round-1 `design.md` §3.2 runtime picture, §7.2 latency table ("≤ 5 s (reconcile interval)") |
| Precedent for an ms setting in session config: `watcher_interval_ms: 2000` next to `watcher_captcha_timeout_sec` / `watcher_generation_timeout_sec` | `app/persistence/config_manager.py:24-26` (module-level `DEFAULT_SESSION:9-31`) |
| Precedent for clamp-on-write of an ms setting: `max(500, min(int(...), 30000))` | `app/ui/panels/watcher_captcha.py:65-73` (`parse_watcher_config`), persisted by `persist_watcher_config:88-98` |
| The generic write slot already exists — **no new slot needed**: `save_settings(settings_json)` applies a chain of `apply_*` helpers | `app/ui/panels/app_settings.py:258-273` (`save_settings`, span 16 LOC), helpers `apply_simple_key:52`, `apply_generation_timeout:60`, `apply_watcher_timeouts:89` |
| Settings JS is **frozen** (cannot grow a line): 252 lines / 48 funcs, and it only reads via `get_cdp_config` / `get_cooldown_config` | `tools/quality_baseline.json` → `app/ui/web/js/panels/settings.js`; calls at `settings.js:81,139,157,179,208` |
| Undo already covers the `settings` kind | `app/ui/web/js/arena-app.js:14` (`UNDO_KINDS`), `push_settings_undo` called at `app_settings.py:271` |

⇒ A new ms key is a **config + one apply-helper + one publish field** change; the frozen Settings
panel cannot host the control (see §6 for why that matters and §5 for where it goes instead).

---

## 2. Item 02 — the generation timeout cannot survive a captcha wait (mechanics, end to end)

The chain, with the exact line where time is measured:

1. `single_job_runner.wait_for_output(ctx, timeout_ms)` installs the mid-wait captcha hook:
   `ctx.ctrl.security_settler = lambda: _settle_and_note(ctx)` — `app/services/single_job_runner.py:249`
   (removed in `finally:` at `:258-261`).
2. `_poll_generation` builds the wait spec with the caller's `timeout_ms` — `single_job_runner.py:232-241`.
3. `cdp_arena/output.py::_run_wait:161-174` wraps it: `PollSpec(timeout=spec.timeout_ms / 1000.0,
   poll_interval=2.0)` (`:169`) and its `check_fn` calls `_security_gate(cdp, spec.ctrl)` **on every
   poll** (`:163`).
4. `_security_gate:115-125` → `if await is_security_dialog_visible(cdp): await settler()`.
   **The time spent inside `settler()` is not measured anywhere.**
5. `output_wait.wait_for_new_output_with_spec:189-211` fixes the clock once:
   `LoopState(..., start=time.monotonic())` (`:190`), and `_check_timeout:150-160` computes
   `elapsed = time.monotonic() - state.start` vs `spec.timeout` — **no pause term exists**.
6. On expiry: `_map_wait_result:127-136` → `"failed", {"error": f"Timeout after {timeout_ms}ms"}`.
7. The settle itself is unbounded by design (RULE 20 today; bounded by the cap in `design.md` D-14R): `_settle_and_note:265-271` →
   `check_security:107-116` → `_run_security_captcha:88-104` → `captcha/service.handle_captcha:210-229`
   → `_resolve_captcha:232-239` → `_manual_wait:242-268` → `cooldown_service.wait_captcha_cleared:446-463`,
   whose docstring is *"Poll until the dialog clears; False only on stop (never gives up)"* — after
   `timeout_sec` it only **warns** every 5 s (`:459-462`) and keeps waiting.

**Consequence (the user's complaint, proven):** with a captcha on screen, step 7 blocks longer than
`timeout_ms`; when it returns, step 5's `elapsed` is already over budget, so the very next
`_check_timeout` fires and the job **fails with "Timeout after …ms" even though the captcha was
cleared**. Nothing in the loop distinguishes "site is slow" from "we were waiting for a human/2Captcha".

Per-case behaviour today (all three of the user's bullets are wrong today):

| Case | Today | Evidence |
|---|---|---|
| Watcher **OFF** | captcha is still detected, overlay shown, penalty recorded, `CAPTCHA_SOLVE` logged, and the wait still burns the generation timeout | round-1 `evidence.md` §1.1-1.2 (four unconditional detection sites); `_resolve_captcha` has no switch check |
| Watcher **ON** + key | solver loop solves (`captcha_watcher`), pipeline waits in `_manual_wait` — and the generation timeout keeps running ⇒ the timeout failure above | `watcher_solver.py:127-136` (`solver_start`), `service.py:242-249` (`_watcher_running`) |
| Watcher **ON**, **no key** | `solver_start` refuses (`{"ok": false, "error": "no api key"}` + the warn line), `_watcher_running` is False, yet the pipeline **already** detects and waits for a manual solve — with the *wrong* amber reason: "solve in Chrome — **or turn the Watcher ON** to auto-solve" | `watcher_solver.py:130-134`; reason string `captcha/service.py:235-237`; wait path `_manual_wait:242-268` |

Headroom facts that shape the fix (baseline maxima, `tools/quality_baseline.json`):

* `output_wait.py` — `max_func_loc 23`, `max_cc 8`, `max_nest 3`, `max_params 4`, 211 lines.
  `_check_timeout` span **11** ⇒ headroom; `WaitSpec` is a 3-line dataclass (`:23-26`).
* `cdp_arena/output.py` — `max_func_loc 16`; `_run_wait` span **14** (headroom 2), `_security_gate`
  span **10**, `_map_wait_result` span **10**.
* `captcha/service.py` — `max_func_loc 27` and `_manual_wait` span **27** ⇒ **zero headroom in
  `_manual_wait`**; `_resolve_captcha` span 8 and `handle_captcha` span 20 have room. The reason
  wording must therefore be produced *outside* `_manual_wait` (it already receives `reason` as a
  parameter — `:257-258` overlay `sub=reason`).

### 2.1 What the cap must be built from (owner correction: *"D-14 should be capped"*, *"no activity at all if off"*)

> **LANDED — S2+S3 (2026-09-20):** the *"no activity at all if off"* half (D-23) landed in S2
> (`app/services/captcha/policy.py` + the five gates + counting tests), and the *"capped"* half
> (D-14R) landed in S3: `app/core/pause_clock.py` (D-25), `_settle_timed` charging (D-26),
> `policy.WaitDeadline` composed into the caller's `stop` predicate, `wait_timeout` outcome,
> one knob `watcher_captcha_timeout_sec` bounding wait AND pause (I-52). Status marker only,
> original evidence below kept verbatim.

| Fact | Evidence |
|---|---|
| The knob already exists, is user-settable and is read **per wait**: `watcher_captcha_timeout_sec`, default 300 | `app/persistence/config_manager.py:25`; read by `_wait_timeout` `app/services/captcha/service.py:190-195`; clamped 10…3600 on write `app/ui/panels/watcher_captcha.py:65-73`; persisted `:88-98`; surfaced in the Watcher window (SYSTEM_OF_RECORD row 12) |
| The wait overlay already counts that same number down ⇒ the cap is visible while it runs | `service.py:257-258` (`show_watcher_overlay(..., timeout_sec=timeout, sub=reason)`) |
| `wait_captcha_cleared(ctrl, stop, timeout_sec, log)` is at the file's **`max_params` 4** and today only *warns* after `timeout_sec` ("never gives up") | `app/services/cooldown_service.py:446-463` (warning branch `:459-462`); baseline for the file: `max_params 4`, `max_cc 10`, `max_func_loc 22`, coverage floor 93.64 ⇒ **the cap must ride the existing `stop` predicate, not a new parameter** |
| That "keeps waiting" behaviour is pinned by a test ⇒ composing the cap in the *caller* keeps the module **and** the test untouched | `tests/test_cooldown_service.py:604-618` (`test_wait_captcha_cleared_timeout_logs_but_keeps_waiting`, asserts `ok is True` + the `⏰` line) |
| `_stop_pred(ctx)` is already the composition point for "stop" | `service.py:65-66` |
| `SolveOutcome.status` is a free-form string ⇒ a new `wait_timeout` status needs no enum edit | `app/services/captcha/signals.py:94-99` (round 1 adds `out_of_scope` the same way) |
| The honest-failure shape to copy already exists, with room to grow | `app/services/single_job_runner.py:75-85` (`page_error` → `raise RuntimeError(outcome.reason)`), span 11 vs file `max_func_loc 26` ⇒ +2 lines fit |
| `_manual_wait` has **zero** headroom ⇒ the outcome mapping must be extracted (the function shrinks) | `service.py:251-277` (span **27** = file `max_func_loc 27`); the solved/stopped `if/else` is `:269-275` |
| The cap cannot travel as a new parameter of the controller wait either | `app/browser/cdp_arena/mixins.py:139-146` (`wait_for_new_output(self, baseline, timeout_ms, correlation_id, cancel_check)` → builds `cdp_arena.WaitSpec:29-35`) ⇒ it rides `ctrl.pause_cap_s`, installed next to `security_settler` (`single_job_runner.py:249`) and cleared in the same `finally:` (`:257-261`) |
| Two captchas inside one generation are possible (the settle runs **per poll**), so a per-encounter cap alone would not bound the absorbed pause ⇒ the clock cap must be cumulative per wait | `cdp_arena/output.py:161-165` (`check_fn` calls `_security_gate` on every poll), `:115-125` |
| "No activity at all if OFF" is measurable today — every side effect has exactly one call site | detect probe `service.py:197-208`; pool mark `_mark_waiting:97` (called `:216`); stats `_record_stats:79` (called `:217`, `:271`); recording `svc.recordings.start/finish` `:220`, `:228`; overlay `:257`; penalty `_record_penalty:88`; report line `_emit_report:180`; per-poll dialog check `cdp_arena/output.py:115-125` — reachable only when the settler is installed (`single_job_runner.py:249`) |

---

## 3. Item 03 — URL rows, the receiver gate, and reset semantics

> **LANDED — S4 (2026-09-20), reset half only:** the reset re-queue evidence below (D-6R) is now
> code — `reset_image_state` lost its `selected` parameter, both resets return images to
> `pending` + `selected=True` and end in `live.feed.commit_queue` (recalc → save → undo →
> emit → `LiveBus.wake`), with a `↻ … re-queued` count line; stale `processing` is recovered at
> Start (`recover_stale_processing`); the single eligibility rule is `core/run_scope.eligible_images`
> (the two clones this section cites were already deleted by B13). The URL-row / receiver facts
> below remain plan evidence for S6/S7. Status marker only, original evidence kept verbatim.

**Row model & serialization**

| Fact | Evidence |
|---|---|
| `UrlRow` has 7 fields, no "can receive a job" flag | `app/core/models.py:13-21` |
| Rows round-trip generically: `to_dict` → `[asdict(u) for u in self.urls]`, `from_dict` → `UrlRow(**u)` ⇒ a new defaulted field persists and loads without migration | `app/core/models.py:250-262`, `:265-267` |
| `urls_to_js` publishes 7 keys; span **14** LOC vs file `max_func_loc 23` ⇒ **+9 lines of headroom** | `app/ui/services/arena_serialize.py:12-25` |
| Undo/redo rebuild rows field-by-field (two builders) — a new field must be added to both or it is lost on undo | `app/ui/services/undo_entries.py:21-31` (`url_rows_from_js`, span 11), `:34-41` (`arena_url_rows_from_js`, span 8); file `max_func_loc 17` ⇒ headroom |
| The row markup is **one template literal on one line** (`rowHtml`) — an inline conditional costs **zero lines** | `app/ui/web/js/panels/url-list/render.js:6-8`; file baseline 74 lines / 12 funcs (frozen) |
| Rows re-render wholesale on state push (`render(urls)` → `tbody.innerHTML=''`) | `render.js:10-27`; fed from `arena-app/listeners.js:127` (`arena_state_updated`) |

**The "job receiver" rule already exists in Python (two halves, one owner each)**

* checkbox gate: `enabled_tab_ids(urls)` — *"Tab ids owned by checked (enabled) URL rows — the run
  gate"* — `app/services/auto_connect.py:203-209`; row→tab lookup `row_for_tab:212-218`.
  `auto_connect.py` is at **100 % coverage**, `max_nest 4` (hard limit) ⇒ must stay untouched.
* pool presence/liveness: `sync_pool_presence` (`auto_connect.py:143`, round-1 evidence §2) and the
  pool snapshot `status_snapshot` → `_snapshot_entry` (`app/browser/page_pool.py:191-197`, `:55-62`),
  with `PageInfo.is_connected` / `is_free()` (`app/browser/page_status.py:49-56`).
* Start-refusal wording already uses the same conjunction ("nothing checked owns a live tab") —
  SYSTEM_OF_RECORD row 21; `run_control.check_start_inputs:56-…`.

⇒ "not used as job receiver" = `enabled` **and** `tab_id` **and** that tab is in the pool **and**
`is_connected`. All four inputs are Python-side; no JS rule is needed (JS only reflects a flag).

**Reset semantics (D-6 reversal)**

| Fact | Evidence |
|---|---|
| `reset_image_state(img, selected)` sets `status="pending"`, `selected=selected`, clears error/output/assignment/attempts | `app/ui/panels/run_control.py:46-53` (span 8) |
| `reset_all` calls it with **`False`** for every image ⇒ the whole queue is parked | `run_control.py:187-195` (`reset_all`, `:190`) |
| `reset_image` also passes **`False`** ⇒ a single Reset does not re-queue either | `run_control.py:210-220` (`:214`) |
| `retry_image` already re-queues (`status="pending"`, `selected=True`) ⇒ the intended semantics exist next door | `run_control.py:197-208` |
| No test passes `False` explicitly; only the slots call it ⇒ the parameter can be deleted, not defaulted | `grep reset_image_state tests/` → no hits; `tests/test_panel_slots.py:220` asserts `reset_all()["ok"] is True`; `reset_all` is a frozen slot name (`tests/test_bridge_slots.py:165`) |
| JS side needs no change: the button just calls the slot | `app/ui/web/js/panels/image-queue.js:34` (`queueResetBtn` → `resetAll()` → `:130` → `_actions.resetAll()`), file frozen at 140 lines / 45 funcs |

---

## 4. Item 04 — L-1 (re-verified, and now load-bearing for item 05)

> **CLOSED — S1 (2026-09-20):** status marker only, original evidence below kept verbatim
> (RULE 17). Fixed by the planned 2-line edit (`schedule_coro` import + call in
> `app/ui/panels/page_pool.py`); RED-first proof `tests/test_page_pool_join.py`
> (failed at base with `'Host' object has no attribute '_schedule_coro'`); L-6
> de-masked in the same commit (`tests/test_panel_browser_tabs.py`, five injected
> `_schedule_coro` doubles → spy on the real `schedule_coro` seam).

* `connect_page_pool` calls `self._schedule_coro(do_connect_page_pool(self, ws_url))` —
  `app/ui/panels/page_pool.py:139-151` (the call is line **147**). No `_schedule_coro` exists
  anywhere in `app/`; the real helper is `app/services/run_state.py:194-202`
  (`schedule_coro(bridge, coro)`), imported and used by every other panel
  (`browser_tabs.py:25,480,491,501,509,522,533,544`, `cdp_tools.py:14,266,282,289,338,347,361`,
  `run_control.py:16`).
* The slot's `except Exception` swallows the `AttributeError` and returns
  `{"ok": false, "error": "…has no attribute '_schedule_coro'"}` ⇒ **the tab never joins the pool**.
* Why item 05 depends on it: the debug window's worker list is the pool snapshot, and round 1's
  reconciler joins newly-matching tabs through exactly this path (`LiveDeps.join_tab` =
  `do_connect_page_pool`, round-1 `design.md` §5.1). With L-1 unfixed, "new webpages appear in the
  live stack" cannot be true.
* Baseline: `app/ui/panels/page_pool.py` `max_func_loc 16`, `max_params 4`, 234 lines, coverage
  82.24 % ⇒ a one-word fix + one import line is inside every limit (Python line growth is not
  ratcheted — §6).

---

## 5. Item 05 — the window registry chain, and a destroyed window (new defect **L-5**)

### 5.1 How a window is registered (every link, with the file that owns it)

| # | Link | File:line |
|---|---|---|
| 1 | Python window table `WINDOW_IDS` (15) + `WINDOWS` (id/title) + `WINDOW_TITLES` + `LEGACY_WINDOW_IDS` + `GRID_VERSION = 5` | `app/core/layout_service.py:11-15`, `:16-31`, `:32`, `:35`, `:36` |
| 2 | Default tree (nested splits/leaves) | `layout_service.py:48-69` (`default_grid_tree`, span **21** = file `max_func_loc 21` ⇒ **zero headroom**) |
| 3 | Validation rejects any leaf set ≠ `sorted(WINDOW_IDS)` ("window set mismatch") | `layout_service.py:213-229` (`parse_grid_payload:226-228`) |
| 4 | Migration **appends missing leaves automatically** (1 missing → leaf; N → row split; wrapped in a col split) | `layout_service.py:283-297` (`migrate_grid_tree`), driven by `_try_migrate:232-251` and `canonical_grid_payload:254-264` |
| 5 | JS mirror table (must be byte-identical in ids/order/titles) | `app/ui/web/js/sash-core/constants.js:3-24` (`WINDOWS`, `WINDOW_IDS`, `WINDOW_TITLES`, `VERSION: 5`); the IIFE span **22** = file `max_func_loc 22`, file 25 lines / 3 funcs ⇒ **zero headroom on both axes** |
| 6 | JS window → DOM element map (a **second**, hard-coded copy of the id list) | `app/ui/web/js/sash-grid-windows/store.js:4-17` (`_collectPanels`, span **14** = file `max_func_loc 14` ⇒ **zero headroom**), file 122 lines / 19 funcs |
| 7 | Grid build/mount: only `winEls[node.id]` is moved into a `.sash-window`; then **`gridEl.replaceChildren(frag)`** | `app/ui/web/js/sash-grid-tree.js:4-12` (`_buildNode`), `app/ui/web/js/sash-grid.js:87-93` (`render`) |
| 8 | JS migration/validation mirror | `app/ui/web/js/sash-core/validate.js:100-142` (`sashDeserializeVersioned` → `sashMigrate` → `sashDeserializeLegacy`), `sash-core/tree.js:100-105` (`defaultTree`, presets) |
| 9 | Panel markup (`<div class="panel" id="winX" data-window="x">` + `<h3 class="win-title">`) and the `<script>`/`<link>` lists | `app/ui/web/index.html:59-…` (16 `data-window` divs — see L-5), scripts `:701-725`, styles `:8-14` |
| 10 | Panel boot registry (`_PANEL_INITS`, 17 names) + global-name contract (`window.X = X`) | `app/ui/web/js/arena-app.js:30-34`, `:36-52`; `app/ui/web/js/core/boot.js:20-28`, `:96-105` |
| 11 | Signal fan-out to panels (registry table; **frozen** at 168 lines / 51 funcs) | `app/ui/web/js/arena-app/listeners.js:124-149` (`buildRegistry`), `:115-118` (`_handlePagePool`) |
| 12 | Boot order: bridge is assigned **before** `initApp()` ⇒ a panel's `init()` may connect signals itself | `arena-app.js:167-173`; precedent `panels/arena-presets.js:39-48` (`presets_changed.connect`), helper `boot.js:38-46` (`Boot.onBridgeReady`) |

Tests that pin the set (all must be updated **deliberately**, like the 134-slot contract):

* `tests/test_grid_layout.py:117-121` — Python ids/order/titles ≡ parsed JS constants
  (`js_windows()`), i.e. the desync guard **covers a new window automatically** once both sides change.
* `tests/test_grid_layout.py:245-247,253` — `window_count == 15` and leaf counts `== 15` (4 asserts).
* `tests/test_layout_service_full.py:22,38,149,237,264,272-289` — all self-consistent
  (`sorted(leaf_ids) == sorted(WINDOW_IDS)`) ⇒ green without edits.
* `tests/js/sash_harness.mjs:16-19` (`ALL_WINDOW_IDS`, 15), `:22-24` (`PANEL_IDS` exceptions),
  `:33-47` (`TITLE_SECONDARIES` per window) — must gain the new id.
* `tests/js/test_title_fit.mjs:107,186` — iterates `ALL_WINDOW_IDS`: the new title must satisfy the
  96 px title-bar invariant (SYSTEM_OF_RECORD row 19) and its migrated leaf count.
* `tests/js/test_boot_all_panels.mjs:107` (`>= 15`) and `tests/test_ui_wiring.py:137` (`>= 15`) —
  green without edits; `test_ui_wiring.py:126-142` additionally requires every `_PANEL_INITS` name
  to be published on `window` (I-35).
* `tests/js/test_sash_split.mjs:52` (`WINDOWS.length > 10`) — green.

### 5.2 L-5 — the Page Pool window markup exists but the window was never registered ⇒ it is destroyed

* `app/ui/web/index.html:263-291` is a full panel: `<div class="panel" id="winPagePool"
  data-window="page_pool">` with the worker table (`poolTableBody`, `:276`), the status badge
  (`poolStatusBadge`, `:264`), counters (`poolTotal/poolSteady/poolBusy/poolCooling/poolFree`, `:271`),
  the three pool buttons (`poolRefreshBtn`/`poolConnectBtn`/`poolClearBtn`, `:267-269`) and a
  "How pool works" help block.
* **`page_pool` is not a window id**: absent from `layout_service.WINDOW_IDS:11-15` and from
  `constants.js:4-19`; absent from `_collectPanels`' map (`store.js:5-10`) ⇒ `winEls` never holds it.
* `render()` replaces the grid's children with the built tree (`sash-grid.js:90`), and `_buildNode`
  only re-parents registered panels (`sash-grid-tree.js:9-10`) ⇒ **`winPagePool` and its 29 lines of
  markup are removed from the document on the first grid render.**
* The panel behind it is alive and fed: `PagePoolPanel` is in `_PANEL_INITS` (`arena-app.js:32`),
  `page_pool_updated` reaches it (`listeners.js:115-118` → `PagePoolPanel.onUpdate`), and the render
  code writes `poolTableBody` / `poolStatusBadge` / the counters
  (`panels/page-pool/render.js:36-42`, `:71-93`, `:108-118`).
  ⇒ Every one of those writes targets a **detached/absent** element: the workers table, the pool
  badge and the pool counters are invisible in the running app.
* Python still does all the work: `_emit_pool_status` (`app/ui/bridge.py:100-108`) emits the snapshot
  and `status_snapshot` (`app/browser/page_pool.py:191-197`) builds it.
* This is exactly the surface item 05 asks for ("show all workers and the status of the job"), so the
  fix is to **register the window** rather than to build a second, duplicate worker table
  (RULE 10 one-control-per-decision; jscpd floor 1.240 %).

### 5.3 Data the debug window needs — already published, zero new slots

| Need | Existing source | Evidence |
|---|---|---|
| Workers: tab, title, url, status, connected, jobs completed, captcha count, cooldown remaining/total/reason, `current_job_id`, **`current_image`**, `busy_since` | `page_pool_updated` snapshot | `PageInfo` fields `app/browser/page_status.py:28-47`; `to_dict:82-110`; `_snapshot_entry` adds `cooldown_remaining` (`app/browser/page_pool.py:55-62`); emitter `app/ui/bridge.py:100-108` (`_emit_pool_status`, emit at `:105`); the Refresh slot emits too (`app/ui/panels/page_pool.py:105-118`, `get_page_pool_status`) |
| `current_image` is really maintained (so a worker's image name is free) | set on job start, cleared on expiry, read by the live-job gate and the batch log | `app/services/cooldown_service.py:158` (`set_tab_image`), `:127`, `:173` (`tab_has_live_job`), `page_status.py:77`, `batch_orchestrator.py:73-74` |
| Job detail per worker (image path, url, attempt, status, error) | `arena_state_updated.jobs` (`JobRecord` list) joined on `current_job_id` | `app/core/models.py:94-113`, serialized at `arena_serialize.py:90` |
| Pending count + run state | `progress_updated` (progress dict + `run_state` patched at emit) | `app/ui/panels/layout_state.py:38-47` (`emit_arena_state`, span **10** vs file `max_func_loc 19` ⇒ headroom) |
| **Name of the first image in the queue** | not published anywhere today; the rule exists twice in Python | `app/ui/panels/queue_scan.py:28-31` ≡ `app/services/batch_orchestrator.py:374-377`; round 1 merges them into `live/feed.eligible_images` (round-1 `design.md` §7.1) ⇒ `next = eligible[0]` |
| URL rows that can receive jobs (item 03 icon + a debug counter) | `enabled_tab_ids` + pool presence (§3) | `auto_connect.py:203-209`, `page_pool.py:191-197` |
| Watcher/solver state (context for a paused worker) | `captcha_watcher_status` | `app/ui/panels/watcher_solver.py:100-109`, `watcher_captcha.py:52-62` |

Frozen-surface check: `tests/test_bridge_slots.py` (`FROZEN_SLOTS`, `EXPECTED_PACKING`, Σ = 134) and
`tests/test_bridge_metaobject.py:41,47` (no slot may lose `@Slot`; `bridge.py` ≤ 300 LOC) — **none of
the above needs a new slot or a new signal**; the only payload change is one extra key inside the
existing `progress_updated` JSON.

---

## 6. The ratchet asymmetry that dictates every edit shape

`tools/verify_quality.py`:

* `JS_METRICS = [max_func_loc, max_cc, max_nest, max_params, **file_lines**, **func_count**]` (`:170`)
  and `check_js` fails growth of `file_lines`/`func_count` **for every baselined JS file on every
  run**, whether or not this change touched it (`:252-270`, loop at `:265-269`); new JS files are
  checked against hard limits only (`JS_HARD_LIMITS`, `:237`).
* `RATCHET_METRICS = [max_func_loc, max_class_loc, max_methods, max_cc, max_cog, max_nest,
  max_params]` (`:174-176`) — the comment at `:171-173` is explicit: *"file_lines/func_count are
  recorded but not enforced"*. `ratchet_growth` (`:296-311`) only iterates `RATCHET_METRICS`.
* Function size is the **span** `end_lineno - lineno + 1` (`node_loc:437-444`), so a symbol with
  zero headroom can still grow *within* an existing line.
* Per-symbol legacy verdicts: an unknown symbol in a baselined file is "new code" and must meet the
  hard limits (`legacy_verdict:849-…`, `funcs` map recorded per file).
* `--record-baseline` refresh is integrator-only and "the commit that runs it must say why"
  (`:761-812`); RULE 16 §16.5 forbids grandfathering growth.

⇒ **Rule of thumb for this wave:** Python files may gain lines and functions (no maximum may grow,
hard limits apply to every new symbol); **every edit to an existing `.js` file must be net-zero in
lines and function count** — registry entries go onto existing lines, new behaviour goes into new
files. HTML/CSS are outside both lanes (`all_js_files` = `app/ui/web/**/*.js`, `:178-179`), so markup
and styles are the free surface for the new window.

### 6.1 Headroom table (verified against `tools/quality_baseline.json` at `6bbaf8b`)

| File | Binding maxima | Symbol spans that matter | Planned delta |
|---|---|---|---|
| `app/core/layout_service.py` | func_loc **21**, cc 9, nest **4**, lines 300 | `default_grid_tree` **21** (0 headroom) | leaf added **on an existing line**; window table extracted to a new `app/core/window_catalog.py` ⇒ lines 300 → ~272 |
| `app/core/models.py` | class_loc 74, func_loc 28, cc 3 | `UrlRow` 8 fields | `receiver: bool = False` (+1 line, lines 292 → 293) |
| `app/ui/services/arena_serialize.py` | func_loc **23** | `urls_to_js` 14, `settings_to_js` **23** (0) | `urls_to_js` +1 line (14→15); `settings_to_js` untouched |
| `app/ui/services/undo_entries.py` | func_loc 17 | `url_rows_from_js` 11, `arena_url_rows_from_js` 8 | +1 line each (12 / 9) |
| `app/ui/panels/app_settings.py` | func_loc **18**, methods 10, cc 7 | `save_settings` **16** | +1 line (17) + new module-level `apply_url_interval` (~7 LOC, new symbol ≤ 30) |
| `app/ui/panels/layout_state.py` | func_loc 19, methods 14 | `emit_arena_state` 10 | +1 line (11): `prog["live"] = live_view(bridge)` |
| `app/ui/panels/run_control.py` | func_loc 19, methods 10 | `reset_image_state` 8, `reset_all` 9, `reset_image` 11 | parameter deleted; two call sites lose an arg ⇒ net **0** lines |
| `app/ui/panels/page_pool.py` | func_loc 16, params 4 | `connect_page_pool` 13 | L-1: one word + one import line |
| `app/browser/output_wait.py` | func_loc 23, cc 8, nest 3, params 4 | `_check_timeout` 11, `WaitSpec` dataclass 4 | +1 dataclass field, `_check_timeout` line **replaced**, new `_paused_elapsed` (~4 LOC) ⇒ lines 211 → ~216 |
| `app/browser/cdp_arena/output.py` | func_loc **16** | `_run_wait` **14**, `_security_gate` 10, `_map_wait_result` 10 | `_run_wait` +1 (15), `_security_gate` +2 (12), `_map_wait_result` +1 (11) ⇒ lines 182 → ~187 |
| `app/services/captcha/service.py` | func_loc **27** | `_manual_wait` **27** (0), `_resolve_captcha` 8, `handle_captcha` 20 | `_resolve_captcha` +1 (9) taking the reason from policy; `_manual_wait` **untouched** |
| `app/persistence/config_manager.py` | class_loc 44, func_loc 13 | `DEFAULT_SESSION` (module dict) | +1 key line (124 → 125) |
| `app/services/auto_connect.py` | **coverage 100 %**, nest **4**, cc 9 | `enabled_tab_ids` 7 | **untouched** (read-only reuse) |
| JS `sash-core/constants.js` | 25 lines / 3 funcs / func_loc **22** (all 0) | IIFE 22 | window entry appended **to an existing line**, `VERSION: 6` on the same return line ⇒ net **0** |
| JS `sash-grid-windows/store.js` | 122 lines / 19 funcs / func_loc **14** (0) | `_collectPanels` 14 | `live_debug: 'winLiveDebug'` appended **to an existing map line** ⇒ net **0** |
| JS `arena-app.js` | 176 lines / 28 funcs | `_PANEL_INITS` is a module const | `'LiveDebugPanel'` appended to the last array line ⇒ net **0** |
| JS `url-list/render.js` | 74 lines / 12 funcs | `rowHtml` (one-line template) | receiver icon **inside** the template line ⇒ net **0** |
| JS `panels/page-pool/*` + `page-pool.js` | 43/119/134/32 lines | — | **untouched** (the rescued markup keeps every element id) |
| JS `arena-app/listeners.js` | 168 lines / 51 funcs | `_handlePagePool` 4 | **untouched** — the new panel self-connects (precedent `arena-presets.js:39-48`) |
| JS `panels/settings.js` | 252 lines / 48 funcs | — | **untouched** — the interval control lives in the new window |
| JS `panels/cdp.js` | 135 lines / 55 funcs | — | round-1 deletion of the 15 s interval (135 → 134) |

---

## 7. Environment (unchanged from round 1)

* No `.venv`, no `node_modules`; `pytest`, `radon`, `coverage`, `cognitive-complexity` are **not
  installed** (`python3 -m pip --version` → pip 23.0.1, Python 3.11; `node` v22 present) ⇒ **no gate
  can run in this checkout as-is**. Bootstrap first:
  `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt radon vulture coverage
  cognitive-complexity && npm ci`, then `bash tools/pre_push_check.sh`.
* `npm run test:js` is an explicit list of 25 `.mjs` files (`package.json` → `scripts["test:js"]`)
  ⇒ a new JS test file must be **added to that list** (package.json is outside both ratchet lanes).
* Duplication floor: `tools/jscpd_baseline.json` → 1.240 % (fail-lane on growth).
* Coverage floors: global line 86.09 / branch 82.01 (`tools/quality_baseline.json` → `coverage`),
  plus per-file floors for every file touched (listed in `quality-budget.md` §3).
* At planning time the round-1 docs are present but **uncommitted** in this sandbox (the earlier
  commit object is gone from the clone); both rounds' docs are committed together with this plan.

---

## 8. Dependency facts that fix the stage order (rev 2 — `design.md` §9, D-24)

Each row is a *verified* reason why a stage cannot move earlier, or why it must move first.

| Order claim | Fact + evidence |
|---|---|
| **S1 first** (L-1) | The reconciler's tab join is `LiveDeps.join_tab` = `do_connect_page_pool` (round-1 `design.md` §5.1), reached through the slot whose scheduler call does not exist (`app/ui/panels/page_pool.py:147`); the worker list every later stage displays is the pool snapshot, emitted only from `app/ui/bridge.py:100-108` over `self._page_pool`. A stage that joins tabs or shows workers is untestable end-to-end until this one word is fixed |
| **S2 before S3** | The OFF guarantee of the pause is *structural*: the settler is installed only when captcha is in scope (`app/services/single_job_runner.py:249`, round-1 D-1), so S3's clock cannot charge when the Watcher is OFF. The cap value, the wait-deadline and the reason wording all read the same predicate module (`app/services/captcha/policy.py`), and the key check that separates "solving" from "manual" lives at `app/ui/panels/watcher_solver.py:127-136` / `app/services/captcha/service.py:242-249` |
| **S3 is self-contained** | Everything it touches is the wait loop: `app/browser/output_wait.py:150-160,189-211` and `app/browser/cdp_arena/output.py:115-125,161-174,127-136`. It needs nothing from `app/services/live/` (which does not exist yet), so the captcha fixes can ship before the larger live-loop work |
| **S4 before S5/S6/S7/S9** | The wake event and the write funnel (`commit_queue`) are what the supervisor plans from and what the reconciler commits through; the single eligibility rule replaces the two clones (`app/ui/panels/queue_scan.py:28-31` ≡ `app/services/batch_orchestrator.py:374-377`) that S5's `plan_pass` and S9's `next_queued` both read. Without S4, "reset re-queues" (D-6R) would have no wake to ride |
| **S5 before S9's run state** | `AppState.run_state` is persisted and serialized but never written by the run lifecycle (L-2: `app/core/models.py:244,260`, patched only at emit in `app/ui/panels/layout_state.py:44`); D-8's single writer (S5) is what makes the debug window's run-state line true instead of permanently `idle` |
| **S6 before S7** | Rows are Python-owned and every mutation ends in `commit_urls` (I-37), and the receiver rule is the conjunction of the existing run gate (`app/services/auto_connect.py:203-209`) with pool presence (`app/browser/page_pool.py:191-197`). `mark_receivers` must be called by the *single* row writer — the reconcile pass — or the flag goes stale between passes |
| **S6's control needs its own new JS file** | The job-cycle bar's existing knobs are bound in frozen `app/ui/web/js/panels/url-list/listeners.js:31` (`urlCooldownSaveBtn` → `facade.saveCooldownConfig()`) with logic in frozen `url-list/cooldown.js` (49 lines / 9 funcs) and `url-list/actions.js:126-156` (163 / 36) — none may grow a line. A new `url-list/interval.js` binding its **own** ids via `Boot.bindOnceById` (`app/ui/web/js/core/boot.js:66-68`) plus a net-zero `'UrlInterval'` append to `_PANEL_INITS` (`app/ui/web/js/arena-app.js:30-34`) is the only ratchet-legal shape |
| **S8 is independent of S2…S7 but prerequisite for S9** | The registry chain (evidence §5.1) and the `replaceChildren` destruction (§5.2) involve no run/captcha/URL code; migration of stored layouts is automatic on both sides (`app/core/layout_service.py:283-297`, `app/ui/web/js/sash-core/validate.js:100-142`), so no earlier stage has to know about the 16th window |
| **S9 last** | It reads what the others produce: `page_pool_updated` workers (S1 makes tabs join, S8 makes them visible), `progress_updated.live.queued`/`next_image` (S4), `.run_state` (S5), `.url_interval_ms`/`.last_pass_at` (S6), `.receivers` (S7) — and it mounts in the window S8 registers. Its panel self-connects (precedent `app/ui/web/js/panels/arena-presets.js:39-48`; bridge exists before panels init, `arena-app.js:167-173`), so frozen `arena-app/listeners.js` (168 lines / 51 funcs) is never touched |
| **D-24a (a stage's new JS files must be complete inside it)** | `record_baseline(refresh=False)` "keeps every recorded maximum (only NEW files/symbols are added — the ratchet never loosens by itself)" (`tools/verify_quality.py:762-812`, JS branch `:807-812`): the moment an integrator records after a stage, that stage's new `.js` files are baselined, and from then on **any** +1 line in them fails (`:265-269`) |
| **The JS lane is global, not per-change** | `check_js(js_files, baseline)` calls `js_maxima(js_files)`, which runs `node tools/js_metrics.js` over the **whole** `app/ui/web` tree and returns per-file maxima for every file (`:201-234`); the passed list is only an on/off switch (`:1032-1034`). So a stage that touches one `.js` file is accountable for every baselined `.js` file's `file_lines`/`func_count` |
| **Two stages edit the same frozen line — and commute** | S6 appends `'UrlInterval'` and S9 appends `'LiveDebugPanel'` to the same last line of `_PANEL_INITS` (`arena-app.js:30-34`). Both are net-zero appends to a data list, so they compose in either order; the ledger in `quality-budget.md` §3.2 keeps the file at 176 lines / 28 funcs after both |
| **CSS is the free surface, but named honestly** | Neither lane covers CSS (`all_js_files` = `app/ui/web/**/*.js`, `:178-179`), so S7 puts `.url-not-receiver` in the existing `css/arena.css` (S7 runs before the window exists) and S8/S9 create `css/live-debug.css` for the window's own strips |

---

## 9. Interface-level research (rev 3 — what forced D-25, D-26, D-27)

Everything below was measured in this checkout at `6bbaf8b` with the gate's **own** code
(`tools/verify_quality.py` imported as a module: `node_loc`, `current_maxima`, `compute_cc_simple`,
`get_nesting_depth`, `effective_params`) so the numbers are the numbers the gate will compare against.
`radon` is not installed here, so CC comes from the AST fallback — re-measure after S0's
`pip install -r requirements.txt`; `current_maxima(Path('app/browser/output_wait.py'))` reproduces the
baseline exactly (23/4/0/8/0/3/4, 211 lines, 17 functions), which is the evidence that the fallback and
the baseline agree.

### 9.1 The ratchet, precisely (this is what makes "small edit" a measured claim)

* `RATCHET_METRICS = max_func_loc, max_class_loc, max_methods, max_cc, max_cog, max_nest, max_params`
  — **any growth fails**, even in an already-baselined file (`verify_quality.py:171-175`, `:296-309`).
* `file_lines` and `func_count` are recorded but **not** enforced for Python (`:171-175`); for JS they
  **are** enforced globally whenever any `.js` changes (`:252-270`, `:1032-1034`).
* ⇒ the legal move in a tight Python file is always *extract into a new symbol or a new file*, never
  *add a branch*; and in JS it is *same-line edits or a new file*.
* Full-tree re-measure of all 222 baseline entries at `6bbaf8b`: **0 breaches** on the seven enforced
  maxima. Two **soft** drifts only: `single_job_runner.py` recorded 902 lines / 76 functions vs actual
  **939 / 79**, `undo_entries.py` 404 vs **406**. Any doc quoting `file_lines` must say recorded-vs-actual
  (`quality-budget.md` §3.1 corrected).

### 9.2 Class spans that decide *where a class may live* (`node_loc`, exact)

| Class | File | Span | File `max_class_loc` | Consequence |
|---|---|---:|---:|---|
| `WaitSpec` | `browser/output_wait.py:23-27` | **3** | 4 | `+1` field ⇒ 4 = **at** the max (legal, no headroom left) |
| `LoopState` | `browser/output_wait.py:29-33` | **4** | 4 | `+1` field ⇒ 5 = **breach** |
| `UrlRow` | `core/models.py:13-21` | **26** | 74 | `+receiver` ⇒ 27, plenty of room |
| `PageInfo` | `browser/page_status.py:28-47` (+ `to_dict`) | **79** | 79 | **zero** headroom ⇒ S9 adds no field (it needs none: `current_image` exists) |
| `CaptchaSignal` | `captcha/signals.py` | 44 | 44 | docstring-only edits |
| `SolveOutcome` | `captcha/signals.py` | 22 | 44 | `+wait_reason`? — not needed (the status string carries it) |
| `PollContext` / `cdp_arena.WaitSpec` | `cdp_arena/output.py`, `cdp_arena/mixins.py` | 5 / 7 | 7 / 9 | `pause=` must ride an **existing** field line |
| `AppSettings` / `AppState` / `JobRecord` / `ImageItem` / `PageStatus` / `JobRequest` | various | 33 / 74 / 42 / 41 / 8 / 7 | all ≥ their span | no growth needed anywhere in this chain |

**⇒ D-25:** a new `PauseClock` class cannot live in `output_wait.py` (any new class there is ≥ 5 lines
of body and the file's `max_class_loc` is 4), and it cannot ride `LoopState`. `WaitSpec.pause` is the
only carrier, and the clock itself becomes `app/core/pause_clock.py`.

### 9.3 Function-level measurements for every symbol a stage edits

The full 25-file table is `tdd-interfaces.md` §D. The four that changed the design:

| Symbol | loc | CC | nest | params | File maxima | Verdict |
|---|---:|---:|---:|---:|---|---|
| `captcha/service.handle_captcha:210` | 21 | **7** | 1 | 2 | CC **7** = file max | an added `if not in_scope: return` ⇒ CC 8 = breach ⇒ **D-26** split into a 4-line entry + `_handle_captcha_scoped` |
| `cdp_arena/output._security_gate:115-125` | 10 | **4** | **1** | 3 | CC **4**, nest **1** = file maxima | in-function charging double-breaches ⇒ **extract** `_settle_timed(settler, clock)` |
| `cdp_arena/output._map_wait_result:127-136` | 10 | 3 | 1 | **4** | params **4** = file max | ⇒ `(cdp, result, spec)` (4→3) **and** a `_timeout_text()` helper (no second branch in a CC-4 file) |
| `browser/output_wait.wait_for_new_output_with_spec:189-211` | **23** | **8** | **3** | **4** | all four = file maxima | **untouchable** — the clock rides `WaitSpec`, the loop body never changes |
| `app_settings.load_arena_preset:326-344` | **18** | 5 | 2 | 1 | loc **18** = file max | S6's interval applier must be a **new module function**, not a line inside it (`save_settings` 16 → 17 ≤ 18 ✓) |
| `cooldown_service.wait_captcha_cleared` | 18 | 7 | 2 | **4** | params **4** = file max | the cap composes into the caller's `stop` (`policy.WaitDeadline`) — module untouched, `test_cooldown_service.py:604-618` stays green |
| `browser/page_pool.PagePool.add_page` | 23 | **10** | 3 | 2 | CC **10** = RULE 16 hard limit **and** all file maxima | `PagePool` is untouchable in every stage (S4/S6/S9 only read it) |
| `panels/queue_scan.RunControlMixin` / `panels/run_control.RunControlMixin` | — | — | **10 methods** | — | `max_methods` **10** = file max | S4's `commit_queue` funnel adds **module-level** functions only, never a mixin method |
| `panels/browser_tabs.report_auto_plan` | 12 | **7** | 2 | 2 | CC **7** = file max | S6 moves the pass body to `live/reconcile.reconcile_once` (a *new* file) instead of growing it |

### 9.4 The three test-integrity defects (D-27)

* **L-6 — the test doubles the seam it tests.** `tests/test_panel_browser_tabs.py:82,156,168,180,211`
  does `panel._schedule_coro = queued.append`, i.e. it replaces the panel's scheduler, so the tests pass
  while the production call `page_pool.py:147 self._schedule_coro(...)` is broken (`AttributeError` on a
  real host — L-1). S1 deletes the double and spies on the real
  `run_state.schedule_coro:194` (`monkeypatch.setattr` + a recording wrapper), keeping all five
  expectations meaningful.
* **L-7 — two JS tests exist but never run.** `package.json`'s `test:js` is an explicit list of
  **25** `.mjs` files while **30** exist on disk: three are harnesses/helpers (`fake_dom.mjs`,
  `sash_harness.mjs`, `user_layout.mjs` — correctly unlisted) and **two are real test files**
  (`test_captcha_saved_page.mjs`, `test_title_fit.mjs`) that no command runs, so a green gate says
  nothing about them — including the 96 px title-bar invariant that S8's 16th window must satisfy
  (`test_title_fit.mjs:107` iterates every window). S10 adopts them
  (→ 30) only if both are green; otherwise the reason is recorded in `QUALITY_RECHECK.md`.
* **L-8 — a dead registry that has already drifted.** `sash-grid.js:41-49` defines `WIN_ICONS` with
  one hit repo-wide (dead), and its key set already disagrees with `WINDOW_IDS`. S8 **deletes** it
  (−9 lines, so the JS `file_lines` ratchet moves down) instead of adding a `live_debug` entry to a
  table nobody reads.

### 9.5 Characterization-harness facts that decide S2 and S5

> **S2 LANDED (2026-09-20):** the S2-relevant facts below are now proven by code — the armed
> golden (`test_captcha_pause_resume`, `watcher_on=True`) stayed byte-identical exactly because
> `FakeCtrl` dialog polls never touch `FakeCDP.evaluate`. Status marker only; S5 still pending.

* `tests/characterization/harness.py:105-121` `build_bridge` constructs a **real** `Bridge` + real
  `ConfigManager` and calls `cfg.set_state(action_blocks=…)` — it never arms the Watcher ⇒ **S2 must add
  a `watcher_on: bool = False` parameter** and `test_captcha_pause_resume.py` must pass `True`; with the
  default `False` the 12 goldens stay **byte-identical** (`check_golden:181-192`, `UPDATE_GOLDENS=1`).
* `collect_trace:158-172` includes `run_state` read from `bridge._run_state`, and `check_golden`
  excludes **logs** ⇒ new log lines are free, but any change to *who writes* `_run_state` drifts the
  goldens. **S5 therefore swaps `RUNNERS:208` to `live.supervisor.run_live` and arms `arm_hooks:211-231`
  (`_stop_after`)** in the same commit as the move.
* Pinned markers: `"Starting"`, `"Job completed"`, `"Batch complete"`, `"Completed with warnings"`,
  `"Prompt verification failed: Mismatch"` (`test_batch_goldens.py:37,47,81`;
  `test_captcha_pause_resume.py:124-132`) — `"Batch complete"` must still be emitted when a run is
  stopped by `_stop_after`, so the supervisor's stop path has to finish the pass.
* No golden contains the string `"Timeout"` ⇒ S3's new timeout wording cannot break one.
* `tests/fakes/cdp_stub_server.py` (129 lines) + `install_patches` (`characterization/fakes.py:196`)
  already stub `wait_for_new_output` wholesale (`fakes.py:125-135`) ⇒ S3's tests need their **own**
  real-loop harness (`test_output_wait_timeout_pause.py` drives `wait_for_new_output_with_spec`
  directly against the stub server), not the golden harness.

### 9.6 UI/JS facts that fix S6-S9 shapes

* **No settings getter slot exists** (`app/ui/panels/app_settings.py` exposes `set_theme`, `set_prompt`,
  `save_settings`, preset import/export/list/save/load/delete, `refresh_users`) and D-20 forbids adding
  one ⇒ the interval control can only *write* through `save_settings` and *read* through the pushed
  `progress_updated.live` payload. That is why `layout_state.emit_arena_state:38-47` (loc 10 · CC 2 ·
  params 1, file max 19) gains exactly one line in S6: `prog["live"] = debug_view.cadence(bridge)`, and
  S9 swaps that same line to `debug_view.live_view(bridge)` (zero growth).
* `url-list/listeners.js:25-40` `bind()` is **15 lines = the file's `max_func_loc`**, and `:31` shows the
  self-binding precedent (`urlCooldownSaveBtn` binds its own id) ⇒ D-12R's control **must** be a new
  file (`url-list/interval.js`, ~60 LOC, modelled on `cooldown.js` 48 LOC / 9 funcs) — there is no legal
  place to add a listener inside `listeners.js`.
* `web/css/arena.css` is **945 lines** and already linked at `index.html:13` ⇒ S7's `.url-not-receiver`
  rule needs no new `<link>`; S8/S9's `live-debug.css` does (one link, ungated — CSS is outside both
  ratchet lanes; `index.html:7-14` lists the stylesheets).
* `arena-app.js:29-34` `_PANEL_INITS` (17 names) is a single multi-line list whose **file** is frozen at
  176 lines / 28 functions ⇒ S6's `'UrlInterval'` and S8's `'LiveDebugPanel'` are both *same-line*
  appends and they commute (no ordering conflict between stages).
* `watcher_solver.solver_start:128-137` is the in-repo precedent for an idempotent loop start through
  `schedule_coro` ⇒ S6's `start_reconciler` copies that shape (start once, `ensure_bg_loop` handles a
  missing loop), called from `main_window._build_ui` (`:48-55`, +1 line; `main_window.py` has
  `max_methods` **10** = file max, so no new method there either).
* JS metrics are **unavailable** in this checkout (`acorn` missing without `npm ci`; the lane prints
  "acorn not installed" and skips) ⇒ `tools/quality_baseline.json`'s JS numbers are authoritative for
  planning, and S0's `npm ci` is what makes them checkable.
