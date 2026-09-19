# System of Record — Arena Image Processor (New App)

This document is the **single source of truth for what the system actually does today**. Everything else in `docs/` is either historical (`docs/archive/`) or derived.

* **Agent rules** (detailed quality gates, behaviours): [`AGENT_RULES.md`](AGENT_RULES.md)
* **Living selector reference**: [`DOM_SELECTORS.md`](DOM_SELECTORS.md)
* **Doc map**: [`../README.md`](../README.md)
* **Workflow diagram**: [`../workflow_diagram.md`](../workflow_diagram.md) (historical but kept)
* **Implementation plan**: [`../implementation_plan.md`](../implementation_plan.md)

---

## 1. What this is

A desktop (PyQt6) app that **processes a folder of images through one or more user-authorized arena.ai URLs**. It reuses the modern dark-mode UI system from Old App (sash-grid draggable windows, win-grip drag indicator, splittable/mergeable/resizable sashes, dock minimized, windows menu, Grid view menu layouts default/A/B/C + Reset, Window presets save/load/import/export with preview, persistence `grid_layout+window_states+window_preset_store` in `config/session.json`).

No DB — JSON only (`config/arena.json`, `config/urls.json`, `config/session.json`, `config/undo.json`). Persists progress so work can resume.

It:

* accepts **multiple URLs** with validation / reachability / auth / readiness checks,
* **scans a folder recursively**, ignoring `*_AI` suffix and filtering by supported types,
* tracks queue states **pending / selected / processing / completed / skipped / failed**,
* allows manual **include / exclude / retry / reset**,
* connects to **already opened Chrome debug port** (user decides port and `--user-data-dir`, e.g. `chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\arena-images-chrome"`),
* for each selected image: **attach image** to webpage via `DOM.setFileInputFiles`, **copy prompt + unique [JOB-ID] token**, **submit once**, **wait new output** (baseline vs new), **verify**, **download highest-quality**, **validate**, **save `*_AI.ext` atomically beside source**,
* shows **rect overlay N seconds** configurable saved in preset JSON for every clicked element (visual confirmation from Old App),
* restores **stacking jobs / Action Blocks** system from Old App: click on btn, click on text areas, visual confirmations that see images or see waiting process on page.

**Never** bypass CAPTCHA, never guess-click, never leave partial file.

---

## 2. Current behaviour (authoritative)

| # | Capability | Current truth |
|---|---|---|
| 1 | **URL list** | List of URLs user pastes. Each validated: syntax, reachability via CDP, auth (not sign-in page), readiness (textarea + send button visible, no security dialog). Status: `unchecked / valid / invalid / unreachable / auth_required / not_ready`. Manual include/exclude. Persisted in `config/urls.json` + `config/session.json`. |
| 2 | **Folder picker** | Folder recursively scanned. Supported types from `settings.supported_types` (default png,jpg,jpeg,webp). Ignore pattern `*_AI.*` (configurable `settings.ignore_suffix`). Scan returns `found` list, `ignored` count, `unsupported` count. RULE 6: only passing filter persisted. |
| 3 | **Image queue** | Table with thumb/path/selected/processing/URL/attempts/output/error. States: `pending` (discovered, not selected), `selected` (queued for run), `processing` (current), `completed` (saved *_AI), `skipped` (user deselected or failed permanently), `failed` (attempt failed, can retry). Attempts counted per image. Manual include/exclude/retry/reset. |
| 4 | **Bulk controls** | Select All / Deselect All / Select Failed / Select Pending / Invert. All go through undo service (RULE 12). |
| 5 | **Prompt editor** | Textarea for base prompt, preview of final prompt `[JOB-ID: <unique>]\n<base>`. Token preview updates live. Persisted in `config/arena.json` + `session.json`. |
| 6 | **Run controls** | Start / Pause / Resume / Stop after current / Cancel / Retry failed. State machine 00-22 (see §3). Stop honoured inside inner waits (RULE 7). Submit button handling improved 2026-09-16: primary `button[aria-label="Send message"]:not([disabled])` + fallback list comma-separated, extra 0.8s delay + wait for enabled (React), multiple click dispatch methods. |
| 7 | **Progress + log** | Progress bar, stats (total/selected/completed/failed/skipped), log console with levels. Each job emits `job_started`, `job_action_status` (with rect), `job_finished`, `progress_updated`. |
| 8 | **Settings** | Supported types, ignore suffix, highlight duration, confirm pause, max attempts, download timeout, CDP host/port, Chrome user-data-dir, prompt, job-cycle/cooldown (min pause + captcha penalty + rate-limit penalty minutes). One control per decision (RULE 10). (2Captcha controls live in their own window — see row 19 `captcha`.) |
| 9 | **Action Blocks stack** | 19 block types restored from Old App, adapted for Arena: `CUSTOM_FIND` (generic find & click — click on btn/text areas), `OBSERVE_BASELINE`, `CHECK_SECURITY`, `HIGHLIGHT_ATTACH`, `ATTACH_IMAGE`, `VERIFY_ATTACHMENT`, `HIGHLIGHT_PROMPT`, `TYPE_PROMPT`, `INSERT_PROMPT`, `VERIFY_PROMPT`, `HIGHLIGHT_SUBMIT`, `SUBMIT`, `WAIT_OUTPUT`, `DOWNLOAD`, `VALIDATE`, `SAVE`, `ADVANCE`, `PAUSE`, `HIGHLIGHT` (pure visual). Each has `enabled`, `selector`, `label_selector`, `match_text`, `match_mode`, `click_enabled`, `click_selector`, `fallback_selector`, `fallback_text`, `highlight_enabled`, `color`, `timeout_ms`, `required`, `custom_name`, `pre_delay_ms`, `highlight_ms`, `confirm_pause_ms`, `highlight_duration_ms` (legacy alias), `extra`. Plain instance attributes (RULE 3) round-trip via `to_dict()`. Order drag-drop with win-grip `drag_indicator`, enable toggle, config panel per block (Tune panel with labels), double-click highlight, custom Find & Click presets chips (save/load), full-stack presets chips below (Save stores the stack, click loads it), Export asks for a target folder first, separate jobs view with rectangles confirmations as it makes clicks. Undoable via `action_blocks` kind. Visual runner RED find → pause → ORANGE click, GREEN collect, BLUE prompt, YELLOW submit, all `pointer-events:none`, stash `__arenaStash`, durations configurable per block saved in preset JSON. |
| 10 | **Visual confirmation** | Rect overlay N seconds configurable, saved in preset JSON. Colour: RED find, ORANGE click, GREEN collect, BLUE prompt, GREEN attach, YELLOW submit. `pointer-events:none`, never intercepts. From Old App's tested system. |
| 11 | **CDP connection** | User starts Chrome: `C:\Program Files\Google\Chrome\Application\chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\arena-images-chrome"`. App connects via `ws://127.0.0.1:9222/json`. `CDPClient` with `asyncio.Lock` to prevent concurrent connect race (fixed). Tab matching: best match by URL, shows connection status per URL. Reuse check + debounce. Auto-connect: scan on start + every 15 s adds/links URL rows for tabs matching `url_pattern` (settings, default `arena.ai`), pool-joins them, flags stale tabs; identity is CDP target id, duplicate URLs get own rows — but **one live tab ↔ at most one row** (I-33): the scan repairs legacy N-rows-per-tab state first (`dedupe_linked_rows`, keeps first enabled, logs removals) and never adds a row for a tab some row already owns. Reparse buttons (URL win + header) rescan immediately and prune dead linked rows when idle; Popup tabs fronts live tabs via CDP + raises their OS windows. Primary tab auto-connects to the first live pool tab with a passive 500ms retry while down. Command replies are delivered with the owning asyncio/qasync loop's thread-safe scheduler, never by mutating a Future from the websocket thread. |
| 12 | **Security / CAPTCHA** | **Isolation contract (2026-10-02): the job pipeline never solves a captcha; the Captcha Watcher (`app/services/captcha_watcher/`) is the only solver, it uses only the official 2Captcha SDK (`2captcha-python`, `AsyncTwoCaptcha`), and it runs only while the Watcher is ON.** Detection is unchanged and verified against real page states: the gate predicate `is_security_dialog_visible` (`app/browser/captcha_js/visible.js`) and the detect probe (`captcha_js/detect.js`) are badge-aware — an open dialog with "Security Verification" / "Protected by reCAPTCHA" / reCAPTCHA iframe / `recaptcha-v2-container` is a challenge; the always-present `.grecaptcha-badge` (own `size=invisible` anchor iframe, a DIFFERENT sitekey) never starts the flow; the v2 predicate requires real on-screen geometry (the badge is `position:fixed; visibility:hidden; right:-186px` in the normal state). **Pipeline (wait-only):** one choke point `handle_captcha(CaptchaCtx)` (call sites: CHECK_SECURITY block, submit/download boundaries, gen-wait cycles via the `security_settler` gate, dispatcher path) runs detect probe → stats → red `waiting_captcha` pool row + overlay `wait for user. Captcha` whose amber WHY line says who is expected to clear it ("Captcha Watcher is solving it (2Captcha SDK)" when the loop runs, otherwise "solve in Chrome — or turn the Watcher ON to auto-solve") + log flag `🛡️ FLAG CAPTCHA_WAITING` → `wait_captcha_cleared` (stop-honoured, `watcher_captcha_timeout_sec`) → cooldown penalty recorded exactly once per cleared edge → one `CAPTCHA_SOLVE` JSON line per encounter (task/token fields empty; `method` = `watcher` | `manual`) + `CAPTCHA_JOB` join at job end. The pipeline never evaluates `inject.js`, never talks to 2Captcha, never clicks "Continue" (`solver.py`, `api_client.py`, `continue_click.js` removed). Post-settle / spinner-loss generation revival (`captcha/recovery.py`) is unchanged. **Watcher solver:** `CaptchaWatcher.run_forever()` on the bridge bg loop (`schedule_coro`), tick every 4 s over the page-pool pages only (app-owned tabs, RULE 20): `detect.js` per tab → visible + kind ∈ {recaptcha_v2, recaptcha_enterprise} + sitekey → `SdkSolver.solve` (`recaptcha(sitekey, url, version="v2", enterprise, invisible)`) → `inject.js(token, sitekey)` (every `g-recaptcha-response` field + real callback chain `data-callback` → `___grecaptcha_cfg` → anchor `cb=`); guards: 8 s eval timeout per page, max 2 paid attempts per tab per encounter (budget resets when the challenge disappears), one solve at a time, every failure fails open into `last_error` + a log line; tokens are counted never logged. The Watcher window switch (`start_watcher`/`stop_watcher`/`set_watcher_config`, and boot with Watcher ON) drives both the passive observer (overlay + job pause) and the solver via `solver_follow`; no key → "Watcher ON, solving disabled" warning, never a paid task. The pipeline's wait ends the same way whoever clears the dialog. Design + deviations: `docs/archive/2026-10-02-captcha-watcher-isolation/design.md`; detection research: `docs/archive/2026-09-18-captcha-detection-verification/design.md`. |
| 13 | **Correlation token** | `generate_correlation_id()` → `[JOB-ID: <unique>]`. Final prompt built via `build_final_prompt()`. Insertion verified by reading back textarea value. Token persisted in job history for traceability (RULE 22). |
| 14 | **Output detection** | Baseline capture before submit: `OBSERVE_BASELINE` stores `srcs` of existing `div.no-scrollbar img[src*=".r2.cloudflarestorage.com/"]` + spinner state. After submit, `WAIT_OUTPUT` understands spinner `div.animate-spin` (user HTML: `<div class="flex min-w-0 flex-1 items-center gap-2"><div class="h-5 w-5 flex-shrink-0 animate-spin"><canvas></canvas></div><span class="truncate">Response A</span></div>`) as generating indicator — waits for spinner to appear (Response A/B) then disappear + new `img` not in baseline, waits for `complete && naturalWidth>0`, prefers largest `naturalWidth`. GREEN rect on new output. Fixed 2026-09-16 after user report. |
| 15 | **Download + validate** | `DOWNLOAD` fetches highest-quality src via CDP `fetch` with credentials include + CORS, fallback to canvas `toDataURL` if CORS tainted (handles `TypeError: Failed to fetch` reported 2026-09-16 "Download failed: Fetch failed {ok: False, 'error': 'TypeEr"). Retries 3x, validates not HTML, valid image via PIL. If fails, job failed, no save. |
| 16 | **Atomic save** | `SAVE` writes via `get_output_path()` (beside source, `_AI` suffix, unique if exists unless overwrite flag) + `atomic_write_bytes()` (temp file + replace). Never partial file (RULE 23). Output files on filesystem, not in JSON (RULE 14). |
| 17 | **Undo system** | One global history (RULE 12) for kinds `grid`, `urls`, `folder`, `queue`, `prompt`, `settings`, `window_states`, `arena`, `action_blocks`. 100 cap, truncate-on-branch, persisted in `config/session.json` + `config/undo.json`. Automatic engine side-effects (marking completed) NOT recorded. |
| 18 | **Presets** | Arena presets: `config/arena.json` stores `prompt`, `action_blocks`, `settings`. Window presets: `grid_layout`, `window_states`, `window_preset_store` in `config/session.json` — save/load/import/export with preview, from Old App system. Save→load round-trips the portable doc (load is a pure getter; preview → confirm → apply flow) and invalid layouts are rejected with an error, never default-substituted (fix 2026-09-18). All UI parameters storable, rect duration saved in preset JSON. |
| 19 | **Modern UI** | Dark-mode variables.css reused. Sash-grid draggable windows via win-grip drag_indicator, splittable/mergeable/resizable sashes, dock minimized, windows menu, Grid view menu layouts default/A/B/C + Reset. 15 windows: `url_list`, `folder`, `queue`, `prompt`, `run`, `progress`, `watcher`, `log`, `settings`, `captcha`, `captcha_records`, `browser`, `action_blocks`, `block_config`, `arena_presets`. The `captcha` window ("Captcha — Watcher solver (2Captcha SDK)", 2026-10-02) is the solver surface: API key (masked display `abcd****7890` only, raw key never echoed back, field cleared after save — `set_captcha_api_key`/`get_captcha_api_key`), Watcher ON/OFF title-bar buttons (same switch as the Watcher window), live solver badge + status line fed by the `captcha_watcher_status` signal (`watcher_status` slot: running / has_key / sdk_available / last_error / balance), Balance (`captcha_balance`, SDK `balance()`), counters (detected + cleared-while-waiting from the pipeline stats, solved-by-Watcher / Watcher-failed / pages-scanned from the loop). There is no "enable auto-solve" toggle any more — Watcher ON is the only way the app solves. Existing persisted layouts self-migrate to include it (missing leaf appended, `SashCore.migrate`). Sash visibility is ONE rule, ONE writer (`_syncSashes()`, called from `_applyStates()` and the MutationObserver): a sash is hidden iff its previous (left/top) sibling is hidden — closed/minimized window or an emptied split. A divider drag resizes only its two adjacent VISIBLE rows (the sash's left row + the next visible row); hidden rows keep their stored sizes and no other row moves (commit math: visible px → `100 − Σhidden` budget). Fixes + root causes: `docs/archive/2026-09-17-watcher-grid-bugfixes/`. Title-bar invariant: ─/✕ controls are ALWAYS fully visible at the right edge in any window width — title text truncates (`span.win-name`, ellipsis), secondary title items (Save/Clear/Reparse buttons, count badges) are dropped right-to-left by the single-writer `_fitTitleBars()` (one of them hidden = `fit-hidden` class) while the row overflows, and the fixed core (grip+icon+controls+gaps+padding) is < the 96px minimum window; the fitter runs on every state change, mid-drag, and app resize. Fixes + root causes: `docs/archive/2026-09-17-titlebar-controls-visibility/`. |
| 20 | **Persistence** | JSON only, no DB. `config/arena.json` (prompt + blocks + settings), `config/urls.json` (url list + status), `config/session.json` (grid_layout + window_states + preset_store + undo_history + queue + folder + selected + cooldown keys), `config/undo.json` (full undo stack), `config/cooldowns.json` (wall-clock timers + per-URL job counters, runtime-only, git-ignored), `config/2captcha.json` (2Captcha key: api_key + solve_timeout_sec, `enabled` kept for shape compatibility but inert — git-ignored, 0600 best-effort, NEVER in arena.json/session.json so presets never carry the key; single owner `CaptchaKeyStore`, read by the Watcher solver), `config/captcha_stats.json` (captcha counters + per-site + last balance/error — git-ignored). Atomic writes, validated on load, never brick on corrupt JSON (RULE 13). |
| 21 | **Job cycle & cooldown** | After each job the tab auto-clicks New Chat (`a[href="/image/direct"]`, visual runner RED→ORANGE), waits for full load (readyState + page ready + empty composer), then cools down per-tab: user-set minimum (default 5 min, `cooldown_min_seconds`) + stacked captcha penalty (default +15 min each, `cooldown_captcha_penalty_seconds`, this tab only) + stacked rate-limit penalty (default +30 min, `cooldown_rate_limit_penalty_seconds`, this tab only) applied when a job fails on a rate/limit/quota banner (`is_rate_limit_error` → `maybe_note_rate_limit` at both the single- and parallel-mode failure sites, so the tab cools base+penalty instead of base alone; a repeated rate-limit stacks another cycle — self-terminating back-off; `0` disables it). Tab is `steady` (ready) only after its countdown ends; pool UI shows live MM:SS + reset/edit per row; URL List win likewise (correction 2026-09-16): pause/penalty bar in win, live countdown + reset/edit on each URL row matched to its pool tab, one shared image queue; cancel skips cooldown. Each URL row is bound to its tab by auto-connect alone (`UrlRow.tab_id`, set on scan add/claim or the run-start rescue claim of a checked unlinked row, I-33) so the row always shows its own tab's timer even when same-site twins tie on URL match; runs record the tab's own row but **never re-bind rows** (the legacy round-robin re-link stole rows and spawned phantom rows — `docs/archive/2026-09-18-url-row-tab-ownership/design.md`). The row checkbox is the "use for job" gate: single mode, tab-resolve, and parallel dispatch only pick tabs owned by checked rows (`enabled_tab_ids` + `resolve_primary_tab(allowed)` + `_acquire_free_in`); Start refuses with an actionable message when nothing checked owns a live tab. The finish log prints the breakdown (`total = base + captcha xN`, or `base + extra (captcha xN, rate-limit xM)` when a rate-limit penalty stacked). Captcha is also waited + recorded at submit/download boundaries. Load balancing: each finished job increments the tab's persistent counter and the next job goes to the free tab with the lowest count (ties keep pool order); Jobs column shows the counter. Design: `docs/archive/2026-09-16-job-cooldown/design.md` + `correction-url-list.md`; rate-limit penalty: `docs/archive/2026-09-19-rate-limit-penalty/design.md`. Silent-miss diagnosis: `fix-persist-silent-miss.md`. |
| 22 | **Captcha session recording** | Every visible captcha encounter on a CDP-backed tab starts a bounded local recording after detection and ends on solved/manual/error/stale/stopped/interrupted resolution. It writes an atomic manifest, append-only timestamped DOM mutation and sanitized network lifecycle events, capped textual response bodies, and gzip sanitized DOM checkpoints under git-ignored `config/captcha_recordings/<session-id>/`; session count is under user control — the Records window lists every retained session (up to 1000 rows, exact total in the title bar) with a per-row delete (confirm dialog) — while a 512 MiB disk-safety cap still prunes the oldest as a last resort. URL queries, headers, form values, scripts, credentials, and opaque tokens are not persisted. The `recordings` window (renamed from `captcha_records`; stored layouts migrate through `LEGACY_WINDOW_IDS`) lists method/outcome/timing/counts, lets the user explicitly label ground truth `unknown`, `bot`, `manual` or `mixed`, and loads any two sessions into bounded side-by-side event-timeline (offset_ms + event detail fields) and latest-DOM (checkpoint timestamp) panes matching the persisted schema; labels are never inferred. Recorder errors fail open and cannot alter captcha handling. Since Area D (2026-09-19) it also keeps a **bounded, token-free milestone timeline** (`milestones.py`: `task_created, token_ready, injected, page_error, dialog_cleared, acceptance_candidate, auto_finished, final`, every string ≤200 chars, `assert_token_free` backstop — a token-shaped value skips the milestone rather than half-writing it; the comparison pane always surfaces milestones even when the 200-event tail dropped them), reports **`dropped_events`** in the manifest (network events lost after close are counted, never silently discarded), and carries an **outcome label independent of the actor** (`result_label ∈ unknown/passed/failed`, `label_history`, `cohort()` actor×result matrix whose success rate uses only passed/failed, comparison served by `RecordingManager.compare_sessions`; the Records viewer shows Actor and Result as two columns, and session ids are validated by `is_valid_session_id` so `delete_session('..')` can no longer reach the parent folder). Design: `docs/archive/2026-09-18-captcha-session-recording/design.md` + `docs/archive/2026-09-18-captcha-bot-failure-analysis/verification-and-problem-diagnostic.md` + `docs/archive/2026-09-19-area-d-implementation/design.md` (D1–D3). |

---

## 3. State machine (00-22) — Arena adaptation

Old App had 00-22 for virt-chat. New App maps to image processing:

| State | Meaning |
|---|---|
| 00 | Idle — no folder, no URLs |
| 01 | URLs added, unchecked |
| 02 | URLs validating (reachability check) |
| 03 | URLs validated — at least one valid & ready |
| 04 | Folder selected, scanning |
| 05 | Scan complete — images discovered (pending) |
| 06 | Images selected — queue ready |
| 07 | Connecting to Chrome debug port |
| 08 | CDP connected, tab matched |
| 09 | Observing baseline (capturing existing outputs) |
| 10 | Attaching image |
| 11 | Attachment verified |
| 12 | Inserting prompt with [JOB-ID] |
| 13 | Prompt verified |
| 14 | Submitting |
| 15 | Waiting for new output (polling) |
| 16 | New output detected |
| 17 | Downloading |
| 18 | Validating download |
| 19 | Saving atomically |
| 20 | Job completed |
| 21 | Paused (USER_ACTION_REQUIRED or user pause) |
| 22 | Batch finished / stopped / failed |

**Flow:** `00 → 01 → 02 → 03 → 04 → 05 → 06 → 07 → 08 → 09 → 10 → 11 → 12 → 13 → 14 → 15 → 16 → 17 → 18 → 19 → 20 → (next image or 22)`

Any state can go to 21 (pause) and resume, or to 22 (stop).

---

## 4. Core flow — plan → execute (per image)

Adapted from Old App's `cycle_plan` + `process_conversation`, now for Arena image:

1. **User configures**: URLs + folder + prompt + action blocks preset + settings (port, user-data-dir, highlight duration, etc.)
2. **Scan**: `services/folder_scanner.py` `scan_folder_recursive(folder, supported_types, ignore_suffix)` → list of `ImageItem` with `path, name, selected, status, attempts, output_path, error`. Only passing filter persisted (RULE 6). Empty vs broken distinguished (RULE 4): empty folder vs folder not set vs scan failed.
3. **Select**: User selects subset via queue UI (bulk controls). Undoable (RULE 12).
4. **Connect**: `CDPClient.connect()` with lock, reuse check, debounce. `Bridge._do_find_tab()` matches best tab by URL. Shows connection status per URL.
5. **Run batch**: `Bridge._do_run_batch()` loops over selected images:
   - For each image, generate correlation ID `generate_correlation_id()`
   - Build final prompt `build_final_prompt(base_prompt, correlation_id)` → `[JOB-ID: xxx]\n<base>`
   - Execute action blocks stack in order:
     - `CHECK_SECURITY` — detect security dialog, if visible pause with USER_ACTION_REQUIRED (RULE 20)
     - `OBSERVE_BASELINE` — capture baseline srcs via CDP `Runtime.evaluate`
     - `HIGHLIGHT_ATTACH` + `ATTACH_IMAGE` — highlight attach button/input (RED), then `DOM.setFileInputFiles` with absolute path, verify preview appears
     - `VERIFY_ATTACHMENT` — check `div.flex.flex-wrap.gap-2 img` exists
     - `HIGHLIGHT_PROMPT` + `INSERT_PROMPT` — highlight textarea (BLUE), insert final prompt, verify read-back equals expected (RULE 22)
     - `HIGHLIGHT_SUBMIT` + `SUBMIT` — highlight submit (YELLOW), click once, verify processing started (spinner or textarea cleared)
     - `WAIT_OUTPUT` — poll for new output not in baseline, wait for `complete && naturalWidth>0`, GREEN rect on new output
     - `DOWNLOAD` + `VALIDATE` + `SAVE` — download highest-quality src, validate via PIL, atomic save beside source with `_AI` suffix (RULE 23), never overwrite without flag, never partial
   - On success: mark image `completed`, `output_path` set, `attempts++`, persist state atomically
   - On failure: mark `failed` or `skipped`, `error` set, persist, continue to next if not stopped
   - Stop honoured inside inner waits (RULE 7): `should_stop` predicate checked each poll iteration
   - Progress reported incrementally (RULE 5): `job_started`, `job_action_status` per block with rect, `job_finished`, `progress_updated`

6. **Completion**: Batch finishes, stats updated, log shows summary.

---

## 5. Invariants — Arena equivalents of Old App I-1..I-33

| ID | Invariant | Old App equivalent | Enforcement |
|---|---|---|---|
| I-1 | Click never lands on unseen highlighted — overlay `pointer-events:none`, find stash reused for click | I-1 | `dom_highlight.py` + `cdp_arena.py` |
| I-2 | Every step reported — `bridge._log()` + `job_action_status` with rect | I-2 | `Bridge` signals |
| I-3 | Empty vs broken distinct — empty queue vs scan failed vs folder not set vs CDP disconnected | I-3 | `folder_scanner`, `url_validator`, `cdp_client` |
| I-4 | Incremental progress — each image result surfaces as it happens, not batched at end | I-4 | `on_collect` / `job_finished` signal |
| I-5 | Filtered-out must not persist — after scan, `state.images` contains only passing filter (supported types, ignore AI) | I-5 | `folder_scanner.py` + `AppState` |
| I-6 | Stop honoured inside inner waits — `should_stop` checked in `wait_for_new_output` polling, CAPTCHA wait, download | I-6 | `cdp_arena.py` |
| I-7 | Guard skip must not stall downstream — disabled block returns success "Skipped (disabled)", does not block next block | I-7 | `action_blocks.py` + `cdp_arena.py` |
| I-8 | One control per decision — no duplicate settings for same filter | I-8 | `config_manager.py` |
| I-9 | Scan-only vs queue — scan-only mode does observation work but adds nothing to selected set | I-11 | `folder_scanner` |
| I-10 | One global undo timeline — kinds `grid`, `urls`, `folder`, `queue`, `prompt`, `settings`, `window_states`, `arena`, `action_blocks` | I-10 | `UndoService` + `config/session.json` |
| I-11 | Never persist unreadable state — grid layout validated via `canonincal_grid_payload()`, `AppState.load_state()` handles corrupt JSON gracefully | I-11 | `layout_service`, `persistence/app_state` |
| I-12 | Output is not queue — `images` queue may shrink, output files `*_AI.ext` on filesystem never deleted by queue operations | I-12 | RULE 14 |
| I-13 | Two-step verification gate fails closed — baseline + token + validation + atomic save; if any fails, nothing saved, job failed | I-13 | `cdp_arena.py` + `image_saver.py` |
| I-14 | Media filed under source — output saved beside source image, not global pile | I-14 | `image_saver.py` |
| I-15 | Deletion permanent fail-closed — queue delete does not delete *_AI file; only OS delete deletes file | I-15 | `app_state.py` |
| I-16 | Correlation token unique and verified — `generate_correlation_id()` + read-back verification | New | `correlation.py` |
| I-17 | Atomic save — temp file + replace, never partial | New | `image_saver.py` |
| I-18 | Selector priority semantic > structural > class fragment — all selectors in `site_adapter.py` with primary + fallbacks | New | RULE 21 |
| I-19 | Never bypass CAPTCHA — pause with USER_ACTION_REQUIRED, let user solve manually | New | RULE 20 |
| I-20 | User-authorized URLs only — only URLs user explicitly added are used | New | RULE 20 |
| I-21 | Rect overlay N seconds configurable saved in preset JSON | New | `config/arena.json` |
| I-22 | CDP connection with lock — prevents concurrent connect race causing instant disconnect | Fixed bug | `cdp_client.py` `asyncio.Lock` |
| I-23 | Grid layout 11 windows exact set — `url_list`, `folder`, `queue`, `prompt`, `action_blocks`, `run_controls`, `progress`, `log`, `settings`, `cdp`, `help` | Old layout | `layout_service.py` |
| I-24 | Post-generation reset — every finished job clicks New Chat and waits for full page load before the tab can go ready | New | `new_chat.py` + `cooldown_service.finish_page_after_job` |
| I-25 | Cooldown ready-gate — tab shows steady (ready) only after its pause expires; expiry flips COOLDOWN→STEADY in locked reads, UI poll, and wait loops | New | `page_status.try_expire` (single source) |
| I-26 | Per-tab independence — pause, captcha count, and pending penalty live on the tab; tab B never inherits tab A timers | New | `PageInfo` fields + `cooldown_service` |
| I-27 | Captcha stacks, reset is safe — each solved captcha records via `note_captcha_event` (guarded log + persist + live emit); user reset clears the live timer but preserves the running job's stacked debt for its finish; stuck busy/waiting/error frees only when no run is active; live runs refuse with a message | New | `note_captcha_event` / `add_captcha_penalty` / `reset_cooldown` + `force_reset_page` / `edit_cooldown` |
| I-28 | Load balancing — next job goes to the free tab with fewest completed jobs; counters persist per URL and are never pruned | New | `register_job_done` + `_pick_lowest_count` + stats in `cooldown_store` |
| I-29 | 2Captcha key never exposed — raw key lives only in git-ignored `config/2captcha.json` (0600 best-effort); WebChannel/UI carry masked form only; key never in logs, payloads, presets, or error text; solver failures never block the job (the pipeline only waits) | New (2026-09-17), solver moved to the Watcher 2026-10-02 | `CaptchaKeyStore.mask` + `watcher_solver` payloads + RULE 20 amendment |
| I-34 | The job pipeline never solves a captcha — `handle_captcha` is wait-only (detect → pause → penalty); the only solver is `app/services/captcha_watcher` (official SDK), running only while the Watcher is ON, on page-pool tabs only, ≤2 paid attempts per challenge | New (2026-10-02) | `tests/test_captcha_service.py` (never injects), `tests/test_captcha_watcher.py`, `tests/test_watcher_solver_slots.py` |
| I-29 | Run prefers a ready tab — single-mode start and each image re-resolve primary to the best ready pooled tab (lowest jobs); primary reconnects on move; waits only when all tabs cooling; stay/move decisions logged with one-line pool summary, build hash logged at startup | New | `resolve_primary_tab` + `_select_run_tab` + `_pool_summary` |
| I-30 | Page-error fast-fail — wait loop scans alert/toast/error regions each poll; fresh limit/error text aborts the wait so the job finishes FAILED (retryable) instead of stalling to timeout; stale banners ignored via wait-start baseline | New | `app/utils/page_errors.py` + `_poll_output_diag` + `_reraise_abort` |
| I-31 | Per-tab stop + job line — URL rows show the running image (`▶ name`) from pool pushes; Stop button aborts that tab's job (fails as Aborted, batch continues); stuck-reset refuses only while that tab's own job is alive | New | `stop_tab_job` + `request_tab_abort` + `set_tab_image` + `jobLineForTab` |
| I-32 | Captcha recordings are bounded, local, and orthogonal — no headers/form values/raw tokens; recorder failure never changes solve/manual outcome; actor/result labels are user-set ground truth, never inferred | New (2026-09-18) | `captcha_recording` package + dedicated QWebChannel adapter |
| I-32 | Folder _AI ops — toolbar Drop _AI strips the suffix from filenames in the picker folder recursively (`photo_AI_1.png` → `photo_1.png`, never overwrites, collisions skipped); Only _AI deletes all non-_AI images there (confirm dialog); images only, hidden dirs skipped, refused mid-run, queue synced | New | `drop_ai_suffix` + `keep_only_ai_files` + `app/core/folder_ai.py` |
| I-33 | URL-row ownership — one live tab ↔ at most one URL row; auto-connect is the sole owner of the binding (scan add/claim + run-start rescue claim, exact URL only, never steals); runs never re-bind rows to foreign tabs; a tab runs jobs only when a **checked** (enabled) row owns it — gate on start, tab-resolve, and parallel dispatch; scan repairs legacy duplicates (keep first enabled, logged) | New (2026-09-18) | `auto_connect.dedupe_linked_rows` / `enabled_tab_ids` / `claim_unlinked_from_pool` + `resolve_primary_tab(allowed)` + dispatcher `_acquire_free_in` — `docs/archive/2026-09-18-url-row-tab-ownership/design.md` |

---

## 6. Storage map — JSON only, no DB

| File | What it holds | Why |
|---|---|---|
| `config/arena.json` | `prompt`, `action_blocks` (19 types: CUSTOM_FIND generic + 14 original + PAUSE/HIGHLIGHT/TYPE_PROMPT/VERIFY_ATTACHMENT, each with selector/label_selector/match_text/match_mode/click_enabled/click_selector/fallback/highlight_enabled/color/timeout/pre_delay/highlight_ms/confirm_pause_ms), `custom_blocks` (reusable Find & Click presets chips), `settings` (supported_types, ignore_suffix, highlight.duration_seconds, highlight.confirm_pause_ms, highlight.color, max_attempts, download_timeout, cdp_host, cdp_port, user_data_dir) — all UI params storable, rect duration saved in preset JSON | Arena preset store — save/load/import/export with preview, from Old App system |
| `config/urls.json` | `urls: [{url, status, last_checked, error}]` | URL list + validation status |
| `config/session.json` | `grid_layout`, `window_states`, `window_preset_store`, `undo_history`, `folder`, `images` (queue), `selected_ids`, `prompt`, `settings` overrides, `stats` | Session persistence — layout + queue + undo |
| `config/undo.json` | Full undo stack (100 cap) — alternative location, mirrored to session.json | Global undo timeline |
| `config/2captcha.json` | `api_key`, `solve_timeout_sec` (+ inert `enabled`) (git-ignored, 0600 best-effort) | 2Captcha key for the Watcher solver — kept out of arena.json/session.json so presets never carry the key (RULE 20); one owner `CaptchaKeyStore` |
| `config/captcha_stats.json` | `detected_total`, `auto_solved`, `auto_failed`, `manual_solved`, `tasks_created`, `tasks_deleted`, `last_balance`, `balance_at`, `last_error`, `per_site` (≤49 hosts + `*`) | Captcha statistics for the Settings panel — corrupt file → blank, partial file keeps valid fields |
| `config/captcha_recordings/<session-id>/` | `manifest.json`, `events.jsonl`, gzip DOM checkpoints | Local redacted captcha lifecycle evidence; git-ignored, bounded, orphaned active sessions recover as interrupted |
| `config/config.json` | Legacy config (if exists) — migrated to arena.json + urls.json | Backward compat |
| `output/*_AI.ext` | Generated images beside source — `get_output_path()` + `atomic_write_bytes()` | Output files, never in JSON |
| `logs/arena.log` | File log + UI log console | Traceability |
| `reports/` | `CODE_QUALITY_METRICS_*.md`, `coverage.json` | Quality gates |

**Atomic write pattern (same as Old App's DB write, now for JSON):**

```python
tmp = path.with_suffix(".tmp")
tmp.write_bytes(data)
tmp.replace(path)  # atomic on same filesystem
```

**Validation on load (RULE 13):**

```python
try:
    data = json.loads(path.read_text())
    validate(data)  # version, shape, sizes
except (json.JSONDecodeError, ValidationError):
    # reject, leave previously stored state untouched, log warning
    return default
```

---

## 7. Key modules and layers (adapted from Old App)

| Layer | Files | Responsibility | Imports allowed |
|---|---|---|---|
| **core** | `app/core/action_blocks.py`, `correlation.py`, `naming.py`, `image_saver.py`, `layout_service.py`, `folder_ai.py`, `cooldown.py`, `models.py`, `scanner.py`, `persistence.py`, `undo_service.py` | Domain logic, no Qt, no CDP; param objects `OutputSpec`/`ScanSpec`/`JobRequest` | stdlib, PIL |
| **services** | `app/services/captcha_recording/` (recorder + `milestones.py` + `cohort.py`: bounded token-free evidence), `app/services/single_job_runner.py` (875, converged 20-block handler map), `batch_orchestrator.py` (492), `run_state.py` (417: bg-loop/schedule/tab-resolve/cooldown persistence), `cooldown_service.py`, `multi_page_dispatcher.py`, `verification.py`, `watcher.py` + `watcher_pkg/` (passive observer), `captcha/` (wait-only choke point + key store/stats/recovery), `captcha_watcher/` (the ONLY solver: `CaptchaWatcher` loop + `SdkSolver` over `2captcha-python`), `auto_connect.py` | Converged block handlers (one pipeline for sequential + parallel), batch orchestration, run seam, captcha observe/wait vs. Watcher solve, auto-connect | core, browser, stdlib (+ optional `twocaptcha`) |
| **browser** | `app/browser/cdp/` package (transport/connect/tabs/probe/dom + facade), `cdp_arena/` package (controller/highlight/attach/submit/download/output + facade), `dom_highlight.py` + `dom_highlight_js.py`, `output_wait.py` + `output_wait_fallback.py`, `site_adapter.py` + `probe_selectors.py` (RULE 21 single source), `output_probes.py`, `page_pool.py`, `visual_click.py` | CDP connection with lock (I-22), visual runner (RULE 1), selector map (RULE 21), output wait with `WaitSpec`, output probes | core, services, stdlib, websockets |
| **persistence** | `app/persistence/config_manager.py`, `preset_store.py`, `cooldown_store.py`, `undo_store.py`, `json_store.py` (one atomic load/save) | JSON persistence, presets, cooldown store, undo store (RULE 12/13) | core, stdlib |
| **ui-services** | `app/ui/services/arena_serialize.py`, `window_preset_service.py`, `file_service.py`, `folder_ai_service.py`, `scan_service.py`, `thumbnail_service.py`, `undo_entries.py` | Qt-free panel helpers: JS serialization, preset docs, OS reveal/clipboard, folder-AI worker, scan merge, thumbnails, undo rows | core, services, stdlib — never Qt, never panels |
| **ui/panels** | `app/ui/panels/*.py` (12 mixins, 119 `@Slot`) + `app/ui/qt_compat.py` shim | QWebChannel slot surface; slots only, helpers module-level | services, core, browser, qt_compat; acyclic sibling reuse only |
| **ui/root** | `app/ui/bridge.py` (149 lines, 10 methods), `bridge_context.py`, `main_window.py` | `Bridge` = signals + 10 API methods + compat re-exports; construction context; real window owner (only top-level Qt) | panels, ui-services, services, core |
| **pipeline** | `app/services/batch_orchestrator.run_batch` + `single_job_runner.run_blocks_for_image` | Batch lifecycle (prepare/parallel-gate/sequential/finish) + one block-execution pipeline shared with parallel dispatch; state machine 00-22, stop honour (RULE 7), progress (RULE 5) | core, browser, persistence |
| **ui-js-core** | `app/ui/web/js/core/ui-helpers.js` (127) deduped esc/el/chip/sortArrow/mergeParts, `panels/highlight.js` (59) | Shared DOM builders C8 | browser |
| **ui-js-panels** | `panels/action-blocks.js` (319) + `block-store.js` + `block-render.js` + `block-config.js` + `block-listeners.js` + `block-ui.js` (59) + `block-status.js` (96) C12, `panels/watcher.js` (272) C9, `panels/page-pool.js` (240), `panels/arena-presets.js` (55) + `arena-presets/store.js` (73) + `render.js` (105) + `actions.js` (221) C13 v4, `panels/image-queue.js` (~400), `panels/url-list.js` (~435), `sash-grid-windows.js` (499) | Panel facades C7-C13 v4, 3 files >300 remain with ideal-size reason (target ≤3 met) | core/ui-js-core |
| **ui-js-app** | `js/arena-app.js` (134) facade + `arena-app/listeners.js` (158) registry table C13 | App init + 22 bridge listeners via buildRegistry table | ui-js-panels |

**Import direction:** `ui` → `ui-services`/`browser` → `services` → `core` → stdlib. No cycles. Qt enters panels only via `app/ui/qt_compat.py` (single guarded shim); services never import Qt or panels. The 119 JS slot names are frozen (contract §1 item 1; `tests/test_bridge_slots.py` exact-match). Batch runs through `batch_orchestrator.run_batch` (the legacy `bridge._do_run_batch` loop was deleted in A4); run control + `JobAction` events live in `panels/run_control.py`.

---

## 8. Tests — what exists and what must exist (RULE 8)

| Test file | What it tests | Why it matters |
|---|---|---|
| `tests/test_scanner.py` | Folder scan recursive, ignore `*_AI`, supported types, empty vs broken (RULE 4,6) | Scanner correctness |
| `tests/test_naming.py` | `get_output_path()` + unique suffix + atomic write | No overwrite without flag (RULE 23) |
| `tests/test_persistence.py` | `AppState` load/save atomic, corrupt JSON handling (RULE 13), queue persistence | Never brick |
| `tests/test_correlation.py` | `generate_correlation_id()` uniqueness, `build_final_prompt()` | Token verification (RULE 22) |
| `tests/test_state_transitions.py` | State machine 00-22, stop/pause/resume | RULE 7 |
| `tests/test_verification.py` | Baseline capture, new output detection, validation (not HTML, dimensions >0) | RULE 15 |
| `tests/test_selectors.py` | Selector map primary+fallbacks, visibility, count, evidence | RULE 21 + DOM_SELECTORS.md |
| `tests/test_rule16_new_code.py` | Code-quality gates: LOC 30/150, params 4, methods 15, CC 10, cognitive 15, nesting 4, coverage 80%/75% | RULE 16 |
| `tests/js_harness.js` | JS probes against DOM stub (real execution) | RULE 8 |
| `tests/characterization/` (Area A) | 12 batch goldens + harness + fakes: the run pipeline's observable trace (state per block, stop/pause/captcha, fallbacks) | Behaviour lock for the A2/A4 pipeline convergence |
| `tests/test_batch_orchestrator.py`, `tests/test_run_state.py`, `tests/test_single_job_runner.py` | Orchestrator seam, bg-loop/cooldown persistence, converged block handlers | RULE 8 for the run pipeline |
| `tests/test_bridge_slots.py` | Exact 119-slot JS contract + 12-panel packing + direct-method cap | A lost `@Slot` silently kills a QWebChannel call |
| `tests/test_bridge_metaobject.py`, `tests/test_qt_shim_fallback.py` | Panel mixin slots in the Qt metaobject; every panel imports without PySide6 | QWebChannel + headless CI |
| `tests/test_cdp_client_stub.py` + `tests/fakes/cdp_stub_server.py` (Area B) | Real websocket/HTTP round-trips through the cdp package: connect, send/evaluate, DOM attach, highlight, timeouts | Found the PySide6 `disconnect` shadowing regression |
| `tests/test_probe_selectors.py`, `tests/test_action_block_defaults.py` (Area B) | No selector literal outside `site_adapter`; JS default catalog/order mirrors the Python catalog | RULE 21 + RULE 3 |
| `tests/test_verify_quality_tool.py` (Area B) | The gate itself: legacy growth, new symbols, coverage ratchet, honest fallback | RULE 16 must not be gameable |
| `tests/unit/test_json_store.py`, `test_config_manager.py`, `test_preset_store.py`, `test_undo_store.py`, `test_cooldown_store_edges.py`, `test_output_state.py` (Area B) | Persistence dedup + edge cases | RULE 12/13 |
| `tests/test_captcha_milestones.py`, `test_captcha_result_labels.py`, `test_recording_*_full.py`, `test_recorder_full.py` (Area D) | Milestone whitelist + token-free assertion, result labels + cohort, and branch-complete recorder/network/store/retention/reader/manager coverage | I-29/I-32 stay true, not just documented |
| `tests/test_cdp_client.py` + `test_cdp_arena.py` (Area D) | Fake-websocket CDP round trips through the `cdp/` package: connect, send/evaluate, DOM attach, highlight, tab fetch fallback, download fallback | Real protocol behaviour without Chrome |
| `tests/test_quality_gate.py` (Area D) | The gate's own negative tests via `--root`/`--changed-files`: grown function fails, coverage drop fails, 40-LOC JS function fails | RULE 16 must not be gameable, and must actually fire |

**Coverage command (copy-paste, same as Old App adapted):**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m coverage run --branch --source=app -m pytest tests -q
COVERAGE_FILE=.coverage .venv/bin/python -m coverage json -o coverage.json
```

---

## 9. Quality gates summary — same thresholds as Old App (RULE 16)

| Check | Prefer | Fail if | Tool |
|---|---|---|---|
| Function LOC | ≤20 | >30 | AST span |
| Class LOC | ≤120 | >150 | AST span |
| Params | ≤3 | >4 | AST |
| Methods per class | ≤10 | >15 | AST |
| CC | ≤7 | >10 | `radon cc -s` |
| Cognitive | ≤10 | >15 | `cognitive-complexity 1.3.x` |
| Nesting | ≤3 | >4 | custom walker |
| Line coverage | ≥80% | <80% or below baseline | `pytest --cov` |
| Branch coverage | ≥75% | <75% | `coverage json` |

Baseline: `tools/quality_baseline.json` — per-file maxima + per-symbol metrics
+ a coverage floor, refreshed only via `--record-baseline` (integrator step,
commit must say why). Ratchet breaches are never grandfathered: a baselined file
may not grow on any metric even with `--allow-legacy`.

Current floors after Area D: **line 84.46 % / branch 80.27 %** (the absolute
80/75 target is met); duplication floor `tools/jscpd_baseline.json` 1.240 %
(fails on growth). JS lane: hard limits for new symbols (LOC 30 / params 4 /
nesting 4 / CC 10) + ratchet for baselined files. Mutation testing is a separate
non-blocking lane (`tools/mutmut_scope.sh`, scopes in `tools/mutmut_scopes.txt`,
evidence in `docs/archive/2026-09-19-area-d-implementation/d5-mutation.md`) —
RULE 17 evidence, not part of the 3-minute push budget.

Override format: `# quality-override: metric=value reason=...` with metric ∈ `loc, class-loc, params, methods, cc, cognitive, nesting, coverage, vulture, dup`, reason ≥20 chars naming constraint.

Anti-gaming: no `foo_part1/part2`, no `**kwargs` dodge, no dummy helpers, no lambda dispatch to hide `if`.

Remediation order: nesting → cyclomatic → cognitive → size (RULE 19).

---

## 10. History of designs — pointers to archive

* Old App designs: removed from the working tree in R1 (record: `docs/archive/2026-09-19-refactor-cycle-integration/design.md` §7). The virt-chat-specific legacy tree `Process Images in Areana/Old App/**` (948 files, 106 MB) was only reference material for the UI system and the action-blocks idea; the last commit that still contains it is `11e6520`, so any provenance question is answerable with `git show 11e6520:"Process Images in Areana/Old App/README.md"`.
* New App designs: `docs/archive/<YYYY-MM-DD>-<topic>/` — each feature that moved complexity across files gets dated folder with design doc, then rows in this file updated
* `docs/archive/2026-09-16-job-cooldown/design.md` — job cycle & cooldown (New Chat reset, per-tab pause, captcha stacking)
* `docs/archive/2026-09-17-captcha-penalty/solution.md` — captcha-penalty hardening (record choke point, sticky row-tab binding, boundary checks, finish breakdown, reset keeps debt)
* `docs/archive/2026-09-17-2captcha-integration/design.md` + `summary.md` — 2Captcha auto-solve (opt-in, RULE 20 amendment): detect probe → solver (per-tab dedup, poll, inject + verify) → manual fallback; Settings key store (masked-only UI) + statistics; `handle_captcha` choke point for all call sites
* `docs/archive/2026-09-18-captcha-detection-verification/design.md` — detection/solver-payload verification against real page states (badge vs dialog, two sitekeys, `size=` param → `isInvisible`, badge exclusion, real container/text signals)
* `docs/archive/2026-09-18-captcha-visual-await/design.md` — 2nd-round badge false positive: saved-state research (badge `position:fixed; visibility:hidden; right:-186px` ⇒ `offsetParent` non-null in normal state), v2 on-screen geometry predicate, exact-moment CAPTCHA_WAITING/CAPTCHA_AUTO visual flags, Captcha-window policy status line
* `docs/archive/2026-09-18-captcha-why-not-solving/design.md` — "detected but solving was not done": auto-solve is opt-in (default OFF → manual wait by design); watcher overlay now carries the WHY (amber reason line: auto OFF / no sitekey / auto failed) via the dead `elapsed_sec` → `sub` param swap; auto-skip is no longer silent (`⚠️ FLAG CAPTCHA_AUTO skipped`)
* `docs/archive/2026-09-18-captcha-token-callback/design.md` — "dialog still visible after token injection": arena's reCAPTCHA is callback-driven (anchor src `&cb=<name>` → `window[cb](token)` closes the dialog); injection now invokes the callback; wait loop is security-aware (`security_settler` gate) so mid-wait dialogs are settled inline instead of burning the 180 s generation timeout
* `docs/archive/2026-09-18-captcha-delivery-recovery/design.md` — round 5, supersedes the token-callback premise: live logs prove `window[cb]` never exists (anchor `cb=` is recaptcha's internal loader arg, not the site callback) — injection now sets EVERY response field + invokes the real chain `data-callback` → `___grecaptcha_cfg` (sitekey-preferred) → anchor last resort; plus post-settle revival (one bounded prompt re-insert + Send when the blocked generation died)
* `docs/archive/2026-09-18-revival-generalize/design.md` — round 6: no-dialog timeouts (12:08 run) never armed round-5 revival — trigger generalized to spinner loss (seen, then 20 s gone with no pixels), slow starts still safe via the seen-latch
* `docs/archive/2026-09-18-grid-window-set/design.md` — grid persistence: Python window set synced to the JS 14 (incl. `captcha`); invalid layouts rejected with an error (RULE 13), never default-substituted; preset load is a pure getter returning the portable doc for the preview → confirm → apply flow
* `docs/archive/2026-09-18-resubmit-send-ready/design.md` — round 7: resubmit inserts into the VISIBLE composer (error-state DOM hides a first-match textarea) and clicks Send once enabled (`submit_when_ready`, terminal-state diagnostics); resubmit re-attaches a dropped image; in-thread error bubbles (`Trace ID:`) abort the wait fast instead of burning 180 s
* `docs/archive/2026-09-18-solve-observability/design.md` — round 8: solve-pipeline evidence in logs — task id, 30 s poll heartbeats, token fingerprint (shape only, RULE 20) + time-to-token, pre-inject dialog state, provider failure detail; `SolveOutcome` unchanged; fast-fail path proven by test on a second real error sample
* `docs/archive/2026-09-18-too-late-to-solve/design.md` — round 9: 13:14 run proves tokens real-but-late (71 s vs ~60 s page patience); data-first slice — `isInvisible` in the submit line + sequential mid-solve error-appearance timestamps (no behavior change); abort-race vs skip-solving decided after 1–2 runs of histogram data
* `docs/archive/2026-09-18-captcha-reporting/design.md` — round 10: structured reporting — one `CAPTCHA_SOLVE` JSON line per encounter (detection + task + token + edge data, joined by eid) + one `CAPTCHA_JOB` line at image-job end (outcome + page error)
* `docs/archive/2026-09-18-captcha-session-recording/design.md` — bounded redacted DOM/network session recordings, CDP event fan-out, automatic encounter lifecycle, local records window, and user-owned bot/manual labels
* `docs/archive/2026-09-18-captcha-solve-comparison-diagnostic/verification-and-problem-diagnostic.md` — evidence-gated comparison of manual-pass, bot-pass, and bot-fail sessions; confirmed schema/tooling gaps, candidate failure signatures, and fix acceptance criteria
* `docs/archive/2026-09-19-area-c-quality-splits/` — Area C C9-C13 quality refactors per RULE 18 ideal sizes (func 4-20, file 150-300, module 5-15, context 60-200) + RULE 16 gates + AGENT_RULES anti-gaming:
  - C9 watcher: 325→257 LOC file ≤300, class 287→237, split config (47 LOC check_once ≤20) + jobs (30) + overlay (55) modules
  - C10 dom_highlight: 478→329 LOC (-31%) + dom_highlight_js 161 JS payloads package, attach/prompt/submit helpers ≤15 LOC CC≤5, registry table
  - C11 output_wait: 312→223 LOC (-29%) + output_wait_fallback 106, WaitSpec/HighlightSpec param objects, predicate table
  - C12 action-blocks: 435→319 LOC (-27%) + block-ui 59 + block-status 96, block-store/config/render/listeners split, listener registry table
  - C13 arena-app: 332→134+158=292 LOC total (-40), setupBridgeListeners 164 CC66 → 22 helpers CC≤5 + buildRegistry() table + bindBridge() in listeners.js
  - Remaining >300 JS panels (arena-presets 357, image-queue ~400, url-list ~435, sash-grid-windows 499) carry ideal-size reason comments per RULE 18.2 and will be split store/render/actions next round
  - Baseline: 145→151 entries after cognitive-complexity installed, verify_quality --changed --allow-legacy PASSED, JS 117 pass, Py 430 pass (offscreen, bridge excluded)
* C14–C16f finish round (2026-09-19, `docs/archive/2026-09-19-code-quality-implementation-plan/`): C13.2 JS panel splits + C14 ESM c8 + C15 coverage ramp + C16a–e gate sweep; **C16f** closed the increment: dead `_legacy` compat shims deleted (7, zero callers repo-wide), `wait_for_new_output_loop`/`build_highlight_js`/`build_highlight_rect_js` wrappers folded into their spec builders (`wait_for_new_output_with_spec` + `WaitSpec`, `build_highlight_js_from_spec` + `HighlightJsSpec`), `JobRecord.create` takes `JobRequest` spec (5→1 params), `ActionBlock.from_dict` rebuilt on `_DEFN_DEFAULTS`/`_CTOR_RAW`/`_CTOR_FROM_DEFN` tables + `load_stack_from_dicts` split (`_block_from_saved`/`_append_missing_required`), `normalize_grid_tree`→`_normalize_split`, `reconcile_with_filesystem`→`_reconcile_diff`, `undo`→`_undo_to_frontier`, window-state filtering unified as `layout_service.normalize_window_states` (fixes the red `test_window_states_keep_captcha` fake-bridge slot), captcha `_poll_task` retry budget via `_poll_retryable` + `SolvePlan.transient_errors` (cog 16→≤15), RULE 16.1.5 override comments on the 5 single-literal JS probe builders, dead `page_status._is_cooling` import dropped. Full-mode fails 55→29 (remainder = grandfathered legacy only: `BrowserController` class split + `bridge.py` Area A; no ratchet growth), `verify_quality --changed --allow-legacy` PASSED, coverage.json generated (line 45.0% vs 41% baseline), ratchet baseline re-recorded (179 entries incl. per-file coverage), Py 548 pass (0 fail) + JS 135 pass
* `docs/archive/2026-09-18-recaptcha-page-mechanics/research-design.md` — follow-up research/design: CAPTCHA is layered (Enterprise bootstrap, anchor, challenge, response field, callback, page/backend acceptance, generation output); callback + dialog gone is not whole-job success
* `docs/archive/2026-09-18-recaptcha-verification-architecture/design.md` — round 11 architecture: evidence-rich probe, page-error/stale-token terminal outcomes, callback acceptance candidate separated from output completion, no penalty for stale/page-failed attempts
* `docs/archive/2026-10-02-captcha-watcher-isolation/` — **Captcha Watcher isolation + UI bugfixes**: `audit.md` (old solving chain inventory, 5 UI root causes), `design.md` (pipeline wait-only, `captcha_watcher/` SDK-only loop, 6 solver slots, one Watcher switch, kept-on-purpose deviations + follow-ups), `bugfix-verification.md` (boot helpers, URL list, action blocks empty-stack healing, preset id collisions, folder-shape normalisation — each with its pinning test); gate snapshot `docs/current/QUALITY_RECHECK.md`
* `docs/archive/2026-09-18-recaptcha-verification-architecture/implementation-2026-09-18.md` — implemented identity gate: page URL + performance.timeOrigin and bounded challenge-frame identity are re-probed before token injection; mismatch deletes provider task and returns token_stale; `SolveOutcome` carries the lifecycle (polls, token fp, dialog state, inject, mid-solve error)
* Selector research: `docs/selector_map.md` (detailed), `docs/research_summary.md`, `docs/current/DOM_SELECTORS.md` (living reference)
* Workflow: `docs/workflow_diagram.md`, `docs/data_model.md`, `docs/implementation_plan.md`

---

## 11. Current UI — 15 windows

| Window ID | Title | Content | Persisted in |
|---|---|---|---|
| `url_list` | URLs | URL list with status (unchecked/valid/invalid/unreachable/auth_required/not_ready), add/remove, include/exclude | `config/urls.json` + `session.json` |
| `folder` | Folder | Folder picker, recursive scan, stats found/ignored/unsupported, supported types | `session.json` folder + settings |
| `queue` | Queue | Table thumb/path/selected/processing/URL/attempts/output/error, bulk controls | `session.json` images + selected_ids |
| `prompt` | Prompt | Base prompt textarea, token preview `[JOB-ID: xxx]\n<base>`, final prompt | `arena.json` + `session.json` |
| `action_blocks` | Action Blocks | Stack of 19 blocks restored from Old App: CUSTOM_FIND (click on btn/text areas), PAUSE, HIGHLIGHT, TYPE_PROMPT, VERIFY_ATTACHMENT plus 14 original. Drag-drop with drag_indicator win-grip, enable toggle, config panel per block (custom_name/selector/label_selector/match_text/match_mode/click_enabled/click_selector/fallback/highlight_enabled/color/pre_delay/confirm_pause/highlight_ms/timeout), double-click highlight, custom blocks chips save/load, separate jobs view with rectangles confirmations as it makes clicks, rect duration configurable saved in preset JSON, undoable | `arena.json` action_blocks + custom_blocks + session.json |
| `run` | Run | Start/Pause/Resume/Stop after/Cancel/Retry, state machine display 00-22 | ephemeral |
| `progress` | Progress | Progress bar, stats total/selected/completed/failed/skipped, current image | ephemeral + session stats |
| `log` | Log | Log console with levels info/success/warn/error, filter, clear, export | `logs/arena.log` |
| `settings` | Settings | Supported types, ignore suffix, highlight duration, confirm pause, max attempts, download timeout, CDP host/port, user-data-dir | `arena.json` settings |
| `watcher` | Generation Watcher | Generation/captcha passive monitoring and state; its ON/OFF also starts/stops the Captcha Watcher solver | ephemeral |
| `captcha` | Captcha — Watcher solver (2Captcha SDK) | Masked key, Watcher ON/OFF, live solver status + balance, encounter/solve counters | `config/2captcha.json` + `captcha_stats.json` |
| `recordings` (legacy `captcha_records`) | Captcha Session Records | Session list, editable labels, A/B event/DOM evidence comparison, and per-session Open-folder action | `config/captcha_recordings/` |
| `browser` | Browser Preview | Selected/generated image and webpage highlight context | ephemeral |
| `block_config` | Block Config — Security Check | Selected action-block configuration | `arena.json` action blocks |
| `arena_presets` | Arena Presets | Save/load prompt, action-block, and setting combinations | `config/arena.json` |

**Layout:** Sash-grid draggable via win-grip `drag_indicator`, splittable/mergeable/resizable sashes, dock minimized, windows menu, Grid view menu layouts default/A/B/C + Reset, Window presets save/load/import/export with preview. Persistence `grid_layout+window_states+window_preset_store` in `config/session.json`. From Old App, tested. Sash visibility single-rule + "divider touches only adjacent rows" invariants: `docs/archive/2026-09-17-watcher-grid-bugfixes/SOLUTION.md`.

**Dark mode:** `app/ui/web/css/variables.css` reused from Old App — same variables, same dark theme.

---

*Last updated: 2026-10-02 — **Captcha Watcher isolation + UI bugfixes**: the job pipeline is wait-only (never solves), `app/services/captcha_watcher/` is the only solver (official `2captcha-python` SDK, Watcher ON only, page-pool tabs, ≤2 attempts), old `captcha/solver.py` + `api_client.py` removed, Captcha window reworked, 7 new slots (134 frozen); bugfixes: `js/core/boot.js`, URL list listeners/commit path, action-blocks empty-stack healing + `restore_default_blocks`, static preset markup with unique ids, `FolderPickMixin` folder-shape normalisation. Record: [`docs/archive/2026-10-02-captcha-watcher-isolation/`](../archive/2026-10-02-captcha-watcher-isolation/design.md), gates: [`QUALITY_RECHECK.md`](QUALITY_RECHECK.md). Previously — 2026-09-19 **R2 Area D integrated**: captcha-recording milestones + independent result labels + `dropped_events` (D1–D3), 428 new tests and the coverage ramp to **84.47 % line / 80.27 % branch** (D4 — the absolute 80/75 target that was still outstanding), scoped mutation tooling (D5), and the gate-integrity additions `--root`/`--changed-files` + JS hard limits + duplication fail-lane (D6). Record: [`docs/archive/2026-09-19-refactor-cycle-integration/design.md`](../archive/2026-09-19-refactor-cycle-integration/design.md) §8. Previously — **R1 legacy removal**: the study tree `Process Images in Areana/Old App/**` (948 tracked files, 106 MB) is gone from the working tree along with its now-dead `.gitignore` entries; every rule, selector and design it contributed was already ported into `docs/current/` and `app/`, so only the historical pointers above still name it. Previously — **refactor cycle X**: Area A's bridge/panel split (bridge.py 4,592 → 149 lines, 12 panels, exact 119-slot contract) and converged run pipeline (`batch_orchestrator` 492 + `run_state` 417 + one `single_job_runner` used by sequential and parallel lanes) + Area B's dead-code purge (`controller.py`, `job_runner.py`, `output_detector.py`, `job_state_machine.py` deleted), RULE 21 single selector source (`probe_selectors.py`) and `json_store.py` dedup + Area C's `cdp/` + `cdp_arena/` packages, core param objects, JS splits, all on top of R0's gate lanes. Full gate: 0 fails; coverage floor line 68.44 / branch 61.02 (ratchet, absolute 80/75 = D4 target). Integration record: [`docs/archive/2026-09-19-refactor-cycle-integration/design.md`](../archive/2026-09-19-refactor-cycle-integration/design.md).* This file is the current truth — if not true today, it does not belong here (RULE 17). Archive old truth to `docs/archive/<date>-<topic>/`.
