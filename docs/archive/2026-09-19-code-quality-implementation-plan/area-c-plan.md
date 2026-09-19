# Area C Plan — Complexity Hotspots C1-C8

**Based on** `metrics-baseline-2026-09-18.md` + `area-plans-prioritized.md` + `AGENT_RULES.md` RULE 16/18/19

## Current metrics (2026-09-19)

| Symbol | File | LOC | CC | Cog | Nest | Methods | File LOC | MI | Coverage |
|---|---|---|---|---|---|---|---|---|
| check_once | app/services/watcher.py:169 | 124 | 35 | 82 | — | — | 306 | 38.5 | 27% |
| WatcherService | watcher.py | — | — | — | — | 15 | 306 | 38.5 | 27% |
| _connect_inner | app/browser/cdp_client.py:345 | 106 | 27 | 41 | — | — | 655 | 9.39 | 9.3% |
| fetch_tabs_sync | cdp_client.py:110 | 36 | 16 | — | 5 | — | 655 | 9.39 | 9.3% |
| CDPClient | cdp_client.py | 469 | — | — | — | 22 | 655 | 9.39 | 9.3% |
| highlight_selector | app/browser/cdp_arena.py:463 | — | 13 | — | — | — | 585 | 21.95 | 29.4% |
| CDPArenaController | cdp_arena.py | 371 | — | — | — | 30 | 585 | 21.95 | 29.4% |
| validate_downloaded_file | app/services/verification.py:73 | 42 | 14 | — | 5 | — | 114 | — | 38% |
| reconcile_with_filesystem | app/core/persistence.py:69 | 101 | 21 | — | — | — | 169 | — | — |
| scan_folder | app/core/scanner.py:9 | 66 | 13 | — | — | — | 109 | — | — |
| undo | app/core/undo_service.py | 38 | 12 | — | — | — | 112 | — | — |
| normalize_grid_tree | app/core/layout_service.py | — | — | 21 | — | — | 187 | — | — |
| get_output_path | app/core/naming.py | — | — | — | — | — | 90 | — | — | 6 params |
| wait_for_new_output_loop | app/browser/output_wait.py | — | 16 | — | — | — | 234 | — | — | 5 params |
| build_highlight_rect_js | app/browser/dom_highlight.py | — | — | — | — | — | 678 | 41.43 | 35% | 7 params |
| PresetStore | app/persistence/preset_store.py | — | — | — | — | 22 | 177 | — | — |
| main_window.__init__ | app/ui/main_window.py | 31 | — | — | — | — | 162 | — | — |
| action-blocks.js | app/ui/web/js/panels/action-blocks.js | 836 | 90 | — | — | — | 836 | n/a | untracked | anon 169 LOC |
| setupBridgeListeners | arena-app.js | 164 | 66 | — | — | — | 332 | — | — |
| JS dup | cdp.js ↔ url-list.js | 17-line clone | — | — | — | — | — | — | — |

## RULE 19 order

1. Nesting >4 → guard, early return, flatten
2. CC >10 → dispatch table, not foo_part1
3. Cognitive >15 → name predicates
4. LOC >30 → extract helper with real responsibility name

Verify after every step: `python tools/verify_quality.py --changed` and `pytest -m "not slow and not e2e"`

## C1 — watcher decision split

**Now:** 124 LOC CC35 cog82, class 269 LOC (306 file) — concentrated tail

**Target:** 0 fails, file ≤300, funcs 4-20, CC≤10, cog≤15, nest≤4, cov 27→80%

**Steps (≤20 LOC funcs):**
- C1.1: Create `watcher_overlay.py` — pure overlay message builders, `build_captcha_msg`, `build_generation_msg`, `should_show_overlay`, `should_clear_overlay` — each ≤15 LOC, CC≤5
- C1.2: Extract `_get_cdp()` ≤5 LOC, `_check_captcha()` ≤10 LOC (guard), `_check_generation()` ≤10 LOC
- C1.3: Extract `_handle_captcha()` ≤20 LOC, `_handle_generation()` ≤20 LOC, `_handle_clear_if_needed()` ≤20 LOC — dispatch table for waiting_kind
- C1.4: Extract `_pause_jobs()`, `_resume_jobs()`, `_show_overlay()`, `_hide_overlay()` each ≤10 LOC
- C1.5: `check_once` orchestrator ≤20 LOC: get_cdp → check_captcha → handle → check_generation → handle → clear → notify
- C1.6: Tests: `tests/test_watcher.py` already exists, add scenarios: captcha detected, generation detected, clear, timeout, no cdp — each test fails if target deleted (RULE 8)

**Dishonest reductions rejected:**
- No `check_once_part1/part2` split — extraction must have real responsibility name (`_handle_captcha` is real decision)
- No `**kwargs` dodge for config
- No deleting real decision to lower CC (4 binary outcomes → CC≥5 floor)

## C2 — cdp_client package split

**Now:** 655 LOC, class 469 LOC 22 methods, 15 fails, _connect_inner CC27, fetch_tabs_sync 36 LOC nest5

**Target:** Package `app/browser/cdp/` with `transport.py` (socket+lock I-22), `connect.py`, `tabs.py`, `probe.py`, `cdp_client.py` ≤150 facade, 15→0 fails, cov 9→80%

**Steps:**
- C2.1: Create `app/browser/cdp/` package, move `_is_port_open`, `_fetch_json_sync`, `CANDIDATE_HOSTS` to `transport.py` — pure, no Qt, ≤150 lines, CC≤7
- C2.2: Move `_normalize_ws_url`, `_is_devtools_url`, `_parse_tabs`, `_filter_real_tabs`, `fetch_tabs_sync`, `diagnose_sync` to `tabs.py` — pure protocol, ≤150 lines
- C2.3: Move `CDPClient._connect_inner` logic to `connect.py` — split into `_build_candidates()`, `_try_candidate()`, `_enable_domains()` each ≤20 LOC, CC≤7, nesting flatten via early return
- C2.4: Move `query_selector`, `set_file_input_files`, `attach_image_cdp`, `highlight_element` to `probe.py` — DOM helpers
- C2.5: `cdp_client.py` facade ≤150 lines: only `__init__`, `is_connected`, `set_host_port`, `get_host_port`, delegates to `transport`, `tabs`, `connect`, `probe` — 1-5 lines per method
- C2.6: Tests: `tests/test_cdp_client.py` etc., mock websocket, test candidate building, deduplication, lock loop mismatch

**Anti-gaming:** No deleting real decision (4 candidate hosts + 3 ws variants + constructed → CC floor)

## C3 — cdp_arena highlight/attach/submit

**Now:** 585 LOC, class 371 LOC 30 methods, 3 fails, highlight_selector CC13

**Target:** Split into `cdp_arena_highlight.py`, `attach.py`, `submit.py`, root ≤150 composition, 3→0 fails, cov 29→80%

**Steps:**
- C3.1: Extract `highlight_selector` CC13 → guard clauses + `_build_highlight_spec()` + `_evaluate_highlight()` each ≤15 LOC, CC≤7
- C3.2: Create `cdp_arena/highlight.py` — `show_watcher_overlay`, `hide_watcher_overlay`, `highlight_selector`, `clear_highlights` — each ≤20 LOC
- C3.3: Create `cdp_arena/attach.py` — `attach_image`, `verify_attachment`
- C3.4: Create `cdp_arena/submit.py` — `insert_prompt`, `verify_prompt`, `submit`, `submit_when_ready`, `_poll_send_state`
- C3.5: Root `cdp_arena.py` ≤150 facade composition, delegates to highlight/attach/submit + output_* modules
- C3.6: Tests: fake CDP client, test highlight, attach, submit flows

## C4 — verification guard clauses

**Now:** `validate_downloaded_file` 42 LOC CC14 nest5, file 114 LOC

**Target:** ≤15 LOC orchestrator, `ValidationResult` dataclass, 3→0 fails, cov 38→90%

**Steps:**
- C4.1: Create `ValidationResult` dataclass `valid, error, metadata`
- C4.2: Extract `is_html_response(data)`, `has_valid_image_dimensions(data)`, `is_nonempty(data)`, `detect_format(data)` each ≤10 LOC, CC≤3, predicate names
- C4.3: `validate_downloaded_file` orchestrator ≤15 LOC: guard empty → guard html → detect format → PIL verify → content-type fallback — early returns, no nesting >3
- C4.4: Tests: empty, html, png, jpg, webp, bmp, invalid, content-type image/* — each fails if deleted

## C5 — core predicate tables + param objects

**Now:** `reconcile_with_filesystem` 101 LOC CC21, `scan_folder` 66 LOC CC13, `undo` 38 LOC CC12, `normalize_grid_tree` cog21, `get_output_path` 6 params, file `action_blocks.py` 716 LOC

**Target:** 5→0 fails, each ≥80% cov

**Steps:**
- C5.1: `scanner.py` — predicate table for supported types + ignore AI suffix, extract `_should_include_file()`, `_is_ai_suffix()` each ≤10 LOC
- C5.2: `persistence.py` `reconcile_with_filesystem` — dispatch table per file state (exists, missing, new), extract `_handle_existing()`, `_handle_missing()`, `_handle_new()` ≤20 LOC each, CC≤7
- C5.3: `undo_service.py` — dispatch table per undo kind (grid, urls, folder, etc.) instead of if/elif chain, `OutputSpec`/`ImageSpec` param objects
- C5.4: `layout_service.py` `normalize_grid_tree` — name predicates `is_valid_version`, `is_valid_node`, `sums_to_100`, extract helpers
- C5.5: `naming.py` `get_output_path` 6 params → `OutputSpec` dataclass `source_path, suffix, preserve_format, overwrite, downloaded_ext, unique_template` — params 6→1, plus `ImageSpec`
- C5.6: `action_blocks.py` — data/behaviour split, move validation to `action_blocks/validation.py`

## C6 — output_wait / dom_highlight / preset_store / main_window

**Now:** `wait_for_new_output_loop` 5 params CC16, `build_highlight_rect_js` 7 params, `preset_store` 22 methods, `main_window.__init__` 31 LOC

**Target:** 7→0 fails

**Steps:**
- C6.1: `output_wait.py` — `WaitSpec` dataclass `old_srcs, correlation_id, old_outputs, timeout, poll_interval` — params 5→1, extract `_poll_once()` ≤20 LOC
- C6.2: `dom_highlight.py` — `HighlightSpec` dataclass `color, caption, duration, clear_first, label_selector, match_text, match_mode` — 7 params→1, split `build_highlight_js` (JS literal exception) but Python wrapper CC≤10
- C6.3: `preset_store.py` 22 methods → split `preset_store_read.py` + `preset_store_write.py`, facade ≤150, ≤10 methods each
- C6.4: `main_window.py` `__init__` 31 LOC → `_build_services()` + `_build_ui()` each ≤15 LOC, `__init__` ≤20 LOC

## C7 — JS panels split

**Now:** `action-blocks.js` 838 anon 169 LOC CC90, `arena-app.js` `setupBridgeListeners` 164 LOC CC66, 48 funcs >30, 24 nesting>4, 8 files>300

**Target:** funcs>30 48→≤10, nest>4 24→0, files>300 8→≤3, each pure func gets `tests/js/*.mjs` test Tier A `node --test`

**Steps:**
- C7.1: Extract `block-store.js` — state management for blocks (CRUD, validation)
- C7.2: Extract `block-config.js` — config schema + defaults
- C7.3: Extract `block-render.js` — rendering rows, row-state helpers, status rendering
- C7.4: `arena-app.js` listener registry table instead of if/elif chain — `BRIDGE_LISTENERS = {grid_layout_changed: ..., arena_state_updated: ...}` — each handler ≤20 LOC
- C7.5: Tests: Tier A `node --test` for each pure func, payload-equality test asserts rendered JS string normalised whitespace

## C8 — JS dup + c8

**Now:** `cdp.js` ↔ `url-list.js` 17-line clone, JS coverage untracked

**Target:** dup gone, JS cov number exists

**Steps:**
- C8.1: Move 17-line clone to `core/ui-helpers.js` — shared helper
- C8.2: Add `c8` instrumentation `npm run test:js:cov` → `c8 node --test tests/js/*` → coverage number
- C8.3: Update `metrics_report.py` to include JS coverage

## Expected deltas (Area C)

- watcher 124→≤20, CC35→≤7, cov 27→80%
- cdp_client 647→≤150 facade + 4×≤150 modules, 15→0 fails, cov 9→80%
- cdp_arena 585→≤150 facade + 3×≤150, 3→0 fails, cov 29→80%
- verification 42→15, CC14→≤5, cov 38→90%
- core 5→0 fails, each ≥80%
- output_wait/dom_highlight/preset_store/main_window 7→0 fails
- JS >30 48→≤10, nest>4 24→0, files>300 8→≤3
- dup 1.59%→≤1%

## Risks

- Behaviour drift → characterization tests before deletion (Area A1 goldens)
- Slot breakage → `test_bridge_slots.py`
- Async semantics → scheduling seam in `run_state.py`
- Anti-gaming: No `foo_part1`, no `**kwargs` dodge, dispatch tables are data not branch hiding

## RULE 18 recheck at end

- func 4-20, file 150-300, module 5-15, context 60-200
- Every deviation carries `ideal-size: reason=constraint`
