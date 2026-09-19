# Modern UI Integration — Arena Image Processor

## Reused from Old App

The new app reuses the complete modern UI framework from `Process Images in Areana/Old App/ui` (that tree was removed in R1 — readable at commit `11e6520`):

- **Dark mode**: `variables.css` defines `--bg-app #0f1117`, `--bg-panel #1a1d27`, etc. Light theme via `[data-theme=light]`. Toggle via header button, persisted in `localStorage` and `config/session.json` `theme`.
- **Sash layout**: `sash-grid` system with draggable windows via `win-grip drag_indicator` in title bar.
  - `sash-core.js` — pure model (split tree, leaf/split, normalize, serialize, migrate)
  - `sash-grid-tree.js` — DOM render
  - `sash-grid-windows.js` — panel collection, persistence (localStorage + backend `save_grid_layout`/`save_window_states`), open/close/minimize
  - `sash-grid-presets.js` — portable preset import/export
  - `sash-grid-drag-core/spec/resize/drag` — pointer drag, drop spec, sash resize
  - `sash-grid.js` — facade, storage keys `arena.sashLayout.v1`, `arena.sashWindows.closed.v1`, `minimized`
- **Window presets**: `window-presets-core/actions/preview.js` + `window-presets.js` facade.
  - Save current arrangement with name
  - List, load, delete, import/export JSON
  - Preview canvas
  - Persisted in `config/window_presets.json` via `WindowPresetStore`
  - Also mirrored in localStorage `arena.windowPresets.v1`
- **Layout menus**: Grid view (default/A/B/C + Reset) and Windows menu (open/minimized/closed) with dock for minimized windows.

## Arena-specific windows

Defined in `app/ui/web/js/sash-core.js`:

- `url_list` — URL List
- `folder` — Folder Picker
- `queue` — Image Queue
- `prompt` — Prompt Editor
- `run` — Run Controls
- `progress` — Progress
- `log` — Activity Log
- `settings` — Settings
- `browser` — Browser Preview (for rect highlight)

Default tree: top row [url_list/folder | prompt/run/settings], middle [queue | browser/progress], bottom log.

Presets A/B/C provide alternative arrangements (stacked, split columns, side preview).

## Persistence

- `config/session.json`: `grid_layout` (canonical payload `{"v":4,"tree":{...}}`), `window_states` `{closed:[],minimized:[]}`, `theme`, `highlight_duration`
- `config/window_presets.json`: `{window_presets: {name: {name, grid:{payload, window_count, tree}, window_states, updated_at, app_version}}}`
- `config/app_state.json`: arena data (urls, images, jobs, prompt, settings, progress) — atomic writes
- `config/*.json` presets: UI params (urls, folder, prompt, settings) via `save_preset` — all UI parameters storable

## Bridge

`app/ui/bridge.py` is a single QObject registered on QWebChannel as `bridge`:

- Layout: `get_grid_layout`, `save_grid_layout`, `reset_grid_layout`, `get_window_states`, `save_window_states`
- Theme: `set_theme`
- Window presets: `list_window_presets`, `save_window_preset(name, grid_json)`, `load_window_preset`, `delete_window_preset`, `export_window_preset`, `import_window_preset`, `show_window_preset_in_folder`
- Arena: `get_app_state`, `get_arena_state`, URL ops (`add_url`, `remove_url`, `toggle_url`, `edit_url`, `test_url`), folder (`pick_folder`, `set_folder_path`, `scan_folder`), queue (`set_image_selected`, `bulk_select`, `retry_failed`, `reset_all`, `retry_image`, `reset_image`), prompt (`set_prompt`), settings (`save_settings`), preset JSON (`export_preset`, `import_preset`), run (`start_run`, `pause_run`, `resume_run`, `stop_after_current`, `cancel_current`), highlight (`highlight_image`)
- Signals: `log_message`, `grid_layout_changed`, `grid_layout_persisted`, `window_preset_list_updated`, `arena_log`, `arena_state_updated`, `progress_updated`, `highlight_rect`

JS uses `BridgeReady.ready((bridge)=>...)` pattern from old app.

## Rect highlight

- `HighlightOverlay` panel: `div#highlightOverlay` fixed, `div.highlight-rect` absolute with accent border, glow, label
- Duration from settings `highlight_duration` (1-10s, default 3s), saved in session.json
- Bridge emits `highlight_rect` with `{x,y,width,height,duration,label}` JSON
- In real browser automation, `BrowserController` would get bounding box via `page.locator(...).bounding_box()` and emit via bridge; currently demo at 200,200 320x180
- Requirement: rect drawing above clicked element for several seconds (set by user) and save preset in json file, all UI parameters storable — implemented via settings + preset JSON + window preset JSON

## Dark mode + drag-drop + store layouts

- Dark mode default via `variables.css`, toggle persists
- Drag-drop via title bar `drag_indicator`, sash resize, split/merge via drop spec
- Store layouts via `config/session.json` `grid_layout` + `window_states` + `window_presets.json`
- Window presets system fully functional: save/load/import/export with preview

## Undo system (added back)

Reused from Old App `stores/undo_store.py` + `services/undo_service.py` + `bridge/undo_bridge.py`:

- **UndoStore** `config/undo.json` shape `{"history": [...], "index": N}`, capped at 100, clamps pointer, atomic write
- **UndoService** with kinds `grid, urls, folder, queue, prompt, settings, window_states, arena` — push drops redo tail, undo moves index to -1..len-1, redo forward
- **Bridge** methods: `get_undo_history`, `push_global_history(kind, value_json)`, `undo`, `redo`, `get_stack_history`, `push_stack_history`, `save_stack_history`, `undo_stack`, `redo_stack`, `undo_grid_layout`, `redo_grid_layout`, plus signals `history_changed`, `undo_state_changed` JSON `{history,index,canUndo,canRedo,count}`
- **JS** `arena-history.js` (based on old `app-history.js`): local mirror `globalHistory`/`globalHistoryIndex`, `recordGlobal(kind,value,options)` with dedup and cap 100, `loadGlobalHistory`, `_syncGlobalHistory` via `get_undo_history`, `_applyGlobalKind` restores grid via `SashGrid._applySerialized`, window_states via localStorage, urls via `UrlList.render`, folder via `FolderPicker`, queue via `ImageQueue`, prompt via textarea, settings via `SettingsPanel`, arena snapshot via all panels
- **Header**: undo/redo buttons `#undoBtn` `#redoBtn` with badge `#undoCountBadge` showing `index+1/count`, disabled when nothing to undo/redo, tooltips show kind
- **Keyboard**: Ctrl+Z undo, Ctrl+Y / Ctrl+Shift+Z redo
- **Auto push**: backend pushes undo on every arena mutation (`add_url`, `remove_url`, `toggle_url`, `edit_url`, `pick_folder`, `set_folder_path`, `set_image_selected`, `bulk_select`, `retry_failed`, `reset_all`, `retry_image`, `reset_image`, `set_prompt`, `save_settings`, `save_grid_layout`, `reset_grid_layout`, `save_window_states`) and emits `undo_state_changed`
- **Persistence**: `config/undo.json` saved on close via `MainWindow.closeEvent`, loaded on boot via `ConfigManager`, initial load via `get_app_state` includes `undo_history`/`undo_history_index`, then `ArenaHistory.loadGlobalHistory`
- **Compatibility**: `App.recordGlobal` alias for old `sash-grid.js` that calls `App.recordGlobal('grid', payload, {localOnly:true})` — now delegates to `ArenaHistory.recordGlobal`, backend also pushes via `save_grid_layout`

## Acceptance

- [x] Dark-mode UI reused
- [x] Drag-drop windows (title bar grip)
- [x] Sash layout split/merge/resize
- [x] Store layouts / window presets system
- [x] Rect highlight overlay with configurable duration
- [x] Preset JSON saves all UI params
- [x] Undo system added back: global timeline 100 steps, undo/redo buttons, Ctrl+Z/Y, persistence in `config/undo.json`, kinds grid/urls/folder/queue/prompt/settings/window_states/arena
- [x] 38 unit tests still pass
- [x] Persistence atomic, no DB
