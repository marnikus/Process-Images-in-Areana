# Bugfix verification — 2026-10-02 release

Five UI defects shipped with the Captcha Watcher isolation. Each row: what
the user saw → what the code did → what changed → the test that pins it.

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

## Gate evidence

| Gate | Result |
|---|---|
| `pytest -q -n 4` | 1,393 passed, 1 skipped, 3 pre-existing environmental failures (identical on `main`: `test_qt_shim_fallback`, `test_cdp_client_stub` IPv6 message, `test_verify_quality_tool` xdist flake passes alone) |
| `npm run test:js` | 142 pass / 0 fail |
| `tools/verify_quality.py --js` | PASSED — 0 fails, 1 warn (`coverage.json` not generated in this sandbox) |
| `tests/test_bridge_slots.py` | frozen surface 134 slots, packing table updated |
