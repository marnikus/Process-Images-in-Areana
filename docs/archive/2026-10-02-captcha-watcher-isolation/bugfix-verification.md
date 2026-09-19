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

## Gate evidence (2026-10-04, B8)

| Gate | Result |
|---|---|
| `pytest -q` (CI-like, no PySide6) | 1,433 passed, 1 skipped, same 2 pre-existing environmental failures (`test_qt_shim_fallback`, `test_cdp_client_stub` IPv6 message); characterization goldens unchanged |
| `npm run test:js` | 169 pass / 0 fail (no JS change) |
| `tools/verify_quality.py --js` | PASSED — 0 fails (new symbols: `page_recovery.py` max CC 8 / nest 2 / func ≤21 LOC; `transport` class 120 LOC, 9 methods) |
| `--changed --base origin/<branch> --allow-legacy --coverage-ratchet --js` | 2 in-limit growth deltas (`transport` class 116→120, `visual_click` nest 1→2) → reviewed `--record-baseline` (`docs/current/QUALITY_RECHECK.md`), then PASSED; coverage 86.09 % line / 82.01 % branch (floor raised from 85.65 / 81.33) |
| `compileall` / pyflakes on touched files / vulture | clean |
