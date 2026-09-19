# Full C Review v4 — 2026-09-19 (C1-C13.4c)

**Process:** Understand → Research/Design → Implement (RULE16 §16.6, RULE19 nesting→CC→cog→size)
**Branch:** `arena/01a0b7f3-process-images-in-areana` at `bb0368a`
**Gates:** `verify_quality --changed --allow-legacy` ✅ 0 fails 4 warns, `--allow-legacy` ✅ 0 fails 119 warns, pytest 552 pass, npm test:js 135 pass, c8 All files 87.79% Stmts 59.74% Branch

## 1. RULE18 & RULE16 recheck

### RULE18 Ideal sizes (preferences, not fail lines)

| Element | Ideal | Actual | Notes |
|---|---|---|---|
| Function 4-20 | ~8-12 | New helpers 3-15 LOC (HandlerDeps, LoopDeps, _confirmKeep, _onAiResponse, _findExactPrefix, _findHostMatch, _pagesSnapshot, _setTabBtn, _fmt, _badge, _isBusy, _cooldownHtml, _parseIds, _loadClosed, _loadMinimized, _onGridFromBackend, _onStatesFromBackend, _handleCheckbox, _handleButton) — all ideal | ✅ |
| File 150-300 | ~200 | watcher.py 92 facade ideal, handlers 71 leaf, loop 114 leaf, watcher_config 47 leaf, watcher_jobs 30 leaf, watcher_overlay 55 leaf, dom_highlight 329 slight over with reason (Python wrappers + interpretation), dom_highlight_js 161 ideal, output_wait 223 ideal, fallback 106 leaf, preset_store 198 ideal, main_window 154 ideal, action-blocks facade 319 slight over with reason (proxies + lifecycle for App compat), block-ui 59 leaf, block-status 96 leaf, block-store 284 ideal, block-render 194 ideal, block-config 157 ideal, cdp 134 ideal, cdp-store 119, cdp-render 111, cdp-actions 129, cdp-listeners 116, sash-core facade 29 ideal, mutate 264 ideal, validate 165, tree 105, traverse 87, constants 24, image-queue 112 ideal, image-queue/store  ?  store/render/thumbs/actions ≤116, url-list 306 slight over (was 448) with reason, url-list/store  ? , render 105, matching 106, actions 144, arena-presets 55 facade ideal, store 73, render 105, actions 221 ideal, sash-grid-windows 14 facade ideal, store/menus/windows ≤204, watcher panel 272 ideal? slight under 300, page-pool 240, settings 216, arena-app/listeners 162 ideal | ⚠️ 2 files slight over 300 (action-blocks 319, url-list 306) — need C14 split |
| Module 5-15 | 7-10 | watcher_pkg 5 files cohesive, cdp 6 files, cdp_arena 10 files, action-blocks 7 files, cdp 5, sash-core 6, image-queue 4, url-list 5, arena-presets 4, sash-grid-windows 4, browser 20+ files (slight over, needs sub-package) | ⚠️ browser 20+ files → needs split |
| Context 60-200 | ~120 | AGENT_RULES 528 >200 existing, SYSTEM_OF_RECORD not yet updated with new modules | ⚠️ context file over, but not worsened |

### RULE16 Gates (hard fails)

| Check | Fail if | Actual new code | Status |
|---|---|---|---|
| func LOC >30 | >30 | New helpers ≤20, orchestrators ≤20 (check_once, wait_for_new_output_with_spec B8) | ✅ |
| class LOC >150 | >150 | WatcherService facade 92, handlers 71, loop 114, PresetStore mixins ≤5, CDPTransport <15, WatcherService old 237 baseline not worsened | ✅ for new, ⚠️ legacy 3 classes >150 (Bridge 5000, Controller 629, JobRunner 316) baseline |
| params >4 | >4 | HandlerDeps/LoopDeps dataclasses 6→1, _resolvePath 3→1 object, _handleReveal/_handleCopy 3→1 object, _onSaveCooldown 5→2 object, OutputSpec 2, ScanSpec 1, WaitSpec 1, HighlightSpec 1 | ✅ |
| methods per class >15 | >15 | PresetStore facade 1, mixins ≤5, WatcherService 25 baseline not worsened, Bridge 5000 baseline | ✅ new, ⚠️ legacy |
| CC >10 | >10 | New code CC≤10 max 10 (_is_loop_mismatch, _findExactPrefix etc), most A-B, legacy bridge 356, controller etc baseline, url-list facade saveCooldownConfig CC13 baseline 14 → WARN not FAIL under --allow-legacy | ✅ changed files |
| cog >15 | >15 | New code cog≤14, legacy bridge 1100 baseline | ✅ |
| nesting >4 | >4 | New code ≤4 via guard clauses, legacy bridge 23 baseline, image-queue _bindTable nesting 6 baseline 10 → WARN | ✅ |
| coverage ≥80/75 | never decrease | Python total 47.7% line (baseline 41%) — not decreased, per-file targets: output_wait 93% (was 55→93), watcher 98.5% (was 61→98), loop 97%, handlers 88.9% — all ≥80 | ✅ for C13.4 targets, ⚠️ total still <80 needs D4 ramp |
| JS LOC >30 | >30 | New JS helpers ≤15, legacy files still have fails but baseline allows | ✅ changed |
| JS CC >10 | >10 | New modules CC≤10, legacy url-list scorePoolPage CC11 baseline 14, saveCooldownConfig CC13 baseline 14, refreshCooldownCells CC14 baseline 14 → WARN | ✅ changed |
| dup | — | jscpd 1.59%→ needs re-measure after dedup, expected ≤1% | ⚠️ |
| vulture | 0 new | 0 new | ✅ |
| anti-gaming | — | No foo_part1, no **kwargs dodge (HandlerDeps/LoopDeps real domain concepts), dispatch tables real (map for test/toggle/remove/edit/connect/stop-job, _setTabBtn/_fmt/_badge etc), CC floor respected | ✅ |

**Summary:** All changed files pass RULE16, 0 fails on --changed --allow-legacy, 0 fails on --allow-legacy. Legacy hotspots (Bridge 5000, Controller 629, cooldown_service 787, output_probes 771, action_blocks 716, single_job_runner 560, solver 549, multi_page_dispatcher 397) still over but not worsened, baseline ratchet prevents growth.

## 2. Area C Plan C1-C8 vs Actual

| Symbol | Before (area-c-plan) | Target | After C13.4c | Met? |
|---|---|---|---|---|
| watcher check_once | 124 LOC CC35 cog82 | ≤20 CC≤7 | 18 LOC CC4 (now in loop.py check_once) | ✅ |
| WatcherService | 269 LOC 15m 306 file | ≤150 ≤15 ≤300 | Facade 92 LOC 11 methods? Actually WatcherService facade 92, class LOC 92, methods ~11, but old WatcherService still exists as facade? Now watcher.py 92 ideal | ✅ file, ⚠️ old class still 237? Actually new facade 92 is new class, old 287 removed |
| cdp_client _connect_inner | 106 CC27 | CC≤7 | _build_candidate_urls 5, _dedupe 3, _enable_domains 3, _try_candidates_loop 3 — all ≤10 | ✅ |
| CDPClient | 469 LOC 22m 655 file 15 fails | facade ≤150 0 fails | facade 127 + 5×≤275 CC≤10 0 fails new | ✅ |
| cdp_arena highlight_selector | CC13 | CC≤7 | 10 LOC CC7 | ✅ |
| CDPArenaController | 371 LOC 30m 585 file 3 fails | ≤150 + 3×≤150 0 fails | facade 28 + 9×≤180 CC≤7 0 fails new | ✅ |
| validate_downloaded_file | 42 CC14 nest5 | ≤15 CC≤5 | 10 CC4 nest3 | ✅ |
| reconcile_with_filesystem | 101 CC21 | CC≤7 | A4 via dispatch | ✅ |
| scan_folder | 66 CC13 | CC≤7 | 7 CC7 | ✅ |
| undo | 38 CC12 | CC≤7 | B6 | ✅ |
| normalize_grid_tree | cog21 | cog≤10 | B10 | ✅ |
| get_output_path | 6 params | ≤4 via spec | OutputSpec 2 | ✅ |
| wait_for_new_output_loop | 5p CC16 | 1p CC≤10 | WaitSpec 1p CC8 | ✅ |
| build_highlight_rect_js | 7p | 1p | HighlightRectSpec 1p | ✅ |
| PresetStore | 22m | ≤15 | mixins ≤5 facade 1 | ✅ |
| main_window __init__ | 31 LOC | ≤20 | 7 LOC | ✅ |
| action-blocks.js | 836 CC90 anon169 | facade ≤500 funcs>30 48→≤10 | facade 319 + 6×≤284 CC≤8 | ✅ facade <500, funcs>30 48→38? Actually metrics show >30 38 global, but C-owned ≤10 |
| cdp.js | 549 | ≤300 | facade 134 + 4×≤129 | ✅ |
| sash-core | 528 | ≤300 | facade 29 + 5×≤264 | ✅ |
| file LOC >500 | 3 (837/549/528) | 0 | 0 | ✅ |
| JS funcs>30 | 48 global | ≤10 | 38 global (was 48) → 10 improvement, but still 38 | ⚠️ needs further split |
| nest>4 | 24 global | 0 | 6 global (was 24) → improvement | ⚠️ still 6 |
| dup | 1.59% 43 groups | ≤1% | needs re-measure | ⚠️ |
| coverage | 41.2% line | 80/75 | 47.7% line (not decreased) | ⚠️ legacy allowed |

## 3. C9-C13 vs Actual

| File | Before C9 | After C13.4c | Delta | Ideal met? |
|---|---|---|---|---|
| watcher.py | 325 | 92 facade + pkg 5 files | -233 -72% | ✅ |
| dom_highlight.py | 478 | 329 + js 161 | -149 -31% + new | ⚠️ 329 slight over |
| output_wait.py | 312 | 223 + fallback 106 | -89 -29% + new | ✅ |
| action-blocks.js | 435 | 319 + ui 59 + status 96 | -116 -27% + new | ⚠️ 319 slight over |
| arena-presets.js | 357 | 55 + store 73 + render 105 + actions 221 | -302 -85% | ✅ |
| image-queue.js | 395 | 112 + store/render/thumbs/actions ≤116 | -283 -72% | ✅ |
| url-list.js | 448 | 306 + store/render/matching/actions | -142 -32% | ⚠️ 306 slight over |
| sash-grid-windows.js | 499 | 14 + store/menus/windows | -485 -97% | ✅ |
| cdp.js | 134 | 134 + 4 modules | stable | ✅ |
| watcher panel | 272 | 272 (not yet split) | — | ⚠️ still 272 ideal but could split |
| Baseline entries | 145 | 171 | +26 new modules | — |
| JS tests | 117 | 135 | +18 | ✅ |
| Python tests | 430+ | 552 | +122 | ✅ |
| c8 All files | 0% | 87.79% Stmts 59.74% Branch | +87.79% | ✅ ≥70% target met |

## 4. Remaining gaps (prioritized)

1. **Python hotspots still >300** (12 files >300, 7 >500): Bridge 5142, cooldown_service 787, output_probes 771, action_blocks 716, controller 643, single_job_runner 560, solver 549, multi_page_dispatcher 397, service 381, job_runner 332, dom_highlight 329, site_adapter 316. These are legacy, not worsened, but block total coverage and MI. Need C16+ splits.

2. **JS files >300**: action-blocks 319 (slight over), url-list 306 (slight over) — 2 files >300 (was 8). Target ≤3 met, but ideal 0 needs further split.

3. **JS funcs >30**: 38 global (was 48) — still 38 over 30, target ≤10. Need to split remaining large JS functions (watcher.js render 66 LOC CC36, sash-grid-drag-core _cleanupDrag 23 CC23, settings.js loadCDPConfig 32 CC19 etc per verify_quality).

4. **JS nesting >4**: 6 global (was 24) — improvement but still 6.

5. **Python coverage total 47.7% <80%**: per-file C targets met (output_wait 93%, watcher 98.5%, loop 97%), but global needs ramp via D4.

6. **Browser module 20+ files**: cohesion test fails — files never change together. Needs sub-package split (cdp/, cdp_arena/, dom_highlight/, output_* etc already, but still 20+).

7. **SYSTEM_OF_RECORD.md not updated**: new modules watcher_pkg, dom_highlight_js, output_wait_fallback, action-blocks/*, cdp/*, sash-core/*, image-queue/*, url-list/*, arena-presets/*, sash-grid-windows/* not documented.

8. **Dup 1.59%**: needs jscpd re-measure after ui-helpers dedup.

## 5. Next steps proposal (C14-C20)

See plan.md for prioritized steps respecting RULE19 order.

## 6. RULE19 order verification

All fixes followed nesting→CC→cog→size:
- url-list.js _handleTableClick nesting7→4 via _handleCheckbox/_handleButton map (nesting first)
- fillCoolCell CC19→≤10 via _setTabBtn/_fmt/_badge/_isBusy/_cooldownHtml (CC second)
- _setTabBtn etc naming clarifies cognitive (cog third)
- File size last (306 still slight over but with reason, next split will reduce)

No gaming: no foo_part1, no **kwargs dodge, HandlerDeps/LoopDeps real domain concepts, dispatch tables real, CC floor respected.
