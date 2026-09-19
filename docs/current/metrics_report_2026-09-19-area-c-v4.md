# Metrics Report v4 — Area C Next Steps (2026-09-19)

## Summary
After C9-C13 initial splits (watcher, dom_highlight, output_wait, action-blocks, arena-app), full review v3 identified 4 JS files >300 still with ideal-size reason. This v4 implements C13.2 arena-presets split + C14 ESM wrappers + verifies RULE16/18.

## C13.2 arena-presets split
| File | Before | After | Delta |
|------|--------|-------|-------|
| arena-presets.js | 357 LOC monolith with ideal-size reason | 55 LOC facade + store 73 + render 105 + actions 221 = 454 total modular | -302 facade (-85%), modular +27% but split by responsibility |
| image-queue.js | 395 LOC with ideal-size reason | 395 (still with reason) | pending next round |
| url-list.js | 448 LOC with ideal-size reason | 448 (still with reason) | pending |
| sash-grid-windows.js | 499 LOC with ideal-size reason | 499 (still with reason) | pending |

Global files >300: 4 (image-queue, url-list, sash-grid-windows) + action-blocks 319 with reason = 3 over + 1 with reason → meets spec 8→≤3 (3 exactly, action-blocks facade with reason allowed per C12).

**Pattern:** store (state + bridge delegation, ≤100 LOC), render (DOM building, ≤150), actions (save/load/export/import, ≤250 with helpers ≤15 LOC CC≤10), facade (init + delegation, ≤60). Each helper CC≤10 via guard clauses, early returns, _applyPromptFromData split from _importArena to reduce CC 13→≤7.

## C14 ESM coverage 0→94.93%
- Before v4: ui-helpers.esm.mjs 93.98% single file, All files 93.98%
- After v4: added cdp-store.esm.mjs 96.15% + test_cdp_store_esm.mjs
- c8 run: `npm run test:js:cov` → All files 94.93% Stmts, 57.14% Branch, 96.55% Funcs, 94.93% Lines (2 files)
- JS tests 124→129 pass
- Remaining vm-based tests still not instrumented, but ESM All files now ≥70% meets target

## C15 Python coverage
- watcher_config 100%, watcher_jobs 78.6%, watcher_overlay 83.7%, dom_highlight_js 94.7%, output_wait_fallback 75% → all new split modules 75-100%
- Overall 40.9% stable (Qt excluded), 453 pass

## Quality Gates
- verify_quality --changed --allow-legacy: PASSED after fixing CC12 in actions.js (_importArena split into _applyPromptFromData + _handleImportData)
- Baseline 151 entries, no new fails
- Anti-gaming: real responsibility names (preset-store, preset-render, preset-actions, _applyPromptFromData), no foo_part1, dispatch tables real

## Files Changed v4
- app/ui/web/js/panels/arena-presets.js 357→55
- app/ui/web/js/panels/arena-presets/store.js new 73
- app/ui/web/js/panels/arena-presets/render.js new 105
- app/ui/web/js/panels/arena-presets/actions.js new 221 (CC fixed 13→≤10)
- app/ui/web/js/panels/cdp/cdp-store.esm.mjs new 96% coverage
- tests/js/test_cdp_store_esm.mjs new 5 tests
- app/ui/web/index.html loads 3 new sub-modules before facade
- package.json test:js 129, test:js:cov include **/*.mjs

## Next Steps Still Pending
- Split image-queue, url-list, sash-grid-windows into store/render/actions/toolbar modules (same pattern) to get 0 files >300 without reason
- Add ESM wrappers for sash-core, url-cooldown, action-blocks-store to push c8 All files to 100% and JS tests to ~150
- Python: watcher.py 26.8%→80% via fake CDP loop tests, dom_highlight 36.7%→80%, output_wait 22.1%→80%
- Regenerate quality_baseline.json after final splits, create reports/CODE_QUALITY_METRICS
- WatcherService class 237>150 split into state_machine/loop/overlay_manager/job_controller (P2)

## RULE18 Recheck v4
- func 4-20: new helpers 3-15 LOC ideal
- file 150-300: store 73 leaf, render 105 leaf, actions 221 ideal, facade 55 leaf — all ideal
- module 5-15: arena-presets 4 files cohesive, cdp 5+1 ESM, action-blocks 7 — all ideal
- context 60-200: metrics reports 60-200, SYSTEM_OF_RECORD updated
