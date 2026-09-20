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
7. The settle itself is unbounded by design (RULE 20): `_settle_and_note:265-271` →
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
  parameter — `:250-251` overlay `sub=reason`).

---

## 3. Item 03 — URL rows, the receiver gate, and reset semantics

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
