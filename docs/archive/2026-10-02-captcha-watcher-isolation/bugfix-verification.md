# Bugfix verification — 2026-10-02 release

Six UI defects shipped with the Captcha Watcher isolation. Each row: what
the user saw → what the code did → what changed → the test that pins it.
B6 (2026-10-03) is the follow-up found when the user reported "Browse still
does nothing" after B4 — it is the **actual** root cause behind most of the
dead-button reports and supersedes the B4/B5 diagnoses for that symptom.

## B5 — Boot ordering (`app/ui/web/js/core/boot.js`)

* **Saw:** after one panel's `init()` threw, every panel listed after it in
  `_PANEL_INITS` stayed dead; a mistyped slot name produced no output at all
  (QWebChannel drops unknown methods silently).
* **Did:** `initApp()` looped the panel list with no isolation; every panel
  hand-rolled its own "is the bridge there" check.
* **Change:** `window.Boot` — `onBridgeReady(fn)` (delegates to the single
  `BridgeReady` handshake, DOMContentLoaded fallback when standalone),
  `bindOnce(el, ev, fn, key)` (one listener per element+event+key even if
  `init()` runs twice), `needBridge(slot)` (bound slot or `null` + ONE warning
  per missing slot, echoed to the in-app LogConsole once the bridge exists),
  `bootPanels(names)` (init each once, `try/catch` per panel).
  `arena-app.js` boots through it; `boot.js` is loaded right after
  `bridge-ready.js` in `index.html`. Deliberately **not** a second
  `window.App` (would shadow `const App` in `arena-app.js`).
* **Pinned by:** `tests/js/test_boot.mjs` (bindOnce dedupe, needBridge warns
  once / distinguishes "not connected", bootPanels once + isolation,
  onBridgeReady delegation + standalone fallback).

## B1 — URL list (`url-list/listeners.js`, `url_queue.py`)

* **Saw:** "Add" toasted `URL already exists` on a single click after a state
  restore; Edit did nothing (native `prompt()`); bookmark buttons in the CDP
  panel never refreshed.
* **Did:** the facade bound the controls itself and re-bound on every
  `init()`; `editUrl` used `prompt()`; `add_url_preset`/`remove_url_preset`/
  `set_last_url_preset` were `@Slot(str)` returning `None`, so the JS
  callback never ran.
* **Change:** all URL-window DOM listeners live in
  `window.UrlListListeners.bind(facade)` (Boot.bindOnce, ids `urlAddBtn`,
  `urlInput`, `urlTableBody`, `urlReparseBtn`, `urlPopupBtn`,
  `urlCooldownSaveBtn`); the facade only delegates and starts its timers once.
  `editUrl` opens `Dialog.promptEdit` prefilled with the current URL.
  Python: `commit_urls(bridge)` is the one write path (persist + emit + undo);
  `edit_url` is validated like `add_url` (scheme, duplicate on another row,
  2,048-char cap) and replies `{ok, url}`; the three preset slots return JSON.
* **Pinned by:** `tests/js/test_url_list_listeners.mjs`,
  `tests/test_url_queue_bugfixes.py`, existing `tests/test_panel_slots.py`.

## B2 — Action blocks (`block-store.js`, `blocks_stack.py`, `core/action_blocks_defaults.py`)

* **Saw:** stack silently reduced to the 9 required blocks (no
  CHECK_SECURITY → no captcha pause, no verify blocks); "Reset" sometimes did
  nothing visible.
* **Did:** `ActionBlocksStore.load()` called `bridge.get_action_blocks()`
  synchronously — under QWebChannel that returns `undefined`, so the store
  painted local defaults while the backend could hold `[]` (a preset import
  or undo snapshot can write it). `get_action_blocks(bridge)` fed `[]` to the
  forgiving loader, which appends only the *required* blocks → 9-block runner
  stack. `resetToDefault` called `reset_action_blocks` twice.
* **Change:** store accepts blocks only through `_acceptBlocks` (shape check;
  empty/garbage → defaults), `load(cb)` goes through the callback (sync shim
  kept for tests), `save()` refuses an empty/invalid stack,
  `restoreDefaults(cb)` calls `restore_default_blocks` (fallback
  `reset_action_blocks`) once and adopts the reply. Python:
  `get_action_blocks` heals an empty persisted stack to the **full** defaults
  and persists the heal (runner and UI agree); `save_action_blocks` rejects
  `[]`; new slot `restore_default_blocks` replies with the blocks it saved;
  `app/core/action_blocks_defaults.py` owns `build_default_stack`,
  `is_empty_stack`, `heal_stack`, `regenerate_ids`, `missing_required`
  (delegating to the canonical `DEFAULT_STACK_ORDER`, CHECK_SECURITY included).
  All native `confirm/prompt/alert` in `action-blocks.js` → `Dialog`.
* **Pinned by:** `tests/test_action_blocks_defaults.py` (incl. the regression
  pin "loader alone turns `[]` into required-only"), block-store cases in
  `tests/js/test_action_blocks.mjs`.

## B3 — Prompt / arena presets (`index.html`, `arena-presets/{actions,render}.js`)

* **Saw:** Arena Presets window: Save / Export / Import / "Save Prompt" dead,
  list stuck on empty; the Prompt window's injected bar worked.
* **Did:** `actions.js` injected a second prompt bar into `#winPrompt` and an
  arena bar into `#winSettings` re-using the static window's ids
  (`promptPresetSaveBtn`, `arenaPresetSaveBtn`, `arenaPresetExportBtn`,
  `arenaPresetImportBtn`). `getElementById` bound whichever copy came first
  in DOM order; `render` wrote into the injected containers only.
* **Change:** static markup only — prompt bar `#promptPresetBar` in
  `#winPrompt` (`promptPresetName`, `promptPresetSaveBtn`, `promptPresetSelect`,
  `promptPresetLoadBtn`, `promptPresetDeleteBtn`); the Arena Presets window
  keeps its own unique ids (`arenaPresetNameInput`, `arenaPresetSaveBtn`,
  `arenaPresetExportBtn`, `arenaPresetImportBtn`, `arenaPresetFileInput`,
  `arenaPresetsList`, `arenaPromptPresetNameInput`, `arenaPromptPresetSaveBtn`,
  `promptPresetsList`). `actions.js` only binds (once) and acts; `render.js`
  fills the `<select>`, both lists and the `arenaPresetsCount` badge, rows
  built with `createElement`/`textContent` (no HTML injection from names),
  delete asks through `Dialog.confirm`.
* **Pinned by:** `tests/js/test_arena_presets_actions.mjs` (every id unique
  in `index.html`, bound once, no injected bar, guards, load/delete/render).

## B4 — Folder picker (`queue_scan_folder.py`, `models.py`, `folder-picker.js`)

* **Saw:** "Browse" did nothing (no toast, no log) on profiles with an older
  `arena.json`.
* **Did:** `pick_folder` assigned into `self.state.folder["root_path"]`;
  `"folder": null` or a bare path string in a legacy file made that raise
  inside the slot → no reply. New-Batch used native `confirm()`.
* **Change:** `FolderPickMixin` (`pick_folder`, `set_folder_path`) in
  `app/ui/panels/queue_scan_folder.py`, inherited by `QueueScanMixin`:
  `as_folder_dict` / `ensure_folder_dict` normalise every shape,
  `commit_folder` is the single write path (persist + undo, replies
  `{ok, path, folder}`), both slots wrap in `try/except` → error JSON.
  `AppState.from_dict` normalises `folder` at load. JS: `Boot.bindOnce`,
  `Boot.needBridge` (missing slot is reported), `Dialog.confirm` for New Batch.
* **Pinned by:** `tests/test_queue_scan_folder.py` (None / str / int folder
  shapes, blank path, dialog ok/cancel/missing, model normalisation),
  updated `tests/test_file_dialogs.py`.

## B6 — Global-name contract: panels never initialised (`arena-app.js`, `boot.js`, every panel module)

* **Saw:** after B1–B5 shipped, the Folder Picker's **Browse** still did nothing
  — no dialog, no toast, no log line, nothing in the console.
* **Did:** every panel (and `App` itself) is declared as a top-level
  `const X = {...}` in a classic `<script>`. That creates a **lexical** global
  binding — it is *not* a `window` property. `Boot.bootPanels(_PANEL_INITS)`
  (and the pre-existing `_initIfExists`) resolved panels through
  `window[name]`, so only the three panels that already exported themselves
  (`CDPPanel`, `ActionBlocksPanel`, `WindowPresets`) ever ran `init()`; the
  other **14 panels never bound a single listener** (Browse / Scan / New
  Batch, URL add, Run controls, …). `_restoreArenaPanels` skipped the same
  panels, and `window.App` — read by **22 modules** to reach the bridge
  (`window.App.bridge`, `window.App.state = data` in the arena-state listener)
  — was `undefined`. Verified in V8 (`node:vm` context == Chromium semantics):
  `window["FolderPicker"] === undefined`, `typeof FolderPicker === "object"`.
  The Python side was healthy: `pick_folder` / `set_folder_path` are present in
  the real `Bridge` `QMetaObject` (checked with PySide6 6.11 offscreen) and
  `set_folder_path` round-trips.
* **Change:** (1) `arena-app.js` publishes `window.App = App` right after the
  `const`; (2) every `const` panel module ends with
  `if (typeof window !== 'undefined') window.X = X;` (the convention the
  three working panels already used) — `UrlList`, `FolderPicker`,
  `ImageQueue`, `PromptEditor`, `RunControls`, `ProgressPanel`,
  `WatcherPanel`, `PagePoolPanel`, `SettingsPanel`, `CaptchaPanel`,
  `CaptchaRecordingsPanel`, `BrowserPreview`, `HighlightOverlay`,
  `ArenaPresets`, plus `SashGrid` (read as `window.SashGrid` by
  `block-ui.js`); (3) `Boot.panel(name)` resolves by name and warns ONCE
  (`[Boot] panel not found on window: X`) instead of skipping silently —
  `bootPanels` and `_restoreArenaPanels` go through it; (4) `initApp()` wraps
  `setupHeader()` in `try/catch` so a header failure can no longer abort the
  panel boot that follows it.
* **Pinned by:** `tests/test_ui_wiring.py::test_every_boot_panel_is_published_on_window`
  (every `_PANEL_INITS` name + `App` has a `window.X =` writer),
  `::test_every_window_dot_name_read_is_published_somewhere` (no `window.X`
  read of a const-only name anywhere in `web/js`),
  `::test_panel_export_lines_match_their_const`;
  `tests/js/test_folder_picker.mjs` (real `boot.js` + `folder-picker.js`:
  publish → boot → Browse click → `pick_folder(startDir)` → display/input
  updated; cancel/error replies; bindOnce on double boot; missing slot
  reported; Scan / New Batch / Enter-to-set);
  `tests/js/test_boot_all_panels.mjs` (loads **every** `index.html` script in
  page order into one V8 sandbox with a fake QWebChannel: all 17 panels
  init without throwing, `window.App === App` with the bridge, Browse reaches
  `pick_folder` exactly once). Before the fix that harness reports **3 / 17**
  panels booted and 0 Browse listeners; after it 17 / 17.
  `tests/js/test_boot.mjs` gained the "unpublished panel warns once" case.
  `package.json` `test:js` now also runs `test_boot.mjs`,
  `test_url_list_listeners.mjs`, `test_arena_presets_actions.mjs` (added on
  2026-10-02 but never wired into the script) and the two new files.

## B7 — URL row disappears ~1 s after Add (`url-list/actions.js`, `undo_entries.py`)

* **Saw:** typing a URL and pressing Add/Enter showed the row for about a
  second, then the table re-rendered without it; `arena.json` did not keep
  it either. (Latent before B6: `_onAdd`'s deferred callback threw on the
  undefined `window.App`, so pre-B6 nothing was rendered at all.)
* **Did:** `add_url` (Python) appends the row and runs `commit_urls()` — the
  single write path: `_save_arena()` emits `arena_state_updated` and
  `push_urls_undo()` records the global undo entry. The JS side applies
  `arena_state_updated` after a **250 ms debounce**
  (`arena-app/listeners.js::_handleArenaState`). `_onAdd` (and `_applyEdit`)
  additionally scheduled, **100 ms** after the ok reply,
  `ArenaHistory.recordGlobal('urls', window.App.state.urls)` — a snapshot
  taken *before* the debounced apply, i.e. the list **without** the new row.
  `recordGlobal` calls `bridge.push_global_history('urls', …)` →
  `undo_entries._remember_urls` **replaces** `bridge.state.urls` with that
  stale list, saves, and emits `arena_state_updated` again → 250 ms later the
  table renders the old list. The push was redundant anyway (Python already
  recorded the undo entry; `history_changed` → `_syncGlobalHistory()` pulls
  it into the client timeline) and, when the timing happened to be right, it
  would have created a duplicate entry. Side finding: `url_rows_from_js` /
  `arena_url_rows_from_js` dropped `tab_id`, so every urls undo/redo/push
  silently unlinked the rows from their tabs.
* **Change:** removed both deferred `recordGlobal('urls', …)` push-backs —
  the client never echoes URL rows to Python; `url_rows_from_js` and
  `arena_url_rows_from_js` keep `tab_id`.
* **Pinned by:** `tests/js/test_url_list_add_persists.mjs` (real
  `arena-history.js` + `url-list/actions.js`; the bridge fake commits rows
  like the slots and applies `push_global_history('urls')` like
  `_remember_urls`: Add and Edit leave the committed row in place with **zero**
  push-backs, failed Add keeps the typed text, a *regression replay* shows the
  old push-back erased the row, and a static guard rejects any
  `recordGlobal('urls'` / `push_global_history('urls'` under
  `panels/url-list/`); on the pre-fix file 3 of the 5 cases fail.
  `tests/test_undo_history.py::test_url_rows_from_js_keep_tab_link`,
  `::test_remember_and_apply_urls_keep_tab_link`.

## B8 — Image generated + downloaded, then every page probe answered nothing (`cdp/transport.py`, `page_recovery.py`, `visual_click.py`, `single_job_runner.py`)

* **Saw:** the generation finished and the app pulled the image
  (`📥 Python download 940228 bytes image/png`), then the very next block
  (a user-added **Find & Click** with the default selector `button`, placed
  after DOWNLOAD) logged `❌ FIND failed: button — no data returned from the
  page (page context unavailable?)`, the job ended **failed** without the
  image, and the automatic New-chat reset failed the same way three times
  inside one second ("cooling anyway"). The next job on the same tab worked
  again — the tab was never dead for long.
* **Did (three defects, one incident):**
  1. `CDPTransport.evaluate()` returned `None` for *every* failure class and
     told nobody why. A CDP **protocol error** reply
     (`{"error": {"message": "Execution context was destroyed."}}` — what
     Chrome answers while a page is between two documents) was read as
     `result={}` → `None` **without even a log line**; JS exceptions and
     transport errors (`ConnectionClosed`, "CDP not connected") only went to
     the `arena` Python logger, which has no file handler in the app
     (`app/utils/logging.py` writes `arena_processor`). The UI could only guess
     ("page context unavailable?").
  2. The shared click runner (`visual_click.find_phase`, `_stage`) failed the
     block on the **first** empty answer. A page mid-reload/navigation is a
     ~1 s condition; a closed DevTools socket is recoverable by re-attaching
     to the same tab — neither was ever retried, so one transient blip failed
     the block, the job and the reset. No app code reloads/navigates the tab
     (`reload_page` has no callers; nothing writes `location.*`), so the
     loss came from the page/Chrome itself — it must be tolerated, not
     assumed away.
  3. Pipeline policy: `_loop_blocks` marked the job failed on **any** block
     failure, and a `required` block failure broke the stack **before
     VALIDATE/SAVE** — so a failing post-download page action threw away an
     already-downloaded (paid) generation.
* **Change:** (1) `transport.evaluate()` now records `last_error` /
  `last_error_kind ∈ {js, protocol, transport}` (cleared on success) and logs
  every class; (2) new `app/browser/page_recovery.py` classifies the record
  (`is_transient_loss`: protocol "Execution context was destroyed" /
  "Cannot find default execution context" / …, or any transport loss except
  timeouts) and `recover_page_context()` waits up to 3 × 1 s for
  `document.readyState` to answer again, **re-connecting the same ws URL when
  the socket closed** (never re-picks tabs), then settles 1 s so a reloaded
  SPA can mount; (3) `visual_click._probe_json` runs FIND and click-target
  staging through that recovery (≤ 3 probe rounds) and every "no data"
  message now carries the transport's real reason — the click dispatch itself
  is deliberately **never** re-sent (it may already have landed); New-chat
  reset goes through the same runner and inherits the recovery;
  (4) `single_job_runner._loop_blocks`: once the output bytes are secured
  (`_output_secured`, same > 100-byte rule as DOWNLOAD), a later failure of any
  block other than VALIDATE/SAVE is logged as
  `⚠ <block> failed after the image was downloaded (<err>) — continuing so
  the image is saved` and the stack continues to VALIDATE/SAVE/ADVANCE; the
  block still shows red in the stack UI. VALIDATE/SAVE failures,
  pre-download failures (golden `nonreq_fail`) and cancellation keep the
  legacy semantics. `download.py` reports the same reason when the in-page
  download attempt answers nothing.
* **Pinned by:** `tests/test_cdp_client.py::test_evaluate_records_{js_exception,protocol_error}_reason`,
  `::test_evaluate_success_clears_last_error`,
  `::test_evaluate_records_transport_loss_after_socket_close` (the shared
  fake ws now raises on send-after-close like real `websockets`, instead of
  parking the reply in a queue for the 30 s timeout);
  `tests/test_page_recovery.py` (classification table, wait-until-document
  answers, give-up after N, reconnect to the same tab, reconnect failure
  reported not raised); `tests/test_visual_click_recovery.py` (FIND recovers
  after "Execution context was destroyed" and succeeds, real reason in the
  failure line, JS errors never retried, closed socket → reconnect → success,
  legacy fakes unchanged, stage recovers but the click is dispatched exactly
  once); `tests/test_job_output_policy.py` (post-download Find & Click
  failure — required or not — keeps the image, job completes with the
  warning; pre-download optional failure still "failed"; SAVE / VALIDATE
  failures still fail the job; cancellation and VALIDATE/SAVE never
  downgraded). Characterization goldens unchanged.
* **Operator note:** a **Find & Click** with the bare default selector
  `button` after DOWNLOAD clicks the first button on the page — configure the
  block (selector / text) or remove it; the job no longer depends on it.
* **Correction (2026-10-05, see §B9):** defect 2 above was a wrong
  hypothesis. The FIND probe did not fail because the page context was lost
  for a second — it failed **every time**, because the generated probe JS was
  syntactically invalid (§B9). The `last_error` contract added here is what
  finally made the real reason visible in the next log
  (`SyntaxError: Unexpected token 'catch'`); the recovery path (`page_recovery.py`)
  stays as hardening for genuine context losses, but it never fired for this
  incident (JS errors are — correctly — not retried). The "next job worked
  again" observation was about the main pipeline (ATTACH/SUBMIT/WAIT use other
  JS), not about the FIND probes, which had never worked since the import.

## B9 — Every FIND / HIGHLIGHT probe was a `SyntaxError` since the import; a saved image still ended "failed" (`dom_highlight_js.py`, `single_job_runner.py`)

* **Saw:** with the B8 diagnostics in place the next run showed the real
  reason for every failing page probe: `❌ FIND failed: … — page JS error:
  SyntaxError: Unexpected token 'catch'` for **Submit Once** (fell back to
  the controller submit), the post-download **Find & Click**, and all three
  **New Chat** reset attempts (→ tab cooled for 20 min). Every job also ended
  `failed` with `Verify attachment failed: preview not found
  div.flex.flex-wrap.gap-2 img` — although the ATTACH step had just logged
  `Attachment verified: Found via blob` and the image was downloaded
  (`📥 Python download 940228 bytes image/png`), validated and saved.
* **Root cause 1 — one missing brace, since commit `0eeec39` ("upd", the
  import; no earlier history):** `app/browser/dom_highlight_js.py`
  `_LABEL_JS` — the `if (childSel) { var c = node.querySelector(childSel);
  if (c) { … } ` line never closed the `if (childSel) {` block, so the
  candidate `for` loop never closed and the following `} catch (err) {`
  became a syntax error. `_LABEL_JS` is spliced into **both** `_FIND_BODY`
  and `_HIGHLIGHT_BODY`, so every `build_find_probe()` /
  `build_highlight_probe()` payload — visual click FIND phase (Submit Once,
  Find & Click, New Chat reset, CUSTOM_FIND), `VERIFY_ATTACHMENT`, every
  `HIGHLIGHT_*` marker block and the highlight-selector helper — was dead
  on arrival; `Runtime.evaluate` answered with `exceptionDetails`, the
  transport returned `None`, and every caller read that as "not found".
  The click probe (`_CLICK_BODY`, no label splice) was fine, which is why
  clicks worked once a FIND had been satisfied by other means. The
  verify-attachment **selector was not stale**: `div.flex.flex-wrap.gap-2 img`
  is the same container the successful blob check uses; the probe simply
  never ran. Reproduced offline: `node --check` on the generated FIND /
  HIGHLIGHT probes → `SyntaxError: Unexpected token 'catch'`; click probes
  pass. Why no test caught it: `tests/test_dom_highlight.py` only asserted
  on the *generated strings* — the exact anti-pattern RULE 8 names — and no
  Node lane executed these probes (unlike the composer/output/recording
  probes). (A suspected second defect — doubled backslashes in the
  `/\s+/g` regexes — was a display artefact of the tool transport; the
  generated files contain single backslashes, verified byte-wise.)
* **Root cause 2 — job outcome policy:** `_loop_blocks` marked the job
  `failed` on the **first** failure of any block, including a non-required
  block that failed *before* the download; the stack then continued
  (non-required ⇒ no break), downloaded, validated and saved the image, and
  still reported `failed` with the stale early error. Golden `nonreq_fail`
  pinned exactly this legacy outcome ("VERIFY_PROMPT failed → file saved →
  status failed"). B8 only covered failures *after* the bytes were secured.
* **Change:** (1) the missing `}` in `_LABEL_JS` — every generated probe
  variant now compiles; (2) **B9 policy** in `single_job_runner`: the run
  accumulates *soft* failures (non-required block, stack continued) apart
  from *hard* ones (required break, VALIDATE/SAVE); when the SAVE block
  succeeded and the bytes are secured, soft failures are downgraded to one
  `⚠ Completed with warnings — the image was saved although non-required
  block(s) failed: <block (error)>; …` line and the job completes (status
  `completed`, `job_finished` completed, `Saved to …`). Required failures,
  VALIDATE/SAVE failures, "nothing saved" and cancellation are unchanged;
  the failed block row still shows red in the stack UI. (3) `package.json`
  `test:js` now also runs the two existing but un-wired probe suites
  (`test_output_probes.mjs`, `test_recording_probes.mjs`).
* **Pinned by:** `tests/js/test_dom_probes.mjs` (13 cases — the **real**
  Python builders are invoked through `child_process`, the payloads run in a
  `vm` context against a stub DOM: every probe compiles; FIND by selector,
  `label_selector` + contains/exact with whitespace-collapsed multi-line
  labels, `match_text` without label, highlight box appended once + rect +
  timed removal, probe exceptions reported not thrown; CLICK refuses without
  stash / detached / disabled, stage never clicks, dispatch clicks once,
  `click_selector` inner target; HIGHLIGHT + CLEAR). Mutation check: with the
  pre-fix template 8/13 fail. `tests/test_js_payload_syntax.py` (64 cases):
  **every** JS payload the app can send — 16 FIND variants, 8 CLICK
  variants, HIGHLIGHT/CLEAR/watcher overlay, new-chat, output baseline/check,
  captcha, recording, page-error scan and every `js_snippets.JS_*` — passes
  a string/regex/comment-aware bracket-balance scan (always on; catches the
  §B9 shape — 19 payloads failed on the pre-fix template) and `node --check`
  when node exists; a meta-test fails when a new `build_*` is not in the
  lane. `tests/test_job_output_policy.py` (+6: pre-download optional failure
  now completes once saved, stays failed when nothing was saved, required
  failure still breaks, VERIFY_ATTACHMENT not-found → warning + completed,
  VERIFY_ATTACHMENT found → rect, two optional failures both listed);
  golden `nonreq_fail` regenerated after review — only `status`, `error` and
  the `job_finished` status changed (events / clicks / files identical);
  `test_nonrequired_midfail_continues` now asserts `completed` + the warning
  markers. Goldens `req_fail`, `cancel`, `abort` unchanged.

## B10 — Image Queue stuck at `pending / 0 / —` while a job ran and saved; Captcha window lost the provider dropdown (`layout_state.py`, `persistence.py`, `job_events.py`, `arena-app/listeners.js`, `image-queue/*`, `key_store.py`, `providers.py`, `sdk_solver.py`, `watcher_solver.py`, `captcha.js`, `index.html`)

* **Saw (1):** a run processed the checked image and the log said the image
  was saved, yet every Image Queue row kept `STATUS pending · ATTEMPTS 0 ·
  OUTPUT —` (header `49/49 IMAGES`): neither `processing` nor the finished
  state ever became visible in the window.
* **Saw (2):** the Captcha window offered a single 2Captcha key field — the
  pre-import app let the user pick one of two solving providers
  (`config/captcha_solvers.json` still carried `2captcha` + `capmonster`).
* **What was verified, in the repo and in a whole-page Node harness (real
  scripts, fake QWebChannel):** Python tracks the run correctly
  (`mark_processing` / `_settle_image` mutate the very objects
  `state.to_dict()` serialises; the user's own `config/app_state.json`
  shows `failed / attempt_count 1 / output_path …_AI_4.png` after the B8
  run); `arena_state_updated` is emitted from the bg loop through the same
  `Qt::AutoConnection` path as `arena_log`, which demonstrably reaches the
  console; one handler is connected; applying a pushed state re-renders the
  rows. No single line in the shipped code was provably wrong in the
  sandbox — but the whole live-status path had **one** transport (the
  debounced full-state push) and several silent single points of failure:
  1. `save_arena_state` ran `save_state()` **and then** `emit_arena_state()`
     inside one `try` — any write failure (Windows sharing violation while
     an antivirus/indexer/sync client holds the freshly written JSON, a
     second writer thread mid-`os.replace`, read-only/locked file, full
     disk) skipped the UI push; the run went on, the state file lagged, the
     console got one `Failed to save state` line.
  2. `_applyPendingState` restored `UrlList → ImageQueue → ProgressPanel`
     inside one bare `try {} catch (e) {}` — a throw in the URL panel (or an
     unparsable payload) dropped the queue and progress refresh silently.
  3. `job_started` / `job_finished` only fed the Action Blocks panel; the
     queue row itself had no per-job update at all.
  4. `ImageQueue.restore` skipped rendering for an empty array (stale rows
     after Clear list) and rows carried no identity (`<tr>` had no id).
* **Change (1) — three independent transports, none silent:**
  `save_arena_state` now saves in its own `try` and **always** emits
  (I-39); the failure is reported once per distinct error per 10 s with a
  message that says the UI keeps updating; `_atomic_json_write` retries a
  transient replace failure (5 attempts, 20 ms doubling backoff, only
  `PermissionError` / `EACCES` / `EBUSY` / `EPERM`). `job_finished` payloads
  (both run paths, via the new `app/services/job_events.py`) carry
  `image_id`, `image_path`, `attempts`, `error`; the listeners registry
  forwards `job_started(job_id, path)` and `job_finished` to
  `ImageQueue.onJobStarted / onJobFinished`, which patch **that row in
  place** (`processing` + attempt, then `completed`/`failed` + output +
  error) — the debounced full-state push remains the source of truth and
  lands right after with the same values. `_applyPendingState` restores each
  panel in isolation; a failing panel is reported to `console.error` and
  once to the log console (`UI state sync: <panel> failed to render …`),
  the others keep updating; a malformed payload is reported instead of
  swallowed. Rows carry `data-img-id`; `restore` re-renders for any array
  (empty included) and leaves the table alone only when the payload has no
  `images` key.
* **Change (2) — provider dropdown restored:** `app/services/captcha_watcher/
  providers.py` is the registry (`2captcha` → `2captcha.com`, `capmonster`
  → `api.capmonster.cloud`; CapMonster Cloud serves the 2Captcha `in.php` /
  `res.php` protocol on that host per its own docs, so the ONE official SDK
  drives both — the provider only selects the SDK `server`). `CaptchaKeyStore`
  now owns `config/captcha_solvers.json` (the pre-import multi-provider
  shape: `provider`, `solve_timeout_sec`, `providers.{id}.{enabled, api_key}`),
  one key per provider; the 2026-10-02 single-provider `config/2captcha.json`
  is authoritative for the 2Captcha slot while it exists and is folded away
  on the first save (mirrored instead when it cannot be removed). New slot
  `set_captcha_provider` (surface 134 → **135**, `watcher_solver` 6 → 7);
  `get_captcha_api_key` / `set_captcha_api_key` reply with
  `{provider, provider_label, providers:[{id,label,has_key,masked_key,…}]}`;
  `make_solver` builds the `SdkSolver` for the active provider; Watcher
  status, log lines and the balance check name the provider. The Captcha
  window: provider `<select>` (option labels show `✓ key set` / `— no key`),
  key label/placeholder/hint follow the selection, Save stores the key of
  the selected provider, a rejected switch snaps the dropdown back. Raw keys
  still never cross the WebChannel or reach the log (RULE 20).
* **Pinned by:** `tests/js/test_queue_live_status.mjs` (8 — whole page:
  `job_started` → `processing`/attempt 1 (Windows path, any case/slash),
  `job_finished` completed → output basename / failed → error text + attempts
  from the payload, debounced push rebuilds rows, a throwing `UrlList.restore`
  no longer blocks the queue and is reported once, `images: []` clears the
  table, a malformed push is reported and the next good one applies, unknown
  images ignored; **pre-fix code: 7/8 fail**), `tests/test_state_push_resilience.py`
  (10 — failing `save_state` still pushes state + progress, dedup window,
  broken signal never raises, replace retry / budget / non-transient errno,
  `job_finished_payload` shape), `tests/test_captcha_providers.py` (20 —
  registry + normalisation, per-provider keys, pre-import file loads as-is,
  legacy override + migration on save, corrupt shapes, SDK receives the
  provider host, provider switch keeps both keys, unknown provider rejected,
  solver factory / `watcher_start` / status follow the active provider,
  legacy `set_captcha_settings` keeps the other key, balance log names the
  provider), `tests/js/test_captcha_provider_panel.mjs` (5), plus the
  updated `test_bridge_slots.py` (135), `test_watcher_solver_slots.py`,
  `test_captcha_key_store.py`, `test_captcha_pure_full.py`.
  `tests/js/page_harness.mjs` is the shared whole-page boot used by both new
  suites.

## B11 — Action Blocks window: header says `16 BLOCKS`, the block list is empty (`block-render.js`, `block-config.js`, `block-store.js`, `block-listeners.js`, `action-blocks.js`, new `block-views.js` / `block-fields.js`, `arena.css`, `core/action_blocks.py`)

* **Saw:** the ACTION BLOCKS — STACKING JOBS window rendered its toolbar,
  the "Reorder Blocks…" hint and the counter `16 BLOCKS`, but the stack
  area between them stayed empty. Block Config never showed a form either.
* **Root cause (verified in the whole-page harness — real `index.html`
  scripts, real Python default stack, fake QWebChannel; pre-fix result
  `0 !== 16` rows):** the C7 split rewrote `block-render.js` and
  `block-config.js` against a DOM that **never existed in `index.html`** —
  `#panel-action-blocks`, `#ab-block-list`, `#ab-add-menu`,
  `#ab-custom-chips`, `#ab-stack-presets`, `#ab-pause-indicator`,
  `#ab-block-count`, `#ab-config-form`. Every renderer began with
  `root.querySelector('#ab-…'); if (!container) return;` — a silent no-op —
  while the facade's `updateFooter` used the real ids (`#actionBlocksCount`,
  `#abTotalSteps`), so the counters updated and nothing else did. The real
  page (`#actionBlocksStack`, `#blockConfigHead` / `#blockConfigForm`,
  `#jobActionStack`, `#allJobsStack`, `#customBlockChips`,
  `#stackPresetChips`) and `css/arena.css` (`.action-block`,
  `.ab-drag-handle`, `.ab-block-info/-title/-meta`, `.ab-block-controls`,
  `.ab-check`, `.ab-edit-btn`, `.ab-delete-btn`, `.bc-*` Block Config
  design) still described the intended "target screenshot" UI; the later
  C12 modules (`block-ui.js`, `block-status.js`) already used those ids.
  Before B6 the panel never initialised, so the mismatch was invisible;
  after B6 the store loaded 16 blocks and the counter exposed it.
  Secondary defects found on the same path: `flushSave` read the form via
  `document.getElementById('panel-action-blocks')` → `null.querySelector`
  (would throw on the first edit); `bindFormEvents` re-bound the form
  listeners on every render; `loadBuiltin` / `loadCustom` /
  `loadStackPresets` still called the QWebChannel slots synchronously
  (always `undefined` — the B2 bug class) so catalog labels, custom-block
  chips and stack-preset chips never loaded; `block-listeners.js` bound
  `job_started` / `job_action_status` / `job_finished` a second time next
  to `ArenaAppListeners` (double processing, `job_action_status` with one
  argument); `job_action_status` payloads are objects (`{status, message,
  rect, …}`) but the renderer used them as class-name strings
  (`ab-block--[object Object]`); and on the Python side the three lookup
  tables `_DEFN_DEFAULTS` / `_CTOR_RAW` / `_CTOR_FROM_DEFN` were
  `tuple`-annotated attributes on the `@dataclass` → dataclass **fields** →
  `asdict()` serialised them into every saved / pushed block (3 junk keys
  per block, ~3× payload; `from_dict` ignored them on the way back).
* **Change — the render layer now speaks the page's DOM contract, and the
  contract is written down in each module header:**
  * `block-render.js` (stack list only): rows are `.action-block` DOM nodes
    (no innerHTML) with drag handle, coloured icon (`ICON_ALIASES` for the
    two names Material Icons lacks), title/meta, category / `REQ` / live
    status badges and `.ab-act[data-action]` controls; states `.selected`
    `.ab-disabled` `.dragging` `.drag-over` `.ab-status-<status>`;
    `markRowStatus` / `clearRowStatuses` update a row in place (no focus
    loss); empty stack shows a hint instead of nothing.
  * `block-views.js` (new): Current Job Stack (`.job-block-row.jb-<status>`
    with message + rect re-highlight), All Jobs tabs (`.ab-job-tab`), footer
    counters, preset chips via the shared `UIHelpers.chip`.
  * `block-fields.js` (new) + `block-config.js`: Block Config head
    (`.bc-title-row` icon / name / `block_id` / category / required) and form
    (`.bc-card > .bc-row*`), rows ordered by the block type's catalog
    `labels` (Old App "Tune" wording) then the generic fields, `extra.*`
    keys supported, colour rows with swatch + picker; events bound **once**
    (`Boot.bindOnce`); the form is rebuilt only when the shown block changes,
    so the backend's `action_blocks_updated` echo after each autosave no
    longer eats a half-typed edit.
  * `block-store.js`: catalog / custom / stack-preset loads go through the
    same callback-or-sync-shim path as `load()`; `block-listeners.js` binds
    only the signals `ArenaAppListeners` does not own.
  * `action-blocks.js`: wires the modules, `highlightBlock` (double-click /
    rect button → `HighlightOverlay.highlightViaCDP`), dead passthroughs
    removed; `index.html` loads the two new scripts; `arena.css` gains the
    state / badge / job-view rules the renderer emits.
  * `core/action_blocks.py`: the tables are `ClassVar[tuple]` — `to_dict()`
    is exactly the 25 dataclass fields again.
* **Proof:** `tests/js/test_action_blocks_render.mjs` (10, whole-page harness
  with the **executed** Python `build_default_dicts()` /
  `get_builtin_blocks_json()` as bridge replies — 16 rows with the contract
  classes, required blocks locked, empty reply → healed 16, push → 17, select
  → head + form → edit → `save_action_blocks`, toggle persists `enabled:false`,
  drag reorder saves the new order, `job_action_status` marks the row and the
  job view (routed exactly once), catalog labels order the form, custom /
  stack chips load through the async path and act on the stack; **pre-fix:
  7/8 of the original assertions fail with `0 !== 16`**),
  `tests/test_action_blocks_defaults.py` +2 (no leaked class tables, dict
  round-trip stable).

## B12 — First run "starts without pasting image and prompt and waits for a generation that never starts" (`services/single_job_runner.py`, new `services/await_processing.py`, new `browser/processing_probe.py`)

* **Saw (user, after B11):** the run began, nothing was attached or
  inserted into the composer, Chrome showed the "wait for finish
  generation" overlay and the block rows sat in *waiting*; "second run
  after wait is working". Nothing in the Action Blocks list had been
  touched (rows rendered, no chip / drag / edit).
* **Not the cause (checked first, because B11 was the last change):** the
  saved stack. The B11 UI writes nothing at boot or on select (whole-page
  jsdom run: 0 `save_action_blocks` calls until a field is edited, and an
  edit changes exactly that field, order kept); the `ClassVar` change has
  no `dataclasses.fields()` consumer and every dict round-trips; the runner
  reads the stack through the same `get_action_blocks` on every run. The
  attach / insert steps themselves (`ctrl.attach_image`, `ctrl.insert_prompt`)
  do not even read the block fields.
* **Root cause — `AWAIT_PROCESSING_IMAGE` was wired to the WAIT_OUTPUT
  handler:** `_handler_map()` mapped both `WAIT_OUTPUT` and
  `AWAIT_PROCESSING_IMAGE` to `_handle_wait`, i.e. `wait_for_output()` — the
  *new output image* wait: generation overlay (`wait for finish generation`,
  600 s countdown), pool row `waiting generation`, revival arming, poll of
  `JS_CHECK_NEW_OUTPUT_V3` against the baseline until a NEW image appears or
  `timeout_ms` (120 000) elapses; the only `is_await` difference was "do not
  raise on timeout". The default stack (`DEFAULT_STACK_ORDER`, since the
  import `0eeec39`) places the block at position 4 — **before**
  `ATTACH_IMAGE` / `INSERT_PROMPT` / `SUBMIT`. On an idle page nothing has
  been submitted, so no new image can ever appear: the block waited the
  full 120 s with the generation overlay up, then emitted `success` and the
  stack went on to attach, insert, submit and download — exactly the
  observed "paste nothing, wait for a generation, then it works". The
  block's own configuration was never read: its default selector
  `div:has-text("Processing"), …` is Playwright syntax (never valid CSS)
  and no probe in the tree ever received it or `match_text`. The definition
  text ("waiting block when the system detects awaiting elements … shows
  waiting state, not error") describes an indicator poll, not an output
  wait. B11 did not introduce this; the user's first close look at the
  block rows (they render since B11) made the 2-minute dead wait visible
  and attributable.
* **Change:**
  * `browser/processing_probe.py` (new, RULE 21 — spinner from
    `probe_selectors.spinner_selector()`, file listed in the selector-literal
    lint): `build_processing_probe(selector, match_text)` → JS answering
    `{processing, indicators, skipped}`: the site spinner
    (`processing_spinner`, `div.animate-spin`), each comma-separated part of
    the block selector (`x:has-text("T")` → `x` + own/short-text filter;
    parts the browser rejects are reported in `skipped`, never fatal;
    `[aria-busy="true"]`, `.spinner`, … as plain CSS), and `match_text` as a
    short text node (≤ 40 chars) that **starts** with it — only *visible*
    elements count (`offsetParent` / computed style / non-empty rect), so
    hidden spinners and the word "processing" inside the user's own prompt
    bubble never do. `interpret_processing()` reads no reply / unparseable
    replies as idle (a broken probe must not stall the run).
  * `services/await_processing.py` (new): `handle_await_processing` — one
    probe; idle → `success "Page idle — nothing to wait for"` immediately
    (no overlay, no sleep); busy → `waiting "Page busy (spinner
    div.animate-spin) — waiting up to N ms"`, overlay "waiting for the
    running generation to finish" + pool row `waiting generation`, poll
    every `extra.poll_interval_ms` (default 1 s, clamped 250–5000) until
    idle (`success "Processing finished after …"`), timeout (`success
    "Still busy after N ms — continuing"` + warn log — the block never
    fails a job) or cancel / tab abort (`skipped`); overlay hidden and pool
    row back to busy in `finally`.
  * `single_job_runner.py`: the map entry points at the new handler;
    `_handle_wait` is WAIT_OUTPUT only again (no `is_await` leniency —
    an empty wait raises `Wait failed` as before).
* **Proof:** `tests/js/test_processing_probe.mjs` (12, the **generated**
  probe executed in jsdom: idle page with old outputs + "processing" inside
  the prompt + hidden spinners → `false`; visible spinner / `div` label /
  small wrapper / `aria-busy` / `match_text` prefix → `true` with the
  indicator; hidden ancestors excluded; rejected selector part skipped),
  `tests/test_await_processing.py` (14: default stack really puts the block
  before ATTACH; idle → 1 eval, 0 sleeps, no overlay; busy → waiting →
  success with overlay show/hide and pool marks; timeout never raises; cancel
  and tab abort → skipped; raising / empty / non-JSON probe replies → idle;
  poll clamps; `:has-text` translation; top-level comma split),
  `tests/test_single_job_runner.py::test_await_processing_is_not_the_new_output_wait`
  (the handler map + an idle page never enters `wait_for_new_output`;
  WAIT_OUTPUT still fails honestly), `tests/test_js_payload_syntax.py` and
  `tests/test_probe_selectors.py` cover the new builder. **Golden
  re-recorded on purpose:** `happy_full` — `AWAIT_PROCESSING_IMAGE` now
  `running → success` (the fake page is idle, so no `waiting` row) and one
  more `evaluate` (the indicator probe); every other golden unchanged.

## B13 — API keys tracked in the public repo; images marked `completed` sent again (`.gitignore`, `core/run_scope.py`, `batch_orchestrator.py`, `multi_page_dispatcher.py`, `run_control.py`, `run_state.py`, `core/scanner.py`, `core/models.py`, `scan_service.py`)

Design record: [`docs/archive/2026-10-09-run-scope-and-config-hygiene/design.md`](../2026-10-09-run-scope-and-config-hygiene/design.md).

### B13a — runtime data in Git

**Symptom.** Two 2Captcha keys (`config/2captcha.json`, `config/captcha_solvers.json`) visible on GitHub; the repo is public.

**Root cause.** The root squash commit `0eeec39` (2026-09-19) committed the whole `config/` tree (894 files, 6.4 MB: state with local paths, session, 278 KB undo history, 36 captcha recordings, private arena chat URL in `arena_presets.json`), `logs/`, 50 `.pyc` files and 182 saved arena.ai pages containing account e-mails. `.gitignore` already listed most of it — a rule never un-tracks a file that was committed before it existed, so the ignore was decorative.

**Fix.** `git rm --cached` of 1,126 paths (nothing deleted on disk), `.gitignore` → `config/*` + `!config/.gitkeep` + `arena webpages/`, `tests/test_repo_hygiene.py` (asks real `git ls-files`; fails on any tracked runtime path or `"api_key": "<hex>"` literal; the scanner is proven live with a planted key), `tools/pre_push_check.sh` step 0 (same check, blocks the push). Keys rotated by the owner — history still holds the old ones (every `arena/*` branch descends from `0eeec39`; a purge needs a `filter-repo` + force-push of `main` by the owner, rotation makes it hygiene rather than urgency). `tests/js/test_captcha_saved_page.mjs` keeps running where the pages exist and skips (by design, `skip: !hasFixtures`) where they don't. Invariant I-43. Commit `54cb501`.

### B13b — `completed` images sent again

**Symptom (owner).** "Marked as completed but sent a second time again." The committed `app_state.json` carried the footprint: completed items with `attempt_count` 4–6 and outputs `…_AI_3.png` / `…_AI_4.png` (the unique-suffix path is taken only when `_AI` already exists).

**Root cause.** The run-scope predicate did exclude `completed` — but it was evaluated **once**, at batch start, and duplicated in two files (`queue_scan.selected_images`, `batch_orchestrator._selected_images`). From then on both loops walked a snapshot list without ever re-reading `img.status`. Three doors led a completed image back into a loop:

1. **Second batch while one was alive** — `check_start_ready` refused only `_run_state == "running"`; after Pause (`paused`) or Stop-after-current (`stopping`) the Start button (never disabled in JS) was accepted and `start_run` **reset `_pause_requested` / `_stop_after`**, which woke the old loop. Two loops on one tab with overlapping lists: what one finished, the other sent again.
2. **Parallel → sequential fallback** — `_try_parallel` caught an `Exception` out of `dispatch_parallel` and returned `False`; `_run_sequential` then re-ran **all** of `ctx.images`, including the parallel phase's completed ones.
3. **Cancel race** — `cancel_current` set `idle` synchronously while the future was still unwinding; an immediate Start passed the gate.

**Fix.**

* `app/core/run_scope.py` — the one predicate: `RUNNABLE_STATUSES`, `is_runnable`, `run_scope` (selected ∧ runnable) and `claim_denied(img, log)` — the **claim-time re-check** that logs `⏭ Skipping <rel> — already <status>` and returns True. `queue_scan.selected_images` is its alias; the orchestrator copy is deleted.
* `batch_orchestrator._run_sequential` and `multi_page_dispatcher._run_with_sem` call `claim_denied` right before the claim (sequential: before `_run_one_image`; parallel: after the semaphore, before the page is taken). A settled image is skipped, the batch continues (RULE 9). Closes doors 2 and 3 and any door not listed. **I-44.**
* `run_state.batch_active(bridge)` (future alive?) + `run_control.check_start_ready` refuses with `batch still active` / `⚠ A batch is still active (paused / stopping / unwinding) — Resume or Cancel it first` **before** `start_run` can touch the pause/stop flags; the future is already released in `_on_coro_done`, so the gate opens by itself. Closes door 1. **I-45.**

**Also decided (owner: yes) — resume on scan (I-46).** A scan that **adds** a source whose `<base>_AI[_n].<ext>` sibling already exists enters it as `completed` with `output_path` (exact `_AI` preferred, else the highest counter; any supported extension; same folder only), `selected=False`. One directory walk (`scanner._image_files` → `_outputs_by_source`; `_build_item` carries `existing_output`; `ImageItem.from_scan_dict` adopts it). Newcomers only: a rescan never overrides an in-app status, so *Reset → Scan* does not flip an image back (boundary pinned by test). Scan log lines come from `scan_service.scan_summary` (`…, N already have _AI output (Reset to redo)`).

**Rejected.** A JS-side Start disable (would duplicate the decision, RULE 10); putting the claim check into `should_continue` with a string verdict (the loop owns the list, and the parallel worker needed the same call anyway); the first `scan_folder` cut at CC 9 (validation and AI-filter split into `_checked_root` / list comprehensions, CC 5).

**Evidence (RULE 8 — each fails with the fix removed; verified by removing it).**

| Test | Executes | Pins |
|---|---|---|
| `tests/test_run_scope.py` (15) | `is_runnable` table over every `ImageStatus`, `in_run_scope` / `run_scope`, `run_control` uses the core predicate (no panel alias), `claim_denied` logging incl. `— deselected` | one predicate, every status placed explicitly, Start and claim agree |
| `…::test_sequential_skips_an_image_deselected_mid_run` | real `_run_sequential`; the checkbox is cleared from inside `job_started` of image 1 | image 2 never claimed, `⏭ … — deselected` |
| `tests/test_batch_orchestrator.py::test_sequential_skips_settled_images_at_claim_time` | real `_run_sequential` + runner with `completed`/`skipped`/`pending` in the list | one job started, `⏭` lines, settled items untouched, batch reaches `idle` |
| `…::test_parallel_fallback_does_not_redo_completed` | `_try_parallel` whose dispatch completes image A then raises → `_run_sequential` | A not re-sent (attempt 1), B processed |
| `…::test_load_run_settings_uses_the_one_run_scope_predicate` | `_load_run_settings` | scope list; `_selected_images` stays deleted |
| `tests/test_multi_page_dispatcher_run.py::test_settled_image_never_acquires_a_page` | real `_run_with_sem` on a real `PagePool` | no page taken, no `job_started`, pool STEADY |
| `tests/test_run_control_gate.py` (6) | real `RunControlMixin.start_run` with a live `Future` in `paused` / `stopping` / `idle` | refused, nothing scheduled, flags untouched; allowed once the future is done; gate order |
| `tests/test_run_state.py::test_batch_active_follows_the_future_not_the_label` | `batch_active` | live / done / cancelled / missing |
| `tests/test_scan_resume.py` (11) | real files in `tmp_path` through `scan_folder`, `from_scan_dict`, `merge_scanned`, both scan workers | output reported, exact-then-highest, same-folder only, newcomers-only boundary, summary line |
| `tests/test_repo_hygiene.py` (15) | real `git ls-files` | no runtime path / key literal tracked; scanner finds a planted key |
| `tests/test_queue_thumbnails.py` (8) | real PNGs through `request_thumbnail` / `start_thumb_job` / `thumb_job_done` | cached → pending ticket → emit, slot always released (kept `queue_scan.py` above its coverage floor after the `selected_images` alias was deleted) |
| `tests/test_naming.py::test_parse_ai_output_is_the_one_family_definition` + existing naming / folder_ai / scanner suites | `parse_ai_output` table (counter, suffix param, case, the degenerate `_AI` stem) | one `_AI` vocabulary; `scanner._AI_FAMILY_RE` and `folder_ai._STRIP_RE` gone; Drop _AI and the scan filter behave exactly as before (equivalence gate) |
| `tests/test_scan_resume.py` (+2: `…empty_scan_as_empty_not_success`, `…worker_logs_an_empty_folder_as_a_warning`) | `scan_summary` and the real scan worker on a folder with no supported file | RULE 4 — `warn`, never a success line |
| `tests/test_progress.py` (3) | `core/progress.py` table + `AppState.recalculate_progress` | counts per key from a real mixed queue; pending = selected ∧ untouched |
| `tests/test_folder_ai.py::test_os_errors_are_reported_per_file_and_never_stop_the_sweep` | real tmp tree, `Path.rename` / `Path.unlink` refusing one file | the `errors` contract names the file, the sweep finishes the rest (RULE 4 / RULE 9); added when `folder_ai.py` lost its regex lines and slipped 0.09 pp under its per-file floor |

Goldens: unchanged (no block behaviour touched); slot surface unchanged (135).

### B13 validation pass (same day) — all 23 rules re-read, `3a5ee06` re-audited

Findings and fixes (design + numbers: [`design.md` → *Validation pass*](../2026-10-09-run-scope-and-config-hygiene/design.md)): **V1** RULE 10 — the claim-time check tested status only while Start filtered `selected ∧ runnable`; an image deselected mid-run was still sent → `in_run_scope` is the one predicate for both. **V2** RULE 16.4 — `scanner._AI_FAMILY_RE` was the fourth definition of the `_AI` family → `naming.AI_SUFFIX` + `naming.parse_ai_output`, consumed by the scan filter, the output map and `folder_ai.strip_ai_name`. **V3** RULE 4 — `Scanned 0 images, 0 new` was logged at success → `scan_summary` returns `(line, level)`, empty = `warn`. **V4/V5** readability — blank lines / type hint in `models.py`, core import first in `run_control.py`. **V6** RULE 18.2 — `models.py` reached 301 lines → progress counting extracted to `core/progress.py` (models 272, progress 49; `AppState.recalculate_progress` is the only caller). Fixture correction: `tests/test_multi_page_dispatcher_run.make_img` now builds *selected* images (a batch list never holds a deselected one); two `test_panel_slots.py` tests that wanted an unselected image say so explicitly.

## Gate evidence (2026-10-02)

| Gate | Result |
|---|---|
| `pytest -q -n 4` | 1,393 passed, 1 skipped, 3 pre-existing environmental failures (identical on `main`: `test_qt_shim_fallback`, `test_cdp_client_stub` IPv6 message, `test_verify_quality_tool` xdist flake passes alone) |
| `npm run test:js` | 142 pass / 0 fail |
| `tools/verify_quality.py --js` | PASSED — 0 fails; `--changed --base origin/main --allow-legacy --coverage-ratchet` PASSED after the reviewed baseline re-record (`docs/current/QUALITY_RECHECK.md`); coverage 85.64 % line / 81.32 % branch |
| `tests/test_bridge_slots.py` | frozen surface 134 slots, packing table updated |

## Gate evidence (2026-10-03, B6)

| Gate | Result |
|---|---|
| `pytest -q` (CI-like, no PySide6) | 1,399 passed, 1 skipped, same 2 pre-existing environmental failures (`test_qt_shim_fallback`, `test_cdp_client_stub` IPv6 message) |
| `pytest -q -n 4` with **real PySide6 6.11** (offscreen) | 1,394 passed, 3 skipped; 5 failures all in pre-existing `tests/test_panel_slots.py` — identical on `origin/main` (plain fake hosts carry a class-level `Signal()`, which has no `.emit` outside a `QObject`); `tests/test_action_blocks_defaults.py` was made env-independent (`_Sig` stand-in) |
| `npm run test:js` | 169 pass / 0 fail (142 → 169: 3 previously un-wired files + 12 new cases) |
| `tools/verify_quality.py --js` | PASSED — 0 fails (no new symbol over any hard limit) |
| `--changed --base origin/main --allow-legacy --coverage-ratchet` | 20 NO-GROWTH `file_lines` fails (+3 lines per panel export) → reviewed `--record-baseline`, then PASSED; coverage 85.65 % line / 81.33 % branch (floor 85.64 / 81.32 kept) |
| `compileall` / pyflakes undefined names / vulture @90 | clean |

## Gate evidence (2026-10-04, B7 + B8)

| Gate | Result |
|---|---|
| `pytest -q` (CI-like, no PySide6) | 1,433 passed, 1 skipped, same 2 pre-existing environmental failures (`test_qt_shim_fallback`, `test_cdp_client_stub` IPv6 message); characterization goldens unchanged |
| `npm run test:js` | 174 pass / 0 fail (169 + `test_url_list_add_persists.mjs`, wired into `test:js`) |
| `tools/verify_quality.py --js` | PASSED — 0 fails (new symbols: `page_recovery.py` max CC 8 / nest 2 / func ≤21 LOC; `transport` class 120 LOC, 9 methods) |
| `--changed --base origin/<branch> --allow-legacy --coverage-ratchet --js` | 2 in-limit growth deltas (`transport` class 116→120, `visual_click` nest 1→2) → reviewed `--record-baseline` (`docs/current/QUALITY_RECHECK.md`), then PASSED; coverage 86.09 % line / 82.01 % branch (floor raised from 85.65 / 81.33) |
| `compileall` / pyflakes on touched files / vulture | clean |

## Gate evidence (2026-10-05, B9)

| Gate | Result |
|---|---|
| `pytest -q -n 4` (CI-like, no PySide6) | 1,504 passed, 1 skipped, same 2 pre-existing environmental failures (`test_qt_shim_fallback`, `test_cdp_client_stub` IPv6 message); golden `nonreq_fail` regenerated after review (§B9), all other goldens unchanged |
| `npm run test:js` | 205 pass / 0 fail (174 + `test_dom_probes.mjs` 13 + the previously un-wired `test_output_probes.mjs` 10 / `test_recording_probes.mjs` 8) |
| `node --check` on every generated probe variant | 27/27 pass (before the fix: all 18 FIND/HIGHLIGHT variants failed with `Unexpected token 'catch'`) |
| `tools/verify_quality.py --js` | PASSED — 0 fails (`_loop_blocks` split into `_absorb_block_result` / `_record_failure` / `_soft_failures_forgiven`; file max CC stays 9) |
| `--changed --base origin/<branch> --allow-legacy --coverage-ratchet --js` | PASSED without a baseline re-record; coverage 86.15 % line / 82.14 % branch (floor 86.09 / 82.01 kept) |
| `compileall` / pyflakes on touched files | clean |

## Gate evidence (2026-10-06, B10)

| Gate | Result |
|---|---|
| `pytest -q -n 4` (CI-like, no PySide6) | 1,534 passed, 1 skipped, same 2 pre-existing environmental failures (`test_qt_shim_fallback`, `test_cdp_client_stub` IPv6 message); characterization goldens unchanged (`job_finished` is normalised to `[status, has_output]`) |
| `npm run test:js` | 218 pass / 0 fail (205 + `test_queue_live_status.mjs` 8 + `test_captcha_provider_panel.mjs` 5) |
| `tools/verify_quality.py --allow-legacy --coverage-ratchet --js` | PASSED — 0 fails / 0 warns |
| `--changed --base origin/<branch> --allow-legacy --coverage-ratchet --js` | 13 in-limit growth deltas, all feature-driven (`key_store` 9 methods / CC 6, `sdk_solver` 7 methods / 5 params, `watcher_solver` 7 slots, `service` +3 LOC, `watcher` +3 LOC) → reviewed `--record-baseline` (`docs/current/QUALITY_RECHECK.md`), then PASSED; coverage 86.37 % line / 82.34 % branch (floor raised from 86.09 / 82.01 to 86.36 / 82.33) |
| `tests/test_bridge_slots.py` | frozen surface **135** slots (+`set_captcha_provider`), packing table updated |
| `compileall` / pyflakes (whole `app/`, no undefined names) | clean |

## Gate evidence (2026-10-07, B11)

| Gate | Result |
|---|---|
| `pytest -q -n 4` (CI-like, no PySide6) | 1,536 passed, 1 skipped, same 2 pre-existing environmental failures (`test_qt_shim_fallback`, `test_cdp_client_stub` IPv6 message) |
| `npm run test:js` | 228 pass / 0 fail (218 + `test_action_blocks_render.mjs` 10) |
| `tools/verify_quality.py --allow-legacy --coverage-ratchet --js` | PASSED — 0 fails / 0 warns (the B11 comment on the `ClassVar` tables sits above the class, so `action_blocks.py` keeps its class-LOC maximum); coverage 86.37 % line / 82.34 % branch against the 86.36 / 82.33 floor; `--changed --base origin/<branch>` lane on the committed diff: PASSED |
| JS ratchet (`tools/js_metrics.js` vs `quality_baseline.json`) | every touched `action-blocks/*.js` stays at or under its recorded maxima (`block-render` 188 lines / 33 funcs / func ≤14 LOC, `block-config` 110 / 19 / CC 5, `block-store` 326 / 46 / CC 8, facade 220 / 116); new `block-views.js` (138) and `block-fields.js` (154) meet the hard limits |
| `tests/test_bridge_slots.py` | frozen surface **135** slots — unchanged (pure UI fix) |
| `compileall` / pyflakes | clean |

## Gate evidence (2026-10-08, B12)

| Gate | Result |
|---|---|
| `pytest -q -n 4` (CI-like, no PySide6) | 1,554 passed, 1 skipped, same 2 pre-existing environmental failures (`test_qt_shim_fallback`, `test_cdp_client_stub` IPv6 message) |
| `npm run test:js` | 240 pass / 0 fail (228 + `test_processing_probe.mjs` 12) |
| `tools/verify_quality.py --allow-legacy --coverage-ratchet --js` | PASSED — 0 fails / 0 warns; coverage 86.55 % line / 82.63 % branch against the 86.36 / 82.33 floor (both new modules 100 % line + branch); `--changed --base origin/<branch>` lane on the committed diff: PASSED |
| Goldens | `happy_full` re-recorded (documented in §B12); the other 11 scenario goldens byte-identical |
| `tests/test_bridge_slots.py` | frozen surface **135** slots — unchanged (no new slot) |
| `compileall` / pyflakes | clean |

## Gate evidence (2026-10-09, B13)

| Gate | Result |
|---|---|
| `pytest -q -n 4` (CI-like, no PySide6) | 1,621 passed, 1 skipped, same 2 pre-existing environmental failures deselected (`test_qt_shim_fallback`, `test_cdp_client_stub` IPv6 message); one timing flake seen once under the coverage tracer (`test_cooldown_service.py::test_wait_for_batch_ready_waits_for_zero`, untouched since the root commit, 3/3 green re-run) |
| `npm run test:js` | 240 pass / 0 fail (unchanged — no JS touched) |
| `tools/verify_quality.py --allow-legacy --coverage-ratchet --js` | PASSED — 0 fails / 0 warns; coverage **87.03 % line / 83.25 % branch** against the 86.36 / 82.33 floor (`run_scope.py`, `progress.py`, `models.py`, `folder_ai.py` 100 % line; `queue_scan.py` 52.24 → 74.91 %); `--changed-files` on the 12 touched production files: 0 fails, no ratchet maximum grown; `--changed --base origin/<branch>` lane on the committed diff: PASSED (see commit) |
| Goldens | all 12 scenario goldens byte-identical |
| `tests/test_bridge_slots.py` | frozen surface **135** slots — unchanged |
| `compileall` / pyflakes | clean |
| Repo hygiene | `git ls-files -- config logs 'arena webpages' '*.pyc'` → `config/.gitkeep` only; `git grep` for `"api_key": "<hex>"` → nothing |
