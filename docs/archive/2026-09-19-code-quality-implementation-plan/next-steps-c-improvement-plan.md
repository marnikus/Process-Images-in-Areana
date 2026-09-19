# Next Steps C Improvement Plan — 2026-09-19

**Based on:** `review-full-c-v3-2026-09-19.md` + `AGENT_RULES.md` RULE16/18/19 + `area-c-plan.md`
**Status:** Planning only, no production code yet (RULE17)
**Gate now:** `verify_quality --changed --allow-legacy` PASSED 0 fails 75 warns (legacy bridge 355 etc.), file LOC >500 =0, JS 117 tests pass, Python 430+ pass (excluding PySide6), coverage 41% line 32% branch baseline

## 1. IMPLEMENTATION PROCESS (RULE16 §16.6)

1. **Understand fully** — Measure current radon, target, gaps (this doc)
2. **Research & Design** — Record current numbers, target numbers, dishonest reductions rejected, seams, invariants, put in archive
3. **Implement** — One area at a time, RULE19 order nesting→CC→cog→size, tests first (RULE8)
4. **Verify** — RULE16 hard gates + RULE18 ideals recheck per `verification-checklist.md`

## 2. Current gaps vs ideal (from v3)

| File | LOC | Ideal 150-300 | Fail >500 | CC max | Target | Reason for gap |
|---|---|---:|---:|---:|---|---|
| watcher.py | 325 | slight over 300 | warn | 7 | ≤300 file, class ≤150, methods ≤15 | Class LOC 287 baseline legacy, file contains config/state dataclasses + service; needs split |
| dom_highlight.py | 478 | over 300 | warn | 10 | ≤300 file | Single JS payload probe + watcher overlay CSS/JS literals per RULE16.1.5; payloads still in same file as wrappers |
| output_wait.py | 312 | slight over 300 | warn | 9 | ≤300 file | WaitSpec+LoopState polling branches + fallback + mismatch handling; many ≤20 helpers but file still >300 |
| action-blocks.js facade | 435 | over 300 | warn <500 | ≤10 | ≤300 ideal | Must keep getter/setter proxies + lifecycle + pause overlay + bridge binding for App compat; further split possible |
| cdp.js facade | 134 | ideal | — | 5 | ≤300 | Fixed: bindUI 33→ split 3 helpers ≤15 |
| JS global files >300 | 6 files (357,395,448,332,499,435) | over 300 | warn | 66 | ≤3 files >300 | arena-presets 357, image-queue 395, url-list 448, arena-app 332 (setupBridgeListeners 164 CC66), sash-grid-windows 499 — not in C scope but blocks global 0 fails |
| coverage | 41% line 32% branch | 80/75 target | fail legacy allowed | — | 80/75 | Needs D4 ramp |
| c8 JS cov | 0% stmts (vm) | 70% target | — | — | 70% | Tests use vm.runInContext not ESM import |
| dup | 1.59% 43 groups | ≤1% | — | — | ≤1% | Needs jscpd re-measure after ui-helpers dedup |
| SYSTEM_OF_RECORD | not updated | — | — | — | updated | New modules cdp/, cdp_arena/, watcher_overlay, action-blocks/*, cdp/*, sash-core/* not documented |

## 3. Prioritization (severity model: Blast radius×3 + Evidence×2 + Gate impact×2 + Defect correlation×2 + Cost of delay)

| # | Step | Priority | Metric delta | RULE19 order | Owner |
|---|---|---|---|---|---|
| C9 | watcher class split: extract WatcherConfig/WatcherState to watcher_config.py, job control to watcher_jobs.py, reduce watcher.py file ≤300 and class ≤150 | P0 | file 325→≤300, class 287→≤150, methods 25→≤15 | size last (after extracting real concepts) | services/ |
| C10 | dom_highlight split: move _HELPERS_JS, _FIND_BODY, _HIGHLIGHT_BODY, _CLICK_BODY, _QUERY_VARS, _LABEL_JS, _MATCH_JS to js_snippets.py (already 180 LOC), keep only build_* and interpret_* wrappers ≤200 LOC | P0 | file 478→≤300, ideal-size reason removed or narrowed to single JS literal | size last (JS literal exception still applies to js_snippets) | browser/ |
| C11 | output_wait split: move _handle_timeout_fallback + _recheck_after_delay + _extract_fallback_src into output_wait_fallback.py, file ≤300 | P0 | file 312→≤250, CC≤10 | size last | browser/ |
| C12 | action-blocks facade split: extract pause overlay (_updateBadge, _updateCorner, _updateStatus, ensurePauseOverlay, setPaused) + drag cleanup (_cleanupDragState, _cleanSashLeftovers, handleKeydown) into block-ui.js and block-status.js, facade ≤300 | P1 | file 435→≤300 | size last | web/js/panels/action-blocks/ |
| C13 | JS global files >300 split: arena-presets.js 357 → arena-presets/store, render, actions, listeners (like C7), image-queue 395 → image-queue/store/render/actions, url-list 448 → url-list/store/render/matcher, arena-app 332 → arena-app/bridge-listeners, header, init (setupBridgeListeners 164 CC66 → listener registry table), sash-grid-windows 499 → sash-grid-windows/store/persistence/render | P1 | files>300 6→≤3, funcs>30 48→≤10 global, nest>4 24→0 | nesting→CC→cog→size | web/js/ |
| C14 | c8 ESM coverage: convert window.X = X to export const X + window shim, update tests to use import, c8 shows real coverage ≥70% | P1 | JS cov 0%→≥70% | — | web/js/ + tests/js/ |
| C15 | coverage ramp for C modules: add tests for watcher, cdp (transport/tabs/connect/probe/dom), cdp_arena (highlight/attach/submit/output/state), verification, core (naming, scanner, persistence, layout, models, undo), output_wait, dom_highlight, preset_store to reach 80% line for C-owned files | P0 | coverage 41%→80% for C modules, global 41%→55%+ | — | tests/ |
| C16 | SYSTEM_OF_RECORD.md + docs/README.md update + metrics_report: add rows for cdp package, cdp_arena package, watcher_overlay, watcher_config, watcher_jobs, action-blocks/*, cdp/*, sash-core/*, output_wait_fallback, js_snippets | P2 | Docs current | — | docs/current/ |

## 4. Detailed steps per C9-C12 (≤20 LOC funcs, CC≤7 ideal / ≤10 fail, cog≤10/15, nesting≤3/4)

### C9 — watcher class split (P0, biggest ideal-size gap)

**Now:** watcher.py 325 LOC file, class 287 LOC 25 methods, config/state dataclasses inside same file
**Target:** file ≤300, class ≤150, methods ≤15, 0 new fails, cov 27→80% for watcher module

**Steps:**
- C9.1: Create `watcher_config.py` — move `WatcherConfig` dataclass (5 fields) + `WatcherState` dataclass (9 fields) — each ≤15 LOC, file 150-300 ideal? Actually 50 LOC, under 150 good for leaf, cohesive
- C9.2: Create `watcher_jobs.py` — extract `_pause_jobs`, `_resume_jobs` + job_runner getter logic — each ≤10 LOC, file ≤100 LOC leaf
- C9.3: watcher.py: import config/state from watcher_config, jobs from watcher_jobs, overlay from watcher_overlay — reduce file LOC 325→~250, class LOC 287→~180? Still >150, need further split: extract `_loop` + `ensure_task` + `start`/`stop` into `watcher_loop.py`? But spec says class ≤150 — to reach, need to split WatcherService into facade + loop + state machine. For now, move config/state out to get file ≤300, class still 287 but baseline not worsened, add ideal-size reason with constraint: async loop + state + overlay + job pause/resume cohesion, will be split in next round
- C9.4: Tests: existing `test_watcher_overlay.py` 6 pass, add `test_watcher_config.py` — each test fails if target deleted (RULE8)
- **Dishonest reductions rejected:** No `watcher_part1/part2`, no `**kwargs` dodge for config (keep explicit fields), no deleting real decision (captcha vs generation vs clear)

### C10 — dom_highlight split (P0, JS literal exception)

**Now:** 478 LOC, contains _HELPERS_JS (40 lines JS), _QUERY_VARS, _LABEL_JS, _MATCH_JS, _FIND_BODY (30 lines), _HIGHLIGHT_BODY (20), _CLICK_BODY (40) + Python wrappers + interpretation helpers
**Target:** ≤300 file, wrappers CC≤10, JS payloads in js_snippets.py

**Steps:**
- C10.1: Move _HELPERS_JS, _QUERY_VARS, _LABEL_JS, _MATCH_JS, _FIND_BODY, _HIGHLIGHT_BODY, _CLICK_BODY to `dom_highlight_snippets.py` or reuse `js_snippets.py` (already 180 LOC) — but js_snippets.py is for cdp_arena, not dom_highlight. Better create `dom_highlight_js.py` with all JS literals — file 150-300 ideal, single responsibility: JS payloads
- C10.2: dom_highlight.py: import snippets, keep only `_js_str`, `_base_out_js`, `_probe`, `_splice`, `build_find_probe`, `build_click_probe`, `build_highlight_probe`, `build_clear_probe`, interpretation helpers `_candidate_lines`, `interpret_find`, `_found_state`, `_outline_suffix`, `interpret_click`, `interpret_click_target`, plus param objects `HighlightJsSpec`, `HighlightRectSpec`, `WatcherOverlaySpec` and `build_*_from_spec` wrappers — each ≤20 LOC, file ≤250 LOC, CC≤10
- C10.3: Tests: existing selector tests, add probe builder tests that assert JS string contains expected selector (payload-equality normalized whitespace)
- **Anti-gaming:** JS literal exception still applies to snippet file (single JS payload), Python wrappers CC≤10, not gaming

### C11 — output_wait split (P0)

**Now:** 312 LOC, contains WaitSpec, LoopState, many helpers + fallback handling
**Target:** ≤300 file, ideally ≤250

**Steps:**
- C11.1: Create `output_wait_fallback.py` — move `_handle_timeout_fallback`, `_recheck_after_delay`, `_extract_fallback_src`, `_process_fallback`, `should_fallback`, `_is_mismatch_block`, `is_mismatch_reason`, `_has_assoc_mismatch` — each ≤20 LOC, file ≤150 LOC
- C11.2: output_wait.py: keep WaitSpec, LoopState, `should_continue_after_spinner`, `is_ready_result`, `is_cancelled`, `handle_spinner_visible`, `handle_spinner_gone`, `handle_ready_result`, `handle_no_exact_below`, `handle_mismatch`, `_poll_check`, `_reraise_abort`, `_process_ready`, `_process_spinner`, `_check_cancelled`, `_check_timeout`, `_handle_ready_branch`, `_handle_non_ready_branch`, `wait_for_new_output_loop`, `wait_for_new_output_with_spec`, `wait_for_new_output_loop_legacy` — each ≤20 LOC, file ≤250 LOC
- C11.3: Tests: existing output_wait tests, add fallback scenario tests

### C12 — action-blocks facade split (P1)

**Now:** 435 LOC facade, contains pause overlay, drag cleanup, keydown, badge/corner/status updates
**Target:** ≤300 facade, modules ≤300 each

**Steps:**
- C12.1: Create `block-ui.js` — move `_cleanSashLeftovers`, `_cleanupDragState`, `attachGlobalHandlers`, `ensurePauseOverlay`, `handleKeydown` — each ≤15 LOC, file ≤150 LOC
- C12.2: Create `block-status.js` — move `_updateBadge`, `_updateCorner`, `_updateStatus`, `setPaused`, `_isCaptchaStatus`, `detectPause`, `_ensureJob`, `onJobStarted`, `onJobActionStatus`, `onJobFinished`, `onJobPaused`, `onJobResumed`, `onJobFailed` — each ≤15 LOC, file ≤200 LOC
- C12.3: Facade `action-blocks.js`: keep `_store`, `_render`, `_config`, `_listeners`, getters/setters, `init`, `tryBindBridge`, `bindUI`, `triggerRun`, `bindBridgeSignals`, `load*`, `onBlocksUpdated`, `render*`, `selectBlock`, `deselect`, `showConfig`, `moveBlock`, `toggleBlock`, `deleteBlock`, `addBuiltinBlock`, `showAddDialog`, `resetToDefault`, `save`, `export`, `import`, `addCustomBlock`, etc. — file ≤300
- C12.4: Tests: existing `test_action_blocks.mjs` probes block-store directly, add block-ui and block-status tests

### C13 — JS global files >300 split (P1, not C-owned but blocks global 0 fails)

**Now:** 6 files >300 (arena-presets 357, image-queue 395, url-list 448, arena-app 332, sash-grid-windows 499, action-blocks 435 with reason)
**Target:** 6→≤3 files >300, funcs>30 48→≤10 global, nest>4 24→0

**Steps:**
- C13.1: `arena-presets.js` 357 → `arena-presets/` store (load/save), render (chips, list), actions (save/load/delete), listeners (bridge)
- C13.2: `image-queue.js` 395 → `image-queue/` store, render, actions (select, deselect, filter)
- C13.3: `url-list.js` 448 CC 18/13/14/21 → `url-list/` store, render, matcher (matchPoolPage CC18→ split _matchExact, _matchPrefix, _matchHost, _matchKeyword), actions, cooldown cells
- C13.4: `arena-app.js` 332 `setupBridgeListeners` 164 CC66 → `arena-app/` bridge-listeners registry table (like C7), header, init
- C13.5: `sash-grid-windows.js` 499 → `sash-grid-windows/` store, persistence, render

### C14 — c8 ESM coverage (P1)

**Now:** c8 shows 0% stmts because tests use vm.runInContext not import
**Target:** JS cov ≥70% via c8

**Steps:**
- C14.1: Convert `window.X = X` to `export const X = ...; if (typeof window !== 'undefined') window.X = X` shim in ui-helpers, cdp-store, sash-core/*, action-blocks/*
- C14.2: Update tests to use `import` instead of vm, or add ESM wrapper that imports and then vm
- C14.3: `npm run test:js:cov` → `c8 --lines=80 --branches=75 node --test tests/js/*.mjs` shows real coverage

### C15 — coverage ramp for C modules (P0)

**Now:** 41% line 32% branch baseline
**Target:** 80/75 for C-owned files

**Steps:**
- C15.1: watcher: add scenarios captcha detected, generation detected, clear, timeout, no cdp — each fails if deleted
- C15.2: cdp: mock websocket, test candidate building, deduplication, lock loop mismatch, _merge_by_id
- C15.3: cdp_arena: fake CDP client, test highlight, attach, submit flows
- C15.4: verification: empty, html, png, jpg, webp, bmp, invalid, content-type image/* — each fails if deleted
- C15.5: core: scanner predicate table, persistence reconcile, layout normalize, models recalc, undo kind_projection, naming OutputSpec
- C15.6: output_wait: spinner visible/gone, ready, mismatch, fallback, timeout, cancelled
- C15.7: dom_highlight: find probe, click probe, highlight probe, clear, watcher overlay
- C15.8: preset_store: add/remove/list/save/load for each preset kind

### C16 — SYSTEM_OF_RECORD + metrics_report (P2)

**Steps:**
- C16.1: Update `SYSTEM_OF_RECORD.md` §7 module layout: add cdp package (transport, tabs, connect, probe, dom, client), cdp_arena package (highlight, attach, submit, output, download, state, controller, mixins, js_snippets), watcher_overlay, watcher_config, watcher_jobs, output_wait_fallback, dom_highlight_js, action-blocks/*, cdp/*, sash-core/*, block-ui, block-status
- C16.2: Update `docs/README.md` doc map
- C16.3: Update `tools/metrics_report.py` to include JS coverage from c8, jscpd dup, vulture @90

## 5. Expected deltas (next steps)

- watcher.py 325→≤250 file, class 287→≤180 (still >150 but with reason, next round ≤150), methods 25→≤15 after moving jobs/loop
- dom_highlight.py 478→≤250 file, js payloads moved to dom_highlight_js.py 200 LOC
- output_wait.py 312→≤250 file, fallback moved to output_wait_fallback.py 150 LOC
- action-blocks.js 435→≤300 facade + block-ui 150 + block-status 200
- JS global files>300 6→≤3, funcs>30 48→≤10, nest>4 24→0
- JS cov 0%→≥70% via ESM
- Coverage 41%→55%+ for C modules, global 41%→45%+ after adding tests
- Docs updated, metrics_report includes JS cov + dup + vulture

## 6. Risks & anti-gaming

- Behaviour drift → characterization tests before deletion (Area A1 goldens), `test_bridge_slots.py` for slot breakage
- Slot breakage → signal-signature test + manual smoke
- Anti-gaming: No foo_part1, no **kwargs dodge, dispatch tables real, CC floor respected (4 binary outcomes → CC≥5)

## 7. RULE18 recheck at end

- func 4-20, file 150-300, module 5-15, context 60-200
- Every deviation carries `ideal-size: reason=constraint` with ≥20 chars constraint name, not convenience
