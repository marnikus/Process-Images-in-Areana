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
| 8 | **Settings** | Supported types, ignore suffix, highlight duration, confirm pause, max attempts, download timeout, CDP host/port, Chrome user-data-dir, prompt, job-cycle/cooldown (min pause + captcha penalty minutes). One control per decision (RULE 10). (2Captcha controls live in their own window — see row 19 `captcha`.) |
| 9 | **Action Blocks stack** | 19 block types restored from Old App, adapted for Arena: `CUSTOM_FIND` (generic find & click — click on btn/text areas), `OBSERVE_BASELINE`, `CHECK_SECURITY`, `HIGHLIGHT_ATTACH`, `ATTACH_IMAGE`, `VERIFY_ATTACHMENT`, `HIGHLIGHT_PROMPT`, `TYPE_PROMPT`, `INSERT_PROMPT`, `VERIFY_PROMPT`, `HIGHLIGHT_SUBMIT`, `SUBMIT`, `WAIT_OUTPUT`, `DOWNLOAD`, `VALIDATE`, `SAVE`, `ADVANCE`, `PAUSE`, `HIGHLIGHT` (pure visual). Each has `enabled`, `selector`, `label_selector`, `match_text`, `match_mode`, `click_enabled`, `click_selector`, `fallback_selector`, `fallback_text`, `highlight_enabled`, `color`, `timeout_ms`, `required`, `custom_name`, `pre_delay_ms`, `highlight_ms`, `confirm_pause_ms`, `highlight_duration_ms` (legacy alias), `extra`. Plain instance attributes (RULE 3) round-trip via `to_dict()`. Order drag-drop with win-grip `drag_indicator`, enable toggle, config panel per block (Tune panel with labels), double-click highlight, custom Find & Click presets chips (save/load), full-stack presets chips below (Save stores the stack, click loads it), Export asks for a target folder first, separate jobs view with rectangles confirmations as it makes clicks. Undoable via `action_blocks` kind. Visual runner RED find → pause → ORANGE click, GREEN collect, BLUE prompt, YELLOW submit, all `pointer-events:none`, stash `__arenaStash`, durations configurable per block saved in preset JSON. |
| 10 | **Visual confirmation** | Rect overlay N seconds configurable, saved in preset JSON. Colour: RED find, ORANGE click, GREEN collect, BLUE prompt, GREEN attach, YELLOW submit. `pointer-events:none`, never intercepts. From Old App's tested system. |
| 11 | **CDP connection** | User starts Chrome: `C:\Program Files\Google\Chrome\Application\chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\arena-images-chrome"`. App connects via `ws://127.0.0.1:9222/json`. `CDPClient` with `asyncio.Lock` to prevent concurrent connect race (fixed). Tab matching: best match by URL, shows connection status per URL. Reuse check + debounce. Auto-connect: scan on start + every 15 s adds/links URL rows for tabs matching `url_pattern` (settings, default `arena.ai`), pool-joins them, flags stale tabs; identity is CDP target id, duplicate URLs get own rows. Reparse buttons (URL win + header) rescan immediately and prune dead linked rows when idle; Popup tabs fronts live tabs via CDP + raises their OS windows. Primary tab auto-connects to the first live pool tab with a passive 500ms retry while down. |
| 12 | **Security / CAPTCHA** | The gate predicate `is_security_dialog_visible` (`app/browser/captcha_js/visible.js`, both controllers) and the detect probe (`app/browser/captcha_js/detect.js`) are badge-aware: an open dialog with "Security Verification" / "Protected by reCAPTCHA" / reCAPTCHA iframe / `recaptcha-v2-container` is a challenge; the always-present `.grecaptcha-badge` widget (its own `size=invisible` anchor iframe, a DIFFERENT sitekey than the challenge) is on screen in the normal state and never starts the flow; v2 predicate (fix 2026-09-18) additionally requires real on-screen geometry — viewport rect intersection + no `display:none`/`visibility:hidden|collapse` ancestor — because the badge is `position:fixed; visibility:hidden; right:-186px` in the normal state (laid out, so `offsetParent` alone said "on screen"); at the EXACT detection moment the app logs a visual flag — `🛡️ FLAG CAPTCHA_WAITING — captcha on screen (tab …) — awaiting your solve in Chrome` (manual) or `🤖 FLAG CAPTCHA_AUTO — 2Captcha auto-solve started (tab …)` (opt-in auto) — alongside the red `waiting_captcha` pool row + overlay, and the Captcha window status line shows the active policy (auto-solve ON/OFF); the manual-wait overlay shows an amber WHY line (auto-solve OFF / no sitekey in dialog / 2Captcha failed — auto-solve is opt-in, default OFF, so a wait means "solve in Chrome" unless the Captcha window is enabled), and an auto-solve skip is never silent (`⚠️ FLAG CAPTCHA_AUTO skipped`); badge widget on screen never triggers captcha handling / URL `CAPTCHA_REQUIRED`. One choke point `handle_captcha(CaptchaCtx)` (all call sites: CHECK_SECURITY block, submit/download boundaries, gen-wait cycles, dispatcher path) runs: detect probe (extracts kind, dialog-scoped sitekey, `invisible` from iframe `size=` param, page URL) → stats → **optional auto-solve** (opt-in 2Captcha, default OFF per RULE 20 amendment 2026-09-17: docs-exact `createTask` payload — `RecaptchaV2EnterpriseTaskProxyless` + `websiteURL` + `websiteKey` (+`isInvisible` for enterprise), per-tab inflight dedup, poll, token injection = React-safe set of the dialog-scoped `g-recaptcha-response` **AND invocation of the widget's registered global callback** parsed from the dialog anchor iframe src (`&cb=<name>` → `window[cb](token)` — arena closes the dialog / resumes the request from the callback, NOT the textarea; fix 2026-09-18 "dialog still visible after token injection"), + dialog continue click (best effort), 20 s verify-grace with specific failure reasons (callback called → likely server-side rejection / no callback in anchor), any failure falls back to manual) → **security-aware wait loop**: `wait_for_new_output`'s poll passes through `_security_gate()` (optional `security_settler` attribute installed by the job runner) so a dialog appearing MID-WAIT is detected within ~2 s and settled inline (auto-solve or manual wait) instead of the job burning the full generation timeout (fix 2026-09-18) → manual wait (overlay `wait for user. Captcha`, stop-honoured) → cooldown penalty recorded exactly once per solved edge. Captcha solving is per-tab independent and non-blocking across pages. The 2Captcha API flow is trace-logged for debugging (createTask OK → task id + sitekey tail + host; createTask FAILED / getTaskResult FAILED with `reason (errorId=N): message`; poll status transitions; token received + elapsed) and the Captcha window has a **Reset** action that clears cumulative stats + last error (balance survives — it is API state) so stale counters from earlier runs can't be misread as current failures. Verified against real page states 2026-09-18: `docs/archive/2026-09-18-captcha-detection-verification/design.md` (+ `2026-09-17-2captcha-integration/`). |
| 13 | **Correlation token** | `generate_correlation_id()` → `[JOB-ID: <unique>]`. Final prompt built via `build_final_prompt()`. Insertion verified by reading back textarea value. Token persisted in job history for traceability (RULE 22). |
| 14 | **Output detection** | Baseline capture before submit: `OBSERVE_BASELINE` stores `srcs` of existing `div.no-scrollbar img[src*=".r2.cloudflarestorage.com/"]` + spinner state. After submit, `WAIT_OUTPUT` understands spinner `div.animate-spin` (user HTML: `<div class="flex min-w-0 flex-1 items-center gap-2"><div class="h-5 w-5 flex-shrink-0 animate-spin"><canvas></canvas></div><span class="truncate">Response A</span></div>`) as generating indicator — waits for spinner to appear (Response A/B) then disappear + new `img` not in baseline, waits for `complete && naturalWidth>0`, prefers largest `naturalWidth`. GREEN rect on new output. Fixed 2026-09-16 after user report. |
| 15 | **Download + validate** | `DOWNLOAD` fetches highest-quality src via CDP `fetch` with credentials include + CORS, fallback to canvas `toDataURL` if CORS tainted (handles `TypeError: Failed to fetch` reported 2026-09-16 "Download failed: Fetch failed {ok: False, 'error': 'TypeEr"). Retries 3x, validates not HTML, valid image via PIL. If fails, job failed, no save. |
| 16 | **Atomic save** | `SAVE` writes via `get_output_path()` (beside source, `_AI` suffix, unique if exists unless overwrite flag) + `atomic_write_bytes()` (temp file + replace). Never partial file (RULE 23). Output files on filesystem, not in JSON (RULE 14). |
| 17 | **Undo system** | One global history (RULE 12) for kinds `grid`, `urls`, `folder`, `queue`, `prompt`, `settings`, `window_states`, `arena`, `action_blocks`. 100 cap, truncate-on-branch, persisted in `config/session.json` + `config/undo.json`. Automatic engine side-effects (marking completed) NOT recorded. |
| 18 | **Presets** | Arena presets: `config/arena.json` stores `prompt`, `action_blocks`, `settings`. Window presets: `grid_layout`, `window_states`, `window_preset_store` in `config/session.json` — save/load/import/export with preview, from Old App system. All UI parameters storable, rect duration saved in preset JSON. |
| 19 | **Modern UI** | Dark-mode variables.css reused. Sash-grid draggable windows via win-grip drag_indicator, splittable/mergeable/resizable sashes, dock minimized, windows menu, Grid view menu layouts default/A/B/C + Reset. 14 windows: `url_list`, `folder`, `queue`, `prompt`, `run`, `progress`, `watcher`, `log`, `settings`, `captcha`, `browser`, `action_blocks`, `block_config`, `arena_presets`. The `captcha` window ("Captcha — 2Captcha Control") is the 2Captcha config surface: enable toggle, API key (masked display `abcd****7890` only, raw key never echoed back, field cleared after save), solve timeout (minutes, 30–600 s), live balance ($, `getBalance`), statistics (detected / auto-solved / auto-failed / manual / auto success rate / balance) with a Save + ↻ Stats title-bar actions. Existing persisted layouts self-migrate to include it (missing leaf appended, `SashCore.migrate`). Layout persistence: `session.json` (grid_layout + window_states) is the source of truth — the close-time flush is SYNCHRONOUS (`runJavaScript` + QEventLoop, 1.5 s timeout; fire-and-forget used to lose the final layout to teardown), and boot restores under a guard: grid `_save()` is deferred until the async backend restore lands (3 s timeout safety), so a stale backend tree can never be cemented by an early save (fix 2026-09-18). Sash visibility is ONE rule, ONE writer (`_syncSashes()`, called from `_applyStates()` and the MutationObserver): a sash is hidden iff its previous (left/top) sibling is hidden — closed/minimized window or an emptied split. A divider drag resizes only its two adjacent VISIBLE rows (the sash's left row + the next visible row); hidden rows keep their stored sizes and no other row moves (commit math: visible px → `100 − Σhidden` budget). Fixes + root causes: `docs/archive/2026-09-17-watcher-grid-bugfixes/`. Title-bar invariant: ─/✕ controls are ALWAYS fully visible at the right edge in any window width — title text truncates (`span.win-name`, ellipsis), secondary title items (Save/Clear/Reparse buttons, count badges) are dropped right-to-left by the single-writer `_fitTitleBars()` (one of them hidden = `fit-hidden` class) while the row overflows, and the fixed core (grip+icon+controls+gaps+padding) is < the 96px minimum window; the fitter runs on every state change, mid-drag, and app resize. Fixes + root causes: `docs/archive/2026-09-17-titlebar-controls-visibility/`. |
| 20 | **Persistence** | JSON only, no DB. `config/arena.json` (prompt + blocks + settings), `config/urls.json` (url list + status), `config/session.json` (grid_layout + window_states + preset_store + undo_history + queue + folder + selected + cooldown keys), `config/undo.json` (full undo stack), `config/cooldowns.json` (wall-clock timers + per-URL job counters, runtime-only, git-ignored), `config/2captcha.json` (2Captcha settings: enabled + api_key + solve_timeout_sec — git-ignored, 0600 best-effort, NEVER in arena.json/session.json so presets never carry the key), `config/captcha_stats.json` (captcha counters + per-site + last balance/error — git-ignored). Atomic writes, validated on load, never brick on corrupt JSON (RULE 13). |
| 21 | **Job cycle & cooldown** | After each job the tab auto-clicks New Chat (`a[href="/image/direct"]`, visual runner RED→ORANGE), waits for full load (readyState + page ready + empty composer), then cools down per-tab: user-set minimum (default 5 min, `cooldown_min_seconds`) + stacked captcha penalty (default +15 min each, `cooldown_captcha_penalty_seconds`, this tab only). Tab is `steady` (ready) only after its countdown ends; pool UI shows live MM:SS + reset/edit per row; URL List win likewise (correction 2026-09-16): pause/penalty bar in win, live countdown + reset/edit on each URL row matched to its pool tab, one shared image queue; cancel skips cooldown. Each URL row is bound to the tab that ran it (`UrlRow.tab_id`, set at run start on both paths) so the row always shows its own tab's timer even when same-site twins tie on URL match; the finish log prints the breakdown (`total = base + captcha xN`). Captcha is also waited + recorded at submit/download boundaries. Load balancing: each finished job increments the tab's persistent counter and the next job goes to the free tab with the lowest count (ties keep pool order); Jobs column shows the counter. Design: `docs/archive/2026-09-16-job-cooldown/design.md` + `correction-url-list.md`. Silent-miss diagnosis: `fix-persist-silent-miss.md`. |

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
| I-29 | 2Captcha key never exposed — raw key lives only in git-ignored `config/2captcha.json` (0600 best-effort); WebChannel/UI carry masked form only; key never in logs, payloads, presets, or error text; solver failures never block the job (fall back to manual wait) | New (2026-09-17) | `CaptchaKeyStore.mask` + bridge status payload + RULE 20 amendment |
| I-29 | Run prefers a ready tab — single-mode start and each image re-resolve primary to the best ready pooled tab (lowest jobs); primary reconnects on move; waits only when all tabs cooling; stay/move decisions logged with one-line pool summary, build hash logged at startup | New | `resolve_primary_tab` + `_select_run_tab` + `_pool_summary` |
| I-30 | Page-error fast-fail — wait loop scans alert/toast/error regions each poll; fresh limit/error text aborts the wait so the job finishes FAILED (retryable) instead of stalling to timeout; stale banners ignored via wait-start baseline | New | `app/utils/page_errors.py` + `_poll_output_diag` + `_reraise_abort` |
| I-31 | Per-tab stop + job line — URL rows show the running image (`▶ name`) from pool pushes; Stop button aborts that tab's job (fails as Aborted, batch continues); stuck-reset refuses only while that tab's own job is alive | New | `stop_tab_job` + `request_tab_abort` + `set_tab_image` + `jobLineForTab` |
| I-32 | Folder _AI ops — toolbar Drop _AI strips the suffix from filenames in the picker folder recursively (`photo_AI_1.png` → `photo_1.png`, never overwrites, collisions skipped); Only _AI deletes all non-_AI images there (confirm dialog); images only, hidden dirs skipped, refused mid-run, queue synced | New | `drop_ai_suffix` + `keep_only_ai_files` + `app/core/folder_ai.py` |

---

## 6. Storage map — JSON only, no DB

| File | What it holds | Why |
|---|---|---|
| `config/arena.json` | `prompt`, `action_blocks` (19 types: CUSTOM_FIND generic + 14 original + PAUSE/HIGHLIGHT/TYPE_PROMPT/VERIFY_ATTACHMENT, each with selector/label_selector/match_text/match_mode/click_enabled/click_selector/fallback/highlight_enabled/color/timeout/pre_delay/highlight_ms/confirm_pause_ms), `custom_blocks` (reusable Find & Click presets chips), `settings` (supported_types, ignore_suffix, highlight.duration_seconds, highlight.confirm_pause_ms, highlight.color, max_attempts, download_timeout, cdp_host, cdp_port, user_data_dir) — all UI params storable, rect duration saved in preset JSON | Arena preset store — save/load/import/export with preview, from Old App system |
| `config/urls.json` | `urls: [{url, status, last_checked, error}]` | URL list + validation status |
| `config/session.json` | `grid_layout`, `window_states`, `window_preset_store`, `undo_history`, `folder`, `images` (queue), `selected_ids`, `prompt`, `settings` overrides, `stats` | Session persistence — layout + queue + undo |
| `config/undo.json` | Full undo stack (100 cap) — alternative location, mirrored to session.json | Global undo timeline |
| `config/2captcha.json` | `enabled`, `api_key`, `solve_timeout_sec` (git-ignored, 0600 best-effort) | 2Captcha opt-in settings — kept out of arena.json/session.json so presets never carry the key (RULE 20) |
| `config/captcha_stats.json` | `detected_total`, `auto_solved`, `auto_failed`, `manual_solved`, `tasks_created`, `tasks_deleted`, `last_balance`, `balance_at`, `last_error`, `per_site` (≤49 hosts + `*`) | Captcha statistics for the Settings panel — corrupt file → blank, partial file keeps valid fields |
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
| **core** | `app/core/action_blocks.py`, `correlation.py`, `naming.py`, `image_saver.py` | Domain logic, no Qt, no CDP | stdlib, PIL |
| **services** | `app/services/folder_scanner.py`, `url_validator.py` | Folder scan, URL validation, filtering (RULE 6) | core, stdlib |
| **browser** | `app/browser/cdp_client.py`, `cdp_arena.py`, `dom_highlight.py`, `site_adapter.py` | CDP connection with lock, visual runner (RULE 1), selector map (RULE 21) | core, services, stdlib, websockets |
| **persistence** | `app/persistence/app_state.py`, `config_manager.py`, `layout_service.py`, `undo_service.py` | JSON persistence, grid layout validation (RULE 13), undo timeline (RULE 12) | core, stdlib |
| **ui** | `app/ui/bridge.py`, `main_window.py`, `panels/*.js`, `web/js/*.js`, `web/css/variables.css` | PyQt6 + WebChannel, sash-grid, win-grip, dark mode, rect overlay | all below via bridge |
| **pipeline** | `app/pipeline/runner.py` (if exists) or `bridge._do_run_batch()` | Batch loop, state machine 00-22, stop honour (RULE 7), progress (RULE 5) | core, browser, persistence |

**Import direction:** `ui` → `browser` → `services` → `core` → stdlib. No cycles. No `browser.*` import from `ui/` except via bridge. No Qt in `core/`.

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

Baseline if exists: `reports/CODE_QUALITY_METRICS_*.md`. Never decrease.

Override format: `# quality-override: metric=value reason=...` with metric ∈ `loc, class-loc, params, methods, cc, cognitive, nesting, coverage, vulture, dup`, reason ≥20 chars naming constraint.

Anti-gaming: no `foo_part1/part2`, no `**kwargs` dodge, no dummy helpers, no lambda dispatch to hide `if`.

Remediation order: nesting → cyclomatic → cognitive → size (RULE 19).

---

## 10. History of designs — pointers to archive

* Old App designs: `Process Images in Areana/Old App/docs/archive/` — virt-chat specific, not reused except UI system and action blocks idea
* New App designs: `docs/archive/<YYYY-MM-DD>-<topic>/` — each feature that moved complexity across files gets dated folder with design doc, then rows in this file updated
* `docs/archive/2026-09-16-job-cooldown/design.md` — job cycle & cooldown (New Chat reset, per-tab pause, captcha stacking)
* `docs/archive/2026-09-17-captcha-penalty/solution.md` — captcha-penalty hardening (record choke point, sticky row-tab binding, boundary checks, finish breakdown, reset keeps debt)
* `docs/archive/2026-09-17-2captcha-integration/design.md` + `summary.md` — 2Captcha auto-solve (opt-in, RULE 20 amendment): detect probe → solver (per-tab dedup, poll, inject + verify) → manual fallback; Settings key store (masked-only UI) + statistics; `handle_captcha` choke point for all call sites
* `docs/archive/2026-09-18-captcha-detection-verification/design.md` — detection/solver-payload verification against real page states (badge vs dialog, two sitekeys, `size=` param → `isInvisible`, badge exclusion, real container/text signals)
* `docs/archive/2026-09-18-captcha-visual-await/design.md` — 2nd-round badge false positive: saved-state research (badge `position:fixed; visibility:hidden; right:-186px` ⇒ `offsetParent` non-null in normal state), v2 on-screen geometry predicate, exact-moment CAPTCHA_WAITING/CAPTCHA_AUTO visual flags, Captcha-window policy status line
* `docs/archive/2026-09-18-captcha-why-not-solving/design.md` — "detected but solving was not done": auto-solve is opt-in (default OFF → manual wait by design); watcher overlay now carries the WHY (amber reason line: auto OFF / no sitekey / auto failed) via the dead `elapsed_sec` → `sub` param swap; auto-skip is no longer silent (`⚠️ FLAG CAPTCHA_AUTO skipped`)
* `docs/archive/2026-09-18-captcha-token-callback/design.md` — "dialog still visible after token injection": arena's reCAPTCHA is callback-driven (anchor src `&cb=<name>` → `window[cb](token)` closes the dialog); injection now invokes the callback; wait loop is security-aware (`security_settler` gate) so mid-wait dialogs are settled inline instead of burning the 180 s generation timeout
* `docs/archive/2026-09-18-grid-persist-api-logging/design.md` — grid persistence fix (close-time flush was fire-and-forget → now synchronous QEventLoop+1.5 s; startup restore guard defers grid saves until the backend restore lands, 3 s timeout; grid slots hardened) + 2Captcha API debug logging (createTask OK/FAILED with task id + sitekey tail + errorId/message, poll status transitions, token received) + Captcha window **Reset** action (stale cumulative stats were misread as current-run failures)
* `docs/archive/2026-09-18-captcha-resubmit/design.md` — "token accepted, dialog closed, but generation never resumed" (11:37 run: 4/4 solved in 60–76 s, all 4 jobs 180 s timeout): arena resumes a challenged request via the reCAPTCHA widget callback, which an injected token cannot trigger (dialog anchor exposes no callable `cb=`) — the human-parity step is missing. Wait-loop gate now does **post-solve re-submit**: after a settled captcha, if no spinner (request dead) and the composer still holds the exact prompt, one `submit()` (guarded — never double-sends a live/consumed send). Diagnostics: detect log prints anchor `cb/size/anchor-ms/execute-ms`, continue-click logs which button closed the dialog, every post-solve decision is logged
* `docs/archive/2026-09-18-grid-restore-push/design.md` — "grid save not working / win on restart is resetted": the boot restore relied on a single QWebChannel `invokeMethod → response` round trip (`get_grid_layout(cb)`) with zero observability — a lost response leaves the grid silently on default. Fix: **signal-push boot restore** — the page requests via `request_grid_restore` / `request_window_states_restore` (proof the channel is ready) and the bridge emits the saved layout on the `grid_layout_restored` / `window_states_restored` signals (the delivery path every log line already uses); idempotent appliers make callback+push double delivery render once; every restore outcome now logs (`🪟 Grid restored from session (N windows)` / rejected / no backend response)
* `docs/archive/2026-09-18-window-preset-restore/design.md` — the grid-reset **root cause**: Python `WINDOW_IDS` lagged the UI (13 windows, missing `captcha` vs the UI's 14) — every save of a live 14-window grid failed validation, "migrated" as a no-op, and `canonical_grid_payload` **silently returned the 13-window default**, replacing the user's layout on disk (their session.json grid was byte-identical to the default). Now: window set synced to the UI (14 incl. `captcha`, default tree mirrors `SashCore.defaultTree`), and an unreconcilable layout **rejects with a reason** instead of swapping in the default. Also fixed: `load_window_preset` returned an envelope (no `format`) → every preset preview died with "unsupported window preset format or schema version"; it is now a pure reader returning the full portable document (previewing no longer rewrites the session), legacy slim docs are upgraded (`windows[]`/`screen` synthesized, `synthetic: true` → legacy note in the preview), and exports round-trip the strict import validation
* `docs/archive/2026-09-18-captcha-wait-visibility/design.md` — "captcha on screen but nothing solves, no log, detection not clear": the per-poll security gate inside the 180 s generation wait was a **silent no-op** — `ctrl.security_settler` was only armed by `single_job_runner`, never by the bridge block runner, so a dialog opening mid-wait produced zero logs and zero solve attempts (only a single pre-wait check existed). Now: the bridge **arms the settle hook** for its WAIT_OUTPUT + DOWNLOAD wait paths, the gate evaluates the new **`diagnose.js` probe** (identical verdict to `visible.js` + kind/sitekey + **evidence**: dialogs/open text, iframes in-badge/in-dialog/on-screen with geometry, and a one-line **reason**), logs verdict changes + a ~30 s `🔎 Security scan` heartbeat + a never-silent no-settler warning, and a **"🔍 Scan now" button** in the Captcha window runs an on-demand numbered step-by-step report (page → dialogs → iframes → verdict → auto-solve state → action) — the user's debug steps
* `docs/archive/2026-09-18-captcha-completion/design.md` — the solve reached **token injected** but the flow never resumed: the dialog's sitecallback is a JS closure (no `cb=` in the dialog anchor, no Continue button), which an injected token never fires, so the dialog was stuck by design and the 20 s grace always expired into "not accepted". Now: injection also **patches `grecaptcha.getResponse`** to return the token (the widget-internal read path), a short 3 s self-close grace is followed by a **step-wise force-close** (Escape → Radix close control → nuclear remove of dialog + overlay + focus guards) — closed ⇒ solved, token stays in the field; the bridge flow then **re-sends the prompt once** if the request died (round-6 `_post_solve_resubmit` parity: `♻️ post-solve: request was dead — re-sent prompt`); "🔍 Scan now" gained deep evidence (dialog markup, grecaptcha surface, **bundle source** around the dialog markers) to close any remaining loop
* Selector research: `docs/selector_map.md` (detailed), `docs/research_summary.md`, `docs/current/DOM_SELECTORS.md` (living reference)
* Workflow: `docs/workflow_diagram.md`, `docs/data_model.md`, `docs/implementation_plan.md`

---

## 11. Current UI — 11 windows (from Old App, adapted)

| Window ID | Title | Content | Persisted in |
|---|---|---|---|
| `url_list` | URLs | URL list with status (unchecked/valid/invalid/unreachable/auth_required/not_ready), add/remove, include/exclude | `config/urls.json` + `session.json` |
| `folder` | Folder | Folder picker, recursive scan, stats found/ignored/unsupported, supported types | `session.json` folder + settings |
| `queue` | Queue | Table thumb/path/selected/processing/URL/attempts/output/error, bulk controls | `session.json` images + selected_ids |
| `prompt` | Prompt | Base prompt textarea, token preview `[JOB-ID: xxx]\n<base>`, final prompt | `arena.json` + `session.json` |
| `action_blocks` | Action Blocks | Stack of 19 blocks restored from Old App: CUSTOM_FIND (click on btn/text areas), PAUSE, HIGHLIGHT, TYPE_PROMPT, VERIFY_ATTACHMENT plus 14 original. Drag-drop with drag_indicator win-grip, enable toggle, config panel per block (custom_name/selector/label_selector/match_text/match_mode/click_enabled/click_selector/fallback/highlight_enabled/color/pre_delay/confirm_pause/highlight_ms/timeout), double-click highlight, custom blocks chips save/load, separate jobs view with rectangles confirmations as it makes clicks, rect duration configurable saved in preset JSON, undoable | `arena.json` action_blocks + custom_blocks + session.json |
| `run_controls` | Run | Start/Pause/Resume/Stop after/Cancel/Retry, state machine display 00-22 | ephemeral |
| `progress` | Progress | Progress bar, stats total/selected/completed/failed/skipped, current image | ephemeral + session stats |
| `log` | Log | Log console with levels info/success/warn/error, filter, clear, export | `logs/arena.log` |
| `settings` | Settings | Supported types, ignore suffix, highlight duration, confirm pause, max attempts, download timeout, CDP host/port, user-data-dir | `arena.json` settings |
| `cdp` | Connection | Chrome debug port status, tab list, best match, connect/disconnect, user decides port and --user-data-dir | settings cdp_host/port/user_data_dir |
| `help` | Help | Manual, selector map, workflow, shortcuts, about | static |

**Layout:** Sash-grid draggable via win-grip `drag_indicator`, splittable/mergeable/resizable sashes, dock minimized, windows menu, Grid view menu layouts default/A/B/C + Reset, Window presets save/load/import/export with preview. Persistence `grid_layout+window_states+window_preset_store` in `config/session.json`. From Old App, tested. Sash visibility single-rule + "divider touches only adjacent rows" invariants: `docs/archive/2026-09-17-watcher-grid-bugfixes/SOLUTION.md`.

**Dark mode:** `app/ui/web/css/variables.css` reused from Old App — same variables, same dark theme.

---

*Last updated: 2026-09-17. This file is the current truth — if not true today, it does not belong here (RULE 17). Archive old truth to `docs/archive/<date>-<topic>/`.*
