# Plan Next C Improvements — 2026-09-19 v4 (C14-C20)

**Based on:** review.md v4 + AGENT_RULES.md RULE16/18/19 + area-c-plan.md + next-steps-c-improvement-plan.md
**Status:** Planning only, no production code yet for these steps (RULE17)
**Gate now:** verify_quality --changed --allow-legacy 0 fails 4 warns, --allow-legacy 0 fails 119 warns, file LOC >500 =0 (was 3), JS 135 pass, Python 552 pass, c8 87.79% Stmts, coverage 47.7% line baseline 41%

## 1. IMPLEMENTATION PROCESS (RULE16 §16.6)

1. Understand fully — Measure current radon, target, gaps (review.md)
2. Research & Design — Record current numbers, target numbers, dishonest reductions rejected, seams, invariants, put in archive (this doc)
3. Implement — One area at a time, RULE19 order nesting→CC→cog→size, tests first (RULE8)
4. Verify — RULE16 hard gates + RULE18 ideals recheck per verification-checklist.md, plus `npm run test:js` + `pytest --cov` + `c8`

## 2. Prioritization (severity model: Blast radius×3 + Evidence×2 + Gate impact×2 + Defect correlation×2 + Cost of delay)

| # | Step | Priority | Metric delta | RULE19 order | Owner | Effort |
|---|---|---|---|---|---|
| C14 | JS facade size: url-list 306→≤200, action-blocks 319→≤300, watcher panel 272→split into store/render/actions | P0 | files>300 2→0, funcs>30 38→≤10, CC>10 27→≤15 | nesting→CC→cog→size | web/js/panels/ | M |
| C15 | JS remaining CC>10 / LOC>30 / nesting>4: watcher.js render 66 LOC CC36, sash-grid-drag-core _cleanupDrag CC23, settings.js loadCDPConfig 32 CC19, etc (per verify_quality 169 fails) — split via helpers | P0 | CC>10 27→≤10, LOC>30 38→≤10, nest>4 6→0 | nesting→CC→cog→size | web/js/ | L |
| C16 | Python hotspots split: Bridge 5142 → bridge/ package (slots, state, image, settings, window_states, etc), controller.py 643 → cdp/controller/ package, cooldown_service 787 → cooldown/ package, output_probes 771 → output_probes/ package, action_blocks 716 → action_blocks/ core package, job_runner 332 → job_runner/ package, single_job_runner 560 → single/ package, solver 549 → captcha/solver/ package | P1 | files>300 12→≤5, classes>150 3→0, CC>10 27→≤10, coverage 47→60%+ | nesting→CC→cog→size | app/ | XL |
| C17 | Python coverage ramp D4: D4.1 watcher, job_runner, single_job_runner, multi_page_dispatcher →55%; D4.2 cdp_client, cdp_arena, output_wait, dom_highlight, site_adapter →63%; D4.3 bridge slot contracts post-A5 →70%; D4.4 core/persistence/captcha fail-closed invariants →80/75%; D4.5 JS c8+jsdom →70% | P0 | coverage 47.7%→80% line 75% branch | — | tests/ | L |
| C18 | Browser module cohesion: 20+ files → sub-packages cdp/, cdp_arena/, dom_highlight/, output/, site/, selector/ — each 5-10 files | P1 | module files 20+→5-10 per sub-package | size last | app/browser/ | M |
| C19 | dom_highlight 329→≤300 via watcher overlay split: move _watcher_style_js, _watcher_overlay_css, _watcher_drag_js, build_watcher_overlay_js_from_spec into dom_highlight_watcher.py | P1 | file 329→≤250 | size last | app/browser/ | S |
| C20 | Docs + metrics: Update SYSTEM_OF_RECORD.md §7 module layout, docs/README.md, fix tools/metrics_report.py coverage branch key (num_branches missing), add JS coverage + jscpd dup + vulture to report, regenerate quality_baseline.json | P2 | Docs current, metrics accurate | — | docs/current/ + tools/ | S |

## 3. Detailed steps

### C14 — JS facade size (P0, biggest ideal-size gap, blocks RULE18)

**Now:** url-list.js 306 LOC (was 448) — contains _applyCooldownConfig, _readCooldownInputs, load/saveCooldownConfig fallbacks, matchPoolPage, scorePoolPage, assignPoolPages, matchUnclaimedPage, jobLineForTab, onPoolUpdate, updateJobLines, refreshCooldownCells, _fillCoolCell, _fillJobsCell — 74 funcs (was 55) due to added helpers for CC reduction. File slight over 300 with reason but still over. action-blocks.js 319 (was 435) — contains store/render/config/listeners/ui/status delegation, getters/setters, init, tryBindBridge, bindUI, triggerRun, bindBridgeSignals, load*, onBlocksUpdated, render*, selectBlock, deselect, showConfig, moveBlock, toggleBlock, deleteBlock, addBuiltinBlock, showAddDialog, resetToDefault, save, export, import, addCustomBlock — 319 slight over. watcher.js 272 LOC — render 66 LOC CC36.

**Target:** url-list 306→≤200 facade, action-blocks 319→≤300 (or ≤250 with block-io.js), watcher 272→split into watcher/store, watcher/render, watcher/actions.

**Steps:**
- C14.1: url-list.js — extract cooldown logic (_applyCooldownConfig, _readCooldownInputs, loadCooldownConfig, saveCooldownConfig, _onSaveCooldown) into url-list/cooldown.js (already partially in actions.js but fallback duplicated). Extract pool matching fallbacks (_findBound, _extractForScore, _findExactPrefix, _findHostMatch, _pagesSnapshot, matchPoolPage, scorePoolPage, _claimBound, _buildCandidates, assignPoolPages, matchUnclaimedPage, jobLineForTab) into url-list/matching.js (already exists, but facade still has fallback copies for VM tests — make VM tests load ESM instead, remove fallback copies, facade delegates only). Extract _fillCoolCell, _fillJobsCell, refreshCooldownCells, onPoolUpdate, updateJobLines into url-list/render.js (already exists). Facade then only init, _handleCheckbox, _handleButton, _handleTableClick, restore, render, esc, _snapshotUrls, _extractUrl, add/remove/toggle/test/edit/connect/stop/cool/reparse/popup — ≤200 LOC.
- C14.2: action-blocks.js — extract save/export/import into block-io.js (already partially, but facade still has them). Extract pause overlay + drag cleanup already in block-ui/status, but facade still has proxies — keep proxies but reduce to 1-line delegations. Move getters/setters to block-store? Actually store already has state. Facade then ≤300.
- C14.3: watcher.js panel 272 LOC — split into watcher/store.js (state, poolPages, _coolSnapAt), watcher/render.js (render, _fillCoolCell, _fillJobsCell, refreshCooldownCells), watcher/actions.js (connect, stop, cooldown, reparse). Facade ≤100.
- **Dishonest reductions rejected:** No foo_part1, no moving code to file without real responsibility name, no deleting real decision (cooldown vs generation vs clear). Fallback removal only after updating VM tests to load ESM modules.

### C15 — JS remaining CC>10 / LOC>30 / nesting>4 (P0, blocks full gate)

**Now:** verify_quality without --allow-legacy shows 169 fails: watcher.js render 66 LOC CC36, sash-grid-drag-core _cleanupDrag CC23, settings.js loadCDPConfig 32 CC19, etc.

**Target:** CC>10 27→≤10, LOC>30 38→≤10, nest>4 6→0 for all JS.

**Steps (RULE19 order):**
- C15.1 nesting>4 → guard clauses, early returns: sash-grid-drag-spec _specGeometry nesting 6→ flatten via _isVertical, _isHorizontal helpers.
- C15.2 CC>10 → dispatch tables: watcher.js render 66 CC36 → split into _renderHeader, _renderBody, _renderFooter, _renderCooldown, _renderJobs, _renderActions each ≤15 LOC CC≤7, plus lookup table for status→chip.
- C15.3 cog>15 → name predicates: settings.js loadCDPConfig CC19 → extract _parseCDPEnabled, _parseHostPort, _validateCDPConfig.
- C15.4 size last → extract by concept: settings.js save 32 LOC → _collectSettings, _validateSettings, _persistSettings.
- Verify after every step: `node tools/js_metrics.js app/ui/web --json | jq` and `npm run test:js`.

### C16 — Python hotspots split (P1, biggest legacy)

**Now:** Bridge 5142 LOC, cooldown_service 787, output_probes 771, action_blocks 716, controller 643, single_job_runner 560, solver 549, multi_page_dispatcher 397, service 381, job_runner 332, dom_highlight 329, site_adapter 316 — 12 files >300, 3 classes >150 (Bridge, Controller, JobRunner), CC max 356, cog max 1100.

**Target:** Files>300 12→≤5, classes>150 3→0, file LOC >500 =0 already, but need to reduce >300.

**Steps (one package at a time, characterization tests first):**
- C16.1 Bridge 5142 → app/ui/bridge/ package: bridge/__init__.py facade 150 LOC (re-exports), bridge/slots/ (image, folder, queue, urls, settings, window_states, arena, action_blocks, etc each ≤200 LOC), bridge/state.py, bridge/logging.py, bridge/history.py. Each slot ≤30 LOC CC≤10, facade delegates. Use existing test_bridge_slots.py as equivalence gate.
- C16.2 controller.py 643 → app/browser/controller/ package: controller/__init__.py facade, controller/connect.py, controller/tabs.py, controller/highlight.py, controller/baseline.py, controller/verify.py, controller/download.py — each ≤200 LOC.
- C16.3 cooldown_service 787 → app/services/cooldown/ package: cooldown/__init__.py facade, cooldown/store.py, cooldown/policy.py, cooldown/timers.py, cooldown/recovery.py — each ≤200.
- C16.4 output_probes 771 → app/browser/output_probes/ package: probes for image detection, spinner, job id, etc.
- C16.5 action_blocks 716 → app/core/action_blocks/ package: already partially, but file still 716 — split into blocks/definitions.py, blocks/validation.py, blocks/serialization.py, blocks/execution.py.
- C16.6 job_runner 332, single_job_runner 560, multi_page_dispatcher 397 → app/services/runner/ package: job_runner, single, multi, batch_orchestrator, state_machine.
- **Anti-gaming:** No foo_part1, real responsibility names (Bridge slot per concern), CC floor respected.

### C17 — Coverage ramp D4 (P0, blocks 80/75 target)

**Now:** 47.7% line, 32% branch baseline? Actually branch not measured in new coverage.json (only line). Need to fix coverage.json to include branch.

**Target:** 80% line 75% branch overall, 80% for C-owned files already met for watcher/output_wait, need for other modules.

**Steps:**
- C17.1: Fix tools/metrics_report.py branch key (num_branches missing) — use new coverage.py JSON format (covered_branches not present, need to generate with --branch).
- C17.2: Add tests for cdp/transport, tabs, connect, probe, dom — mock websocket, test candidate building, deduplication, lock.
- C17.3: Add tests for cdp_arena/highlight, attach, submit, output, state — fake CDP client.
- C17.4: Add tests for verification (empty, html, png, jpg, webp, bmp, invalid).
- C17.5: Add tests for core (naming OutputSpec, scanner ScanSpec, persistence reconcile, layout normalize, models recalc, undo kind_projection).
- C17.6: Add tests for bridge slots (each slot).
- C17.7: Add tests for cooldown_service (policy, timers).
- C17.8: JS c8 already 87.79% — add more ESM wrappers for remaining panels to push to 100%.

### C18 — Browser module cohesion (P1)

**Now:** app/browser/ 20+ files (cdp/, cdp_arena/, dom_highlight, dom_highlight_js, output_wait, output_wait_fallback, output_probes, output_state, output_detector, controller, site_adapter, selector, tab_matcher, page_pool, page_status, probe_requests, visual_click, new_chat, cdp_client, cdp_events, cdp_protocol).

**Target:** Sub-packages: browser/cdp/ (6 files), browser/cdp_arena/ (10 files), browser/dom/ (dom_highlight, dom_highlight_js, dom_highlight_watcher), browser/output/ (output_wait, fallback, probes, state, detector), browser/site/ (site_adapter, selector), browser/page/ (page_pool, page_status, tab_matcher), browser/probe/ (probe_requests, visual_click, new_chat).

**Steps:** Move files, update imports, add __init__.py facades for backward compat, run tests.

### C19 — dom_highlight 329→≤300 (P1)

**Now:** 329 LOC (was 478) — contains Python wrappers + interpretation helpers + watcher overlay builders.

**Target:** ≤300, ideally ≤250.

**Steps:** Extract _watcher_style_js, _watcher_overlay_css, _watcher_drag_js, build_watcher_overlay_js_from_spec into dom_highlight_watcher.py — each ≤15 LOC, file 100 LOC leaf.

### C20 — Docs + metrics (P2)

**Now:** SYSTEM_OF_RECORD.md not updated, docs/README.md not updated, metrics_report.py broken branch key, quality_baseline.json 171 entries but needs regen after each fix.

**Steps:**
- C20.1: Update SYSTEM_OF_RECORD.md §7 module layout: add watcher_pkg (config, jobs, overlay, cdp, handlers, jobs_ctrl, loop), dom_highlight_js, output_wait_fallback, action-blocks/*, cdp/*, sash-core/*, image-queue/*, url-list/*, arena-presets/*, sash-grid-windows/*, cdp/*, cdp_arena/*.
- C20.2: Update docs/README.md doc map.
- C20.3: Fix tools/metrics_report.py to handle new coverage.json format (percent_covered, not num_branches) and include JS coverage from c8, jscpd dup, vulture.
- C20.4: Regenerate quality_baseline.json after each area, create reports/CODE_QUALITY_METRICS.md with before→after deltas.

## 4. Expected deltas (C14-C20)

- url-list.js 306→≤200 facade, action-blocks 319→≤300, watcher panel 272→≤100 facade + 3×≤150 modules — files>300 2→0, ideal 20→22
- JS funcs>30 38→≤10, CC>10 27→≤10, nest>4 6→0 — full gate 169→0 fails (without --allow-legacy)
- Python files>300 12→≤5, classes>150 3→0, CC max 356→≤50, cog max 1100→≤100, MI mean 60.97→≥65
- Coverage 47.7%→80% line, branch 59.74% (JS) →75% overall via D4
- Browser module 20+→5-10 per sub-package — cohesion test passes
- Docs updated, metrics accurate, baseline 171→200+ entries

## 5. Risks & anti-gaming

- Behaviour drift → characterization tests before deletion (Area A1 goldens), test_bridge_slots.py for slot breakage, js harness for DOM.
- Slot breakage → signal-signature test + manual smoke.
- Anti-gaming: No foo_part1, no **kwargs dodge, dispatch tables real, CC floor respected (4 binary outcomes → CC≥5), HandlerDeps/LoopDeps real domain concepts.
- JS fallback removal → update VM tests to load ESM modules, not delete decision.

## 6. RULE18 recheck at end

- func 4-20, file 150-300, module 5-15, context 60-200
- Every deviation carries ideal-size: reason=constraint with ≥20 chars, not convenience
- Verify after every step: radon cc -s, pytest, npm run test:js, c8, verify_quality --changed --allow-legacy and without --allow-legacy for full gate

## 7. Implementation order (RULE19)

1. C14 JS facade size (nesting first, then CC)
2. C15 JS CC/LOC/nesting (nesting→CC→cog→size)
3. C19 dom_highlight split (size last)
4. C18 browser cohesion (size last)
5. C16 Python hotspots (nesting→CC→cog→size, one package at a time)
6. C17 coverage ramp (tests first)
7. C20 docs + metrics (last)
