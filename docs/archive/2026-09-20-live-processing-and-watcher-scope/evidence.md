# Evidence — what the code does today (2026-09-20)

Step 1–2 of RULE 16.6 (understand fully, then research). Every claim carries `file:line`.
Companion docs: [`design.md`](design.md) (what to build) · [`quality-budget.md`](quality-budget.md) (RULE 16/18 numbers).

> Chronology note: written 2026-09-20 (git `6bbaf8b`). `docs/current/SYSTEM_OF_RECORD.md`
> carries a later internal stamp (2026-10-05); this plan is written against **that** state and
> supersedes it for the four areas below.

---

## 1. Feature 01 — captcha work is unconditional today

### 1.1 The four pipeline detection sites (none of them checks the Watcher)

| # | Site | Code | Runs when Watcher OFF? |
|---|---|---|---|
| 1 | `CHECK_SECURITY` block | `app/services/single_job_runner.py:402` `_handle_security` → probes `is_security_dialog_visible()` itself, emits `"Security dialog visible — solving or waiting"`, then `check_security` | **yes** |
| 2 | after `SUBMIT` | `app/services/single_job_runner.py:465` `await check_security(ctx)` | **yes** |
| 3 | before `DOWNLOAD` | `app/services/single_job_runner.py:489` `await check_security(ctx)` | **yes** |
| 4 | inside every generation poll | `app/services/single_job_runner.py:249` installs `ctx.ctrl.security_settler`; `app/browser/cdp_arena/output.py:115` `_security_gate` (called per poll at `:161`) evaluates `is_security_dialog_visible` on **each poll** and calls `_settle_and_note` (`single_job_runner.py:265`) | **yes** |

All four funnel into `check_security` (`single_job_runner.py:107`) → `_run_security_captcha`
(`:88`) → `handle_captcha` (`app/services/captcha/service.py:210`).

### 1.2 What one detection writes (all of it, even with the Watcher OFF)

`app/services/captcha/service.py:210-232` + `:246-283` (line numbers verified against `6bbaf8b`):

| Effect | Line |
|---|---|
| log `🛡️ Captcha detected (kind, sitekey=…) via check-security` | `service.py:218` |
| pool row flipped to `waiting_captcha` (red) + `_emit_pool_status` | `service.py:216` → `:97` `_mark_waiting` |
| stats counter `detected` (+ per-site) in `config/captcha_stats.json` | `service.py:217` |
| session recording started under `config/captcha_recordings/<id>/` | `service.py:220` |
| log `🛡️ FLAG CAPTCHA_WAITING — … awaiting your solve in Chrome` | `service.py:255` |
| page overlay `wait for user. Captcha` + amber WHY line | `service.py:257` |
| log `⏰ Captcha wait Ns/300s — still waiting` every 5 s, up to `watcher_captcha_timeout_sec` | `app/services/cooldown_service.py:446-463` (line at `:462`) |
| cooldown penalty stacked (+15 min default) exactly once per cleared edge | `service.py:272` → `cooldown_service.py:373` |
| log `🧾 CAPTCHA_SOLVE {json}` | `service.py:184` |
| log `🧾 CAPTCHA_JOB {json}` at job end | `single_job_runner.py:916-931` (line at `:928`) |
| stats counter `manual_solved` | `service.py:271` |

### 1.3 The only watcher-awareness that exists is *wording*

`service.py:242-249` `_watcher_running(ctx)` reads `bridge._captcha_watcher.running` and is used
**only** to pick the amber reason line (`:236-238`) and the `method` label `"watcher" | "manual"`
(`:273`). Nothing gates detection, logging, stats, recording or penalty.

**Root cause of the complaint:** the gate is missing, not mis-worded. Detection is a pipeline
behaviour; the Watcher switch (`app/ui/panels/watcher_captcha.py:154/170`, config key
`watcher_enabled`) only drives the *passive* watcher loop and `solver_follow`
(`app/ui/panels/watcher_solver.py:143`).

### 1.4 The two loops that are already correctly scoped (no change needed)

| Loop | Start condition | Logs |
|---|---|---|
| Passive watcher `WatcherService` | `watcher_enabled` → `update_config` starts/stops (`app/services/watcher.py:47-53`) | `🛡️ Watcher: Captcha detected …` (`app/services/watcher_pkg/handlers.py:33`) — only when ON |
| Captcha Watcher (SDK solver) | `solver_start` requires a stored key (`watcher_solver.py:126-136`) | `🛡️ Captcha Watcher ON/OFF`, `🤖 … solving`, `✅/❌` (`app/services/captcha_watcher/watcher.py:139/159/105/112`) |

### 1.5 Rules this collides with

* RULE 20 (`docs/current/AGENT_RULES.md:479-503`): *"Default (OFF): do not bypass/defeat/solve
  CAPTCHA — pause with `USER_ACTION_REQUIRED`, let the user solve manually."*
* I-19 (`SYSTEM_OF_RECORD.md:147`) and I-34 (`:161`): the pipeline is **wait-only** by contract.
* `tests/test_captcha_service.py` pins wait-only + fail-open + penalty-once (15 `handle_captcha`
  calls on bridges with **no** `_captcha_watcher` attribute).

→ Turning detection off when the switch is off is a **rule amendment**, not a bugfix: RULE 20,
I-19 and I-34 must be amended in the same change (RULE 17).

---

## 2. Feature 02 — URL rows are snapshot-bound and prune only while idle

| Fact | Code |
|---|---|
| The only periodic scan is a **JS** timer: 15 s (+ once at 4 s) | `app/ui/web/js/panels/cdp.js:32-33` → slot `auto_connect_scan` |
| Manual scans: Reparse buttons | `app/ui/web/js/panels/url-list/actions.js:111`, `cdp/cdp-actions.js:118` |
| Scan body: fetch tabs → dedupe → plan → apply → pool-join → presence → report | `app/ui/panels/browser_tabs.py:374-387` `auto_scan_pass` |
| **Pruning is refused while a run is live** | `browser_tabs.py:359-363` `auto_prune_allowed` (`_run_state != "idle"` → False) |
| Pruning also needs a non-empty tab list (a failed fetch never wipes rows) | `browser_tabs.py:362`, `app/services/auto_connect.py:143` `sync_pool_presence` ("never deletes") |
| Removal today = *linked row whose tab vanished* only | `auto_connect.py:117` `prunable_row_ids` |
| Rows are added only for tabs matching `url_pattern`; **existing rows are never re-checked against the pattern** | `auto_connect.py:126-141` `plan_auto_connect` |
| Unlinked (user-typed) rows are never removed, never expire | `auto_connect.py:117-124` (only `tab_id` rows are prunable) |
| A returning tab gets a **fresh** row (`enabled=True` default) — the old checkbox/state is lost | `app/ui/panels/url_queue.py:75-83` `_add_missing_rows` → `UrlRow.create` |
| The run snapshots rows once per batch | `app/services/batch_orchestrator.py:414-421` `prepare_batch` (`urls`, `allowed`, `tab_id` frozen into `BatchCtx`) |
| Parallel dispatch snapshots `allowed` once per batch, re-derives per image **from the same snapshot** | `multi_page_dispatcher.py:349`, `:275`, `:161` |
| Row writes have one funnel (persist + emit + undo) | `url_queue.py:118-127` `commit_urls` (I-37) |
| Auto-scan deliberately skips undo ("system action, reproducible by re-scan") | `browser_tabs.py:319-336` `apply_auto_plan` |

**Consequence:** a URL row can only be added/removed at a scan boundary, removals are blocked for
the whole duration of a run, and a live run keeps using the rows it snapshotted at start — exactly
the three things feature 02 asks to remove.

---

## 3. Feature 03 — the run is one pass and always ends itself

| Fact | Code |
|---|---|
| `start_run` gates → `_run_state="running"` → schedules `run_batch` | `app/ui/panels/run_control.py:222-240` |
| `run_batch` → prepare → parallel? → cooldown gate → sequential → tail | `batch_orchestrator.py:485-492`, `:452-460` |
| **Six** places write `_run_state="idle"` (run ends itself) | `batch_orchestrator.py:341` `_finish_batch`, `:360` `_abort_no_tab`, `:445` `_await_batch_gate`, `:468` `_cancel_batch`, `:480` `_crash_batch`, `multi_page_dispatcher.py:393` `_finalize_batch` |
| Images are a **snapshot list** taken once per batch | `batch_orchestrator.py:398-401` `_selected_images` → `ctx.images`, iterated at `:349` |
| "No usable tab" **ends the run** | `batch_orchestrator.py:161-166` `_claim_tab` → `"stop"`; `:357-361` `_abort_no_tab` |
| All tabs cooling → `wait_for_batch_ready` waits, but a cancel/timeout ends the batch | `batch_orchestrator.py:437-450` |
| `start_run` while running refuses (`⚠ Already running`) | `run_control.py:78-80` |
| Stop paths: `cancel_current` (immediate + cancels the future + fails `processing`), `stop_after_current` (flag, break after this image) | `run_control.py:255-275`, `batch_orchestrator.py:127-136` |
| Cancel relies on a **stringly-typed** coroutine-name check | `app/services/run_state.py:118-125` `_track_batch_future` (`co_name == "run_batch"`), pinned by `tests/test_run_state.py:51-55` |
| `_run_state` (bridge attr) and `AppState.run_state` (persisted/serialized) are **two different values**; only the bridge attr is written | `run_control.py:229`, `app/core/models.py:244`, `app/ui/services/arena_serialize.py:85`, `app/ui/panels/layout_state.py:44` |
| `RunState` enum exists but the code writes raw strings, and `"stopping"` ≠ enum `"stopping_after_current"` | `app/core/enums.py:57-64` vs `run_control.py:259` |

---

## 4. Feature 04 — queue changes are invisible until the next Start

| Fact | Code |
|---|---|
| `reset_image` / `reset_all` set `selected=False` → a reset image is **not** eligible | `run_control.py:44-51` `reset_image_state(img, False)`, `:203-210`, `:222-228` |
| Eligibility = `selected AND status ∈ (pending, failed, selected, needs_review, processing)` — **duplicated** in two modules | `app/ui/panels/queue_scan.py:28-31` `selected_images` and `batch_orchestrator.py:398-401` `_selected_images` (jscpd-visible clone) |
| `retry_failed` / `retry_image` do set `selected=True`, but nothing re-plans a finished batch | `run_control.py:26-34`, `:190-201`, `:212-220` |
| Queue mutations repeat a 3-line tail (`recalculate_progress` + `_save_arena` + `push_queue_undo`) in 8 slots, with **no wake** | `run_control.py:186-189/199/208/219/227`, `queue_scan.py:281-284/290-293`, `:100-108`, `:118-126` |
| Scans run off the UI thread and write `state.images` while a batch may be iterating it | `queue_scan.py:63-70` `run_off_ui_thread`, `:96-108` |
| Nothing serialises queue access between the Qt thread and the bg loop; saves are atomic per file but reads are unsynchronised | `app/core/persistence.py:24-45`, `app/ui/panels/layout_state.py:28-34` |
| Folder `_AI` disk ops are refused for the whole run (`"stop the run first"`) — permanent once the run never ends | `queue_scan.py:129-133` |
| `processing` is in the eligibility set (crash-recovery intent) → a live re-read could double-dispatch an in-flight image | `queue_scan.py:29-31`, claim happens later at `batch_orchestrator.py:203-211` `mark_processing` / `multi_page_dispatcher.py:159-166` |

---

## 5. Frozen contracts this work must respect

| Contract | Where | Impact |
|---|---|---|
| **134 slots, exact set, exact per-panel packing** | `tests/test_bridge_slots.py:78-236` (`FROZEN_SLOTS`, `EXPECTED_PACKING`, `sum == 134`) | No new/renamed slots without a deliberate contract update |
| **Per-file ratchet** — growth of `max_func_loc / max_class_loc / max_methods / max_cc / max_cog / max_nest / max_params` fails even in legacy files | `tools/verify_quality.py:170-176`, `:296-311`; numbers in `tools/quality_baseline.json` | `RunControlMixin` (10 methods), `UrlQueueMixin` (11), `QueueScanMixin` (10), `BrowserTabsMixin` (7) **cannot gain methods**; new Bridge surface must live in new files |
| **JS ratchet also covers `file_lines` + `func_count`** | `tools/verify_quality.py:265-269` | JS edits may only shrink; new JS goes into new (unbaselined) files |
| **Per-file coverage floors** (e.g. `auto_connect.py` 100.0 %, `url_queue.py` 96.88 %, `batch_orchestrator.py` 92.51 %) + global floor line 86.09 / branch 82.01 | `tools/quality_baseline.json` (`coverage` key + per-file `coverage`) | New code inside a baselined file must be tested to that file's floor |
| **Duplication floor 1.240 %** (fails on growth) | `tools/jscpd_baseline.json` | The two eligibility clones must be merged, not tripled |
| **Characterization goldens** (12 scenarios, `run_state` in the trace) | `tests/characterization/harness.py:203-208`, `goldens/*.json` | An always-live loop never terminates → the harness must arm a stop; `run_state` must still read `idle` at the end |
| **Log strings pinned by tests** | `"No usable checked tab left"` (`tests/test_batch_orchestrator.py:171`), `"Batch complete"` (`:321`, goldens markers `:37/:47`), `"Parallel batch complete"` (`tests/test_multi_page_dispatcher_run.py:234`) | Keep these for a *finished* run; add new wording only for the live tail |
| **I-33 URL-row ownership** (one live tab ↔ one row; auto-connect is the sole binder; checked rows gate runs) | `SYSTEM_OF_RECORD.md:171`, `auto_connect.py:149-266` | The reconciler inherits this invariant; it may not re-bind rows to foreign tabs |
| **I-37 URL rows are Python-owned** (every mutation ends in `commit_urls`) | `SYSTEM_OF_RECORD.md:164` | Reconciler writes must go through the same funnel |

---

## 6. Environment (gates cannot run as-is in this checkout)

* No `.venv`, no `node_modules`; `pytest`/`radon`/`coverage` are **not installed**
  (`python3 -m pip --version` → pip 23.0.1, python 3.11; `node` v22 present).
* Bootstrap before any gate: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
  radon vulture coverage cognitive-complexity && npm ci` (`docs/current/CODE_VERIFICATION.md:16-24`).
* `.venv/`, `node_modules/`, `coverage.json`, `.coverage` are git-ignored ✓ (`.gitignore:5,42-44`).

---

## 7. Latent defects found while researching (fix candidates, not caused by this plan)

| # | Defect | Evidence | User-visible effect |
|---|---|---|---|
| **L-1** | `connect_page_pool` calls `self._schedule_coro(...)`, but **no Bridge has that attribute** — every other panel uses the module-level `schedule_coro(self, coro)` from `app.services.run_state` | `app/ui/panels/page_pool.py:147` vs `browser_tabs.py:480/491/501/509/522/533/544`, `cdp_tools.py:266/282/289`, `run_control.py:235`; no `def _schedule_coro` anywhere in `app/`; tests pass only because their fake bridges inject `_schedule_coro=` (`tests/test_panel_browser_tabs.py:82,156,168,180,211`) | Page Pool → *Add tab* raises `AttributeError`, is swallowed by the slot's `except`, and returns `{"ok": false, "error": "'Bridge' object has no attribute '_schedule_coro'"}` — the tab never joins the pool. One-word fix (`schedule_coro(self, …)`), same LOC |
| **L-2** | `AppState.run_state` is persisted and serialized but never written by the run lifecycle (only `bridge._run_state` is) | `app/core/models.py:244,260,290`, `app/ui/services/arena_serialize.py:85` vs `run_control.py:229` | `get_arena_state`/`arena_state_updated` always report `run_state: "idle"`; only the `progress_updated` payload is patched at emit time (`layout_state.py:44`). RULE 13 tension — fixed by D-8 |
| **L-3** | `RunState` enum values are not the values in use (`"stopping"` vs `STOPPING_AFTER_CURRENT = "stopping_after_current"`) | `app/core/enums.py:57-64` vs `run_control.py:259` | Cosmetic today; a trap for anyone reading the enum as the contract |
| **L-4** | The eligibility rule exists twice (clone pair) | `queue_scan.py:28-31` ≡ `batch_orchestrator.py:398-401` | Duplication-floor pressure; the two can drift (they already differ in intent: UI scope vs run scope) |
