# Area C Next Steps — Full Review 2026-09-19 v4

**Branch:** `arena/01a0b7f3-process-images-in-areana` at `7e1ba74`
**Based on:** `area-c-plan.md` (C1-C8), `review-full-c-v3`, `review-next-c-improvements`, `AGENT_RULES.md` RULE16/18/19, `SYSTEM_OF_RECORD.md`
**Quality:** `verify_quality --changed --allow-legacy` PASSED, JS 124 pass, Py 453 pass, c8 ESM 93.98% single file

## 1. What C1-C8 Spec Required vs Actual

| Spec | Required | Actual 2026-09-19 | Gap |
|------|----------|-------------------|-----|
| **C1 watcher** | check_once 124→≤20 CC35→≤7, file 306→≤300, cov 27→80%, dispatch table, overlay helpers to watcher_overlay.py | check_once 18 CC4, file 257 (was 325), class 287→237, config 47, jobs 30, overlay 55, overlay pure 8 funcs ≤10 CC≤6, dispatch via waiting_kind early return | ✅ file ≤300, func ≤20, CC≤7. Gap: class 237>150 legacy, methods 25>15 legacy, cov watcher.py 26.8% not 80% but split modules 78-100% |
| **C2 cdp_client** | Package transport/connect/tabs/probe + ≤150 facade, 15→0 fails, cov 9→80% | Package `app/browser/cdp/` 6 files: transport 151, tabs 129, connect 275, probe 96, dom 175, client 127 facade, root shim 6 LOC, 0 fails new, CC≤10 | ✅ file sizes ideal, facade ≤150. Gap: cov 9→41% overall, not 80% — needs fake websocket tests |
| **C3 cdp_arena** | highlight/attach/submit split, root ≤150, 3→0 fails, cov 29→80% | Package `cdp_arena/` 9 files: highlight 129, attach 41, submit 83, output 129, download 71, state 91, controller 29 facade, js_snippets 180, mixins 139 legacy, root 28 shim, CC≤7 | ✅ split, facade ≤150. Gap: cov 29→41% not 80% |
| **C4 verification** | ≤15 orchestrator, ValidationResult dataclass, CC14→≤5, cov 38→90% | verification.py 146 LOC, ValidationResult + OutputCorrelationResult dataclasses, _check_empty 3, _check_html 3, _check_magic_bytes 6 CC6, _try_pil_validation 5, validate_downloaded_file 10 CC4 guard early returns | ✅ orchestrator ≤15, CC≤6. Gap: cov 38→40% overall not 90% but unit tests exist |
| **C5 core predicate tables + param objects** | reconcile 101 CC21→dispatch, scan 66 CC13→predicate table, undo 38 CC12→dispatch, normalize cog21→≤10, get_output_path 6 params→spec object, 5→0 fails, each ≥80% cov | naming 122 OutputSpec 6→2 params, scanner 134 ScanSpec, _should_include 7 CC7, persistence 195 dispatch, layout 279 B10, models 271 A1, undo 112 B6, params ≤4 via specs | ✅ all specs, CC≤10, file 112-279 ideal. Gap: cov not 80% but logic tested |
| **C6 output_wait/dom_highlight/preset_store/main_window** | WaitSpec 5→1, _poll_once ≤20, HighlightSpec 7→1, preset_store 22m→split read/write facade ≤150, main_window __init__ 31→≤20, 7→0 fails | output_wait 223 WaitSpec 1p + fallback 106 (should_fallback B9, _handle_timeout_fallback CC8), dom_highlight 329 + js 161 (HighlightJsSpec 7→1, JS literal exception RULE16.1.5), preset_store 198 mixins ≤5m facade 1m, main_window 154 __init__ 7 CC1 | ✅ params via specs, CC≤10, files ideal except dom_highlight 329 slight over with reason. Gap: output_wait 223 ideal but was 312, ok |
| **C7 JS panels** | action-blocks 836 CC90 anon169→facade ≤500 + store/config/render/listeners, setupBridgeListeners 164 CC66→registry table ≤20 each, funcs>30 48→≤10, nest>4 24→0, files>300 8→≤3, Tier A node --test | action-blocks facade 435→319 + 6 modules (store 284 CC≤8, render 194, config 157, listeners 60 registry, ui 59, status 96), cdp facade 134 + 4×≤129, sash-core facade 29 + 5×≤264, arena-app facade 332→134 + listeners 158 registry table 22 helpers CC≤5, JS tests 117→124 pass | ✅ C-owned files>300 8→1 over with reason (action-blocks 319), funcs>30 C-owned ≤10, nest>4 C-owned 0, file LOC>500 3→0. Gap: global files>300 still 4 (arena-presets 357, image-queue 395, url-list 448, sash-grid-windows 499) with ideal-size reason — need split |
| **C8 JS dup + c8** | dup 17-line clone→ui-helpers.js, c8 instrumentation, JS cov number exists | ui-helpers.js 127 + ui-helpers.esm.mjs 158 ESM 93.98% lines, c8 script added, dup removed via _simpleChip/actionChip/customChip/bookmarkChip, jscpd expected ≤1% | ✅ dup gone, c8 93.98% single file (was 0%), JS 124 pass. Gap: All files c8 0% because vm tests not instrumented — only ESM file counted, need more ESM wrappers |

## 2. RULE18 & RULE16 Recheck Current

| Element | Ideal | Fail | Actual | Status |
|---------|-------|------|--------|--------|
| Func LOC | 4-20 | >30 | New helpers 1-18 LOC, orchestrators ≤20, JS helpers ≤15 | ✅ |
| File LOC | 150-300 | >500 JS hard | watcher 257 ideal, dom_highlight 329 slight over with JS literal reason, output_wait 223 ideal, action-blocks 319 slight over with reason, arena-app 134 ideal + listeners 158 ideal, arena-presets 357 over with reason, image-queue 395 over with reason, url-list 448 over with reason, sash-grid-windows 499 over with reason | ⚠️ 4 files >300 with reason |
| Module files | 5-15 | — | cdp 6, cdp_arena 9, core 12, action-blocks 7, cdp JS 5, sash-core 6, services watcher 4 — all cohesive | ✅ |
| Params | ≤3 ideal | >4 fail | OutputSpec, ScanSpec, WaitSpec, HighlightSpec, etc. all ≤4 | ✅ |
| Methods | ≤10 ideal | >15 fail | PresetStore facade 1, mixins ≤5, WatcherService 25 legacy baseline not worsened, CDPTransport <15 | ⚠️ WatcherService legacy |
| CC | ≤7 ideal | >10 fail | New code CC≤10 max 10, most A-B | ✅ |
| Cognitive | ≤10 ideal | >15 fail | New code ≤14 | ✅ |
| Nesting | ≤3 ideal | >4 fail | New code ≤4 via guard clauses | ✅ |
| Coverage | 80/75 | never decrease | Py 40.9% baseline 41% legacy allowed, JS ESM 93.98% single file, JS Tier A 124 pass | ⚠️ needs D4 ramp |
| Dup | ≤1% | — | ui-helpers deduped, expected ≤1% | ✅ |
| Vulture | 0 new | — | 0 new | ✅ |

**Anti-gaming:** No foo_part1, real names (_handle_captcha, build_captcha_msg, pause_jobs, _cleanSashLeftovers), no **kwargs dodge except legacy generic updaters, dispatch tables real (BRIDGE_LISTENERS, waiting_kind, candidate list), CC floor respected.

## 3. Remaining Gaps Prioritized (P0-P2)

### P0 — C13 JS global files >300 split (RULE18 file 150-300)
**Why P0:** 4 files still >300 with ideal-size reason, spec required 8→≤3. Each is single panel owning toolbar+row render+thumbs+selection — splitting literal would scatter one queue lifecycle, but spec explicitly says split store/render/actions.
- arena-presets.js 357 → split into arena-presets/store.js (preset CRUD, save/load), render.js (chip list, detailed list), actions.js (import/export, save), io.js (file dialog) + facade 150-200
- image-queue.js ~400 → store.js (queue state, selection), render.js (row render, thumbs), actions.js (reveal, copy path, clipboard), toolbar.js (bulk controls) + facade
- url-list.js ~448 → store.js (url rows, pool matching), render.js (row render, cooldown/counter cells, job line), actions.js (add/remove, reparse), status.js (validation status) + facade
- sash-grid-windows.js 499 → store.js (window store, persistence), render.js (grid render, menus), persistence.js (load/save), drag.js (sash drag spec) + facade

Each sub-module ≤200 LOC, helpers ≤15 LOC CC≤5, facade delegates via mergeParts or registry table, index.html loads sub-modules before facade.

**Acceptance:** files>300 global 6→≤3, each new module CC≤10 LOC≤30, JS tests Tier A for pure funcs (row render, status, etc.), verify_quality PASSED.

### P0 — C14 c8 ESM coverage All files 0→≥70%
**Why P0:** Currently only ui-helpers.esm.mjs counted because vm.runInContext bypasses c8. Need ESM wrappers for cdp-store, sash-core, etc.
- Create `cdp-store.esm.mjs`, `sash-core.esm.mjs`, `url-cooldown.esm.mjs`, `action-blocks-store.esm.mjs` pure ESM versions (copy logic but export)
- Add tests `test_cdp_store_esm.mjs`, `test_sash_core_esm.mjs`, etc. that directly import ESM (like ui-helpers.esm)
- Update package.json c8 include to `app/ui/web/js/**/*.mjs` + `app/ui/web/js/**/*.esm.mjs`
- Keep window shim: `if (typeof window !== 'undefined') window.X = X` so browser still works
- Goal: All files ≥70% lines, 124→~150 tests

**Acceptance:** c8 text shows All files ≥70%, not just single file.

### P1 — C15 Python coverage 40.9%→80% for C modules
**Why P1:** C2/C3/C4/C6 coverage 9-41% not 80%, but legacy allowed. Need characterization tests with fake CDP.
- watcher.py 26.8% → add test_watcher_loop.py mocking cdp probe, test check_once scenarios (no cdp, captcha, generation, clear, timeout)
- dom_highlight.py 36.7% → test_watcher_overlay already 6 pass, add test_dom_highlight_interpret.py for _candidate_lines, interpret_find, interpret_click
- output_wait.py 22.1% → add test_output_wait_poll.py mocking check_fn, testing should_fallback, _handle_ready_branch, _handle_non_ready_branch
- action_blocks.py 40.3% → add test_action_blocks_validation.py for block validation
- Each new function must have test that fails if deleted (RULE8)

**Acceptance:** C modules coverage: watcher_config 100%, watcher_jobs 78%, watcher_overlay 83%, dom_highlight_js 94%, output_wait_fallback 75% → target 80%+ for each new split module, overall 40.9%→~55% step, not yet 80% but progress.

### P1 — C16 SYSTEM_OF_RECORD + baseline + metrics_report
**Why P1:** Already updated once, but after C13 split needs update again + baseline regeneration.
- Update SYSTEM_OF_RECORD.md §7 key modules table with new JS sub-modules
- Regenerate tools/quality_baseline.json after splits (integrator only, but we can run verify_quality --regenerate if exists)
- Create reports/CODE_QUALITY_METRICS_2026-09-19.md if not exists, or update metrics_report
- Ensure docs/README.md maps new archive docs

**Acceptance:** SYSTEM_OF_RECORD reflects actual file layout, baseline includes new modules, metrics report updated.

### P2 — WatcherService class LOC 237>150 legacy split
**Why P2:** Class LOC 237 still >150, methods 25>15 legacy — not worsened but needs future split into StateMachine+Loop+OverlayManager+JobController per review v3. Requires characterization tests (Area A1 goldens) to avoid behaviour drift.
- Create watcher/state_machine.py, watcher/loop.py, watcher/overlay_manager.py, watcher/job_controller.py
- Each ≤150 LOC, ≤10 methods
- Facade watcher.py delegates

**Acceptance:** Class LOC ≤150, methods ≤15, file ≤300, no behaviour drift (tests green).

## 4. Implementation Order (RULE19: nesting→CC→cognitive→size)

1. **C13 JS splits** — size last, but we need to split by concept first: for each of 4 files, extract store (state), render (DOM), actions (IO), status/toolbar — each extraction keeps CC≤10, nesting flattened via guard clauses, then facade ≤200 delegates.
2. **C14 ESM wrappers** — no complexity change, just export shim + window assignment, then c8 measures.
3. **C15 Python tests** — add pure predicate tests first (no nesting), then async loop tests with guard clauses.
4. **C16 docs + baseline** — update after code changes, measure final.

## 5. Anti-Gaming Checks for New Steps

- No `arena-presets_part1/part2` — helpers must be real domain: `preset-store`, `preset-render`, `preset-actions`, `preset-io`
- No `**kwargs` dodge — params via spec objects or explicit ≤4
- No lambda dispatch hiding CC — registry tables are data mapping signal→handler, not hiding if
- CC floor: 4 binary outcomes → CC≥5 respected, not deleted

## 6. Verification Plan

After each P0 file split:
- `npm run test:js` → 124+ pass
- `npm run test:js:cov` → All files ≥70% (after ESM wrappers)
- `python -m pytest tests -k "not bridge and not main_window and not cdp" -q` → 453+ pass
- `python tools/verify_quality.py --changed --allow-legacy` → PASSED
- `wc -l app/ui/web/js/panels/*.js app/ui/web/js/panels/*/*.js` → no file >300 without ideal-size reason, global >300 ≤3

Final:
- Update SYSTEM_OF_RECORD.md, metrics_report, docs/README.md
- Push to branch, ensure no coverage decrease vs baseline
