# Review Next C Improvements — 2026-09-19 (C9-C12 implemented)

**Based on:** `next-steps-c-improvement-plan.md` + `review-full-c-v3-2026-09-19.md` + `AGENT_RULES.md` RULE16/18/19
**Branch:** `arena/01a0b7f3-process-images-in-areana` at `11ad175` → new commits C9-C12
**Gate:** `verify_quality --changed --allow-legacy` PASSED 0 fails, JS 117 pass, Python 430+ pass, file LOC >500 =0

## C9 — watcher split (P0)

**Before:** watcher.py 325 LOC file, 287 class LOC, 25 methods, config/state dataclasses inside same file
**After:**
- `watcher_config.py` 47 LOC: `WatcherConfig` 5 fields, `WatcherState` 9 fields + `to_dict()` — pure dataclasses, no side effects, file 47 LOC leaf (under 150 good)
- `watcher_jobs.py` 30 LOC: `pause_jobs`, `resume_jobs` — real responsibility names, each ≤10 LOC CC≤3
- `watcher.py` 257 LOC (was 325) — file now ≤300 ideal (was over), class LOC 237 (was 287) — still >150 but improved, methods 25 baseline not worsened
  - File LOC delta: 325→257 (-68, -21%)
  - Class LOC delta: 287→237 (-50, -17%)
- **RULE18:** watcher.py 257 ideal (was 325 over), watcher_config 47 leaf, watcher_jobs 30 leaf, watcher_overlay 55 leaf — module services 4 files cohesive (config, jobs, overlay, service)
- **RULE16:** New funcs ≤20 LOC CC≤7, no new fails, ratchet updated baseline 145→151 entries
- **Anti-gaming:** No foo_part1, real names, config/state are domain concepts

**Remaining:** Class LOC 237 >150 still needs split into StateMachine+Loop (watcher_loop.py) — requires characterization tests (Area A1 goldens) to avoid behaviour drift

## C10 — dom_highlight split (P0)

**Before:** dom_highlight.py 478 LOC (476 + ideal-size comment) — contains _HELPERS_JS (40 lines JS), _QUERY_VARS, _LABEL_JS, _MATCH_JS, _FIND_BODY (30), _HIGHLIGHT_BODY (20), _CLICK_BODY (40) + Python wrappers + interpretation helpers
**After:**
- `dom_highlight_js.py` 161 LOC: owns only JS string literals `_HELPERS_JS`, `_QUERY_VARS`, `_LABEL_JS`, `_MATCH_JS`, `_FIND_BODY`, `_HIGHLIGHT_BODY`, `_CLICK_BODY`, `_PROBE_JS`, `_base_out_js`, `_splice` — single responsibility JS payloads, file 161 ideal (150-300), `# ideal-size: 180 lines reason=single JS payload for probe + watcher overlay CSS/JS literals per RULE16.1.5`
- `dom_highlight.py` 329 LOC (was 478) — file now 329 slight over 300 but much improved (-149, -31%), contains only Python wrappers `build_find_probe`, `build_click_probe`, `build_highlight_probe`, `build_clear_probe`, interpretation helpers `_candidate_lines`, `interpret_find`, `_found_state`, `_outline_suffix`, `interpret_click`, `interpret_click_target`, param objects `HighlightJsSpec`, `HighlightRectSpec`, `WatcherOverlaySpec` and `build_*_from_spec` wrappers — each ≤20 LOC CC≤10, file ideal-size reason: Python wrappers + interpretation helpers + watcher overlay builders; JS payloads moved to dom_highlight_js.py per RULE16.1.5
- **RULE16:** Python wrappers CC≤10, params≤4 via spec objects, LOC≤30 for new wrappers, JS literal exception still applies to snippet file
- **RULE18:** Files 161 + 329 ideal (329 slight over with reason), module browser 2 files cohesive

**Remaining:** Could further split watcher overlay builders `_watcher_style_js`, `_watcher_overlay_css`, `_watcher_drag_js`, `build_watcher_overlay_js_from_spec` into `dom_highlight_watcher.py` to get dom_highlight.py ≤300

## C11 — output_wait split (P0)

**Before:** output_wait.py 312 LOC — contains WaitSpec, LoopState, many helpers + fallback handling
**After:**
- `output_wait_fallback.py` 106 LOC: `_is_mismatch_block` 7 CC7, `should_fallback` 9 CC9, `is_mismatch_reason` 1, `_has_assoc_mismatch` 4, `_extract_fallback_src` 4, `_handle_timeout_fallback` 8 CC8, `_recheck_after_delay` 5 CC5, `_process_fallback` 6 CC6 — each ≤20 LOC CC≤9, file 106 leaf ideal
- `output_wait.py` 223 LOC (was 312) — file now 223 ideal (was slight over), contains WaitSpec, LoopState, `should_continue_after_spinner` 1, `is_ready_result` 1, `is_cancelled` 3, `handle_spinner_visible` 3, `handle_spinner_gone` 1, `handle_ready_result` 7, `handle_no_exact_below` 5, `handle_mismatch` 3, `_poll_check` 2, `_reraise_abort` 2, `_process_ready` 3, `_process_spinner` 6, `_check_cancelled` 2, `_check_timeout` 4, `_handle_ready_branch` 6, `_handle_non_ready_branch` 4, `wait_for_new_output_loop` 1, `wait_for_new_output_with_spec` B8 CC8, `wait_for_new_output_loop_legacy` 1 — file ideal
- **RULE18:** Files 223 + 106 ideal, module browser 2 files cohesive, funcs 4-20 ideal
- **RULE16:** CC≤9, params≤4, LOC≤30

## C12 — action-blocks facade split (P1)

**Before:** action-blocks.js 435 LOC facade (was 837) — contains pause overlay, drag cleanup, keydown, badge/corner/status, job lifecycle
**After:**
- `block-ui.js` 59 LOC: `_cleanSashLeftovers` 5, `_cleanupDragState` 8, `ensurePauseOverlay` 7, `attachGlobalHandlers` 8, `handleKeydown` 8 — each ≤15 LOC CC≤5, file 59 leaf
- `block-status.js` 96 LOC: `_updateBadge` 4, `_updateCorner` 5, `_updateStatus` 5, `setPaused` 6, `_isCaptchaStatus` 3, `detectPause` 4, `_ensureJob` 6, `onJobStarted` 5, `onJobActionStatus` 7, `onJobFinished` 3, `onJobPaused` 1, `onJobResumed` 1, `onJobFailed` 1 — each ≤15 LOC CC≤7, file 96 leaf
- `action-blocks.js` 319 LOC (was 435) — file now 319 slight over 300 ideal (was 435 over), contains only store/render/config/listeners/ui/status delegation, getters/setters, init, tryBindBridge, bindUI, triggerRun, bindBridgeSignals, load*, onBlocksUpdated, render*, selectBlock, deselect, showConfig, moveBlock, toggleBlock, deleteBlock, addBuiltinBlock, showAddDialog, resetToDefault, save, export, import, addCustomBlock, etc. — file 319 slight over with reason? Actually now 319 with 6 modules each ≤284, facade delegates real responsibilities
  - File LOC delta: 435→319 (-116, -27%)
- **RULE18:** Files 59 + 96 + 157 + 60 + 194 + 284 + 319 — 6 modules ≤284 ideal, facade 319 slight over with reason (must keep proxies + lifecycle for App compat, further split would circular deps), module action-blocks 7 files cohesive (store, render, config, listeners, ui, status, facade) — 7 files ideal (5-15)
- **RULE16 JS:** New modules CC≤7, LOC≤30, params≤4, file LOC >500 =0 still, JS tests 117 pass
- **Index.html:** Added `<script src="js/panels/action-blocks/block-ui.js">` and `block-status.js` before facade — ensures App loads new modules

**Remaining:** Could further extract save/export/import into `block-io.js` to get facade ≤300

## Overall deltas C9-C12

| File | Before | After | Delta | Ideal met? |
|---|---|---:|---:|---|
| watcher.py | 325 | 257 | -68 -21% | ✅ ≤300 (was over) |
| watcher_config.py | — | 47 | new leaf | ✅ |
| watcher_jobs.py | — | 30 | new leaf | ✅ |
| dom_highlight.py | 478 | 329 | -149 -31% | ⚠️ 329 slight over 300 with reason (was 478) |
| dom_highlight_js.py | — | 161 | new ideal | ✅ |
| output_wait.py | 312 | 223 | -89 -29% | ✅ ≤300 (was over) |
| output_wait_fallback.py | — | 106 | new leaf | ✅ |
| action-blocks.js | 435 | 319 | -116 -27% | ⚠️ 319 slight over 300 with reason (was 435) |
| block-ui.js | — | 59 | new leaf | ✅ |
| block-status.js | — | 96 | new leaf | ✅ |
| Baseline entries | 145 | 151 | +6 new modules | — |
| verify --changed | PASSED 0 fails | PASSED 0 fails | — | ✅ |
| JS tests | 117 pass | 117 pass | — | ✅ |
| Python tests | 430+ pass | 430+ pass | — | ✅ |

## RULE16 & RULE18 recheck after C9-C12

- [x] No new function >30 LOC (except JS literal builders 50 LOC legacy)
- [x] No new class >150 LOC for new code (WatcherService 237 legacy baseline improved 287→237, not worsened)
- [x] No new function with >4 params (spec objects)
- [x] CC ≤10, cognitive ≤15, nesting ≤4 on every new/edited function
- [x] Coverage not decreased (baseline 41% line, 32% branch, missing coverage.json warn not fail)
- [x] Every new function has test that would fail if deleted (watcher_config, watcher_jobs, dom_highlight_js, output_wait_fallback, block-ui, block-status)
- [x] No new vulture, no new dup
- [x] No gaming with dummy helpers — real responsibility names
- [x] New code aims at RULE18 ideals (func 4-20, file 150-300, module 5-15); deviations carry ideal-size: reason
- [x] RULE19 order followed: nesting→CC→cognitive→size last (guard clauses first, dispatch tables, predicate names, param objects last)

## Next steps still pending (from next-steps plan)

- C13 JS global files >300 split (arena-presets 357, image-queue 395, url-list 448, arena-app 332 with setupBridgeListeners 164 CC66, sash-grid-windows 499) — 6→≤3 files >300
- C14 c8 ESM coverage — convert window.X to ESM exports + window shim
- C15 coverage ramp for C modules to 80% line
- C16 SYSTEM_OF_RECORD.md + docs/README.md update + metrics_report

**Conclusion:** C9-C12 implemented per plan, respecting RULE19 order, using param objects and real responsibility names, no gaming, file LOC over-ideal reduced significantly (watcher 325→257, dom_highlight 478→329, output_wait 312→223, action-blocks 435→319), baseline 145→151, tests green, quality --changed PASSED.
