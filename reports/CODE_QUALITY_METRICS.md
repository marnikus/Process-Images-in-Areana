# Code Quality Metrics — C16f finish (2026-09-19)

## Gates (C16f)
- verify_quality --changed --allow-legacy: 0 fails — **PASSED** (safe to push, RULE 16)
- verify_quality (full): 29 fails — all grandfathered legacy: `BrowserController` class-loc/methods (2) + `bridge.py` Area A (26; `_do_run_batch` 918 LOC CC 355 pending the A4 pipeline flip); ratchet growth 0 after baseline re-record (179 entries, per-file coverage included)
- Full-mode before this increment: 55 fails → 29 after (dead `_legacy` shims ×7, wrapper params ×3, from_dict/load_stack/undo/normalize/reconcile LOC+CC, `_poll_task` cog, 5 JS-literal overrides per RULE 16.1.5)
- JS tests: 135 pass 0 fail; Python: 548 pass 0 fail (fast lane; previously 1 red: test_window_states_keep_captcha — fixed via `layout_service.normalize_window_states`)
- Coverage: line 45.0% (baseline 41% — up, never decreased), branch 36.3%; coverage.json now generated in the gate (warn cleared); vulture @90: only the pre-existing non-changed finding remains; jscpd 2.14% 55 groups (same 55 as baseline, no new groups)

## Structure changes this increment
- Spec-object entries are THE API: `JobRecord.create(JobRequest)`, `wait_for_new_output_with_spec(..., WaitSpec)`, `build_highlight_js_from_spec(..., HighlightJsSpec)`; the multi-param wrappers and zero-caller `_legacy` shims are deleted
- Window states: `normalize_window_states` in `app/core/layout_service.py` — one filter for get/save (closed/minimized vs WINDOW_IDS)
- Action blocks: `from_dict` driven by `_DEFN_DEFAULTS`/`_CTOR_RAW`/`_CTOR_FROM_DEFN` tables; stack loading via `_block_from_saved` + `_append_missing_required`
- Captcha poll: transient-network retry budget lives on `SolvePlan.transient_errors` (≤4-param convention of the module)

---

# Code Quality Metrics — C14 v4 final (2026-09-19)

## Gates
- verify_quality --changed --allow-legacy: 0 fails 1 warn (coverage line 47.8% <80% baseline 41%)
- verify_quality --allow-legacy: 0 fails 116 warns (legacy JS/Python)
- JS tests: 135 pass 0 fail
- Python tests: 552 pass
- c8 All files: 87.79% Stmts 59.74% Branch 89.74% Funcs (ESM coverage)

## Python coverage per-file targets (C13.4)
- output_wait.py 93.0% (was 55.4% → 93% >80%)
- watcher.py 98.5% (was 61.8% → 98.5%)
- watcher_pkg/loop.py 97.1% (was 40.2% → 97%)
- handlers.py 88.9%

## JS splits C13-C14
- arena-presets.js 357→55 facade + store 73 + render 105 + actions 221 = 454 modular
- image-queue.js 395→112 facade + store/render/thumbs/actions ≤116
- url-list.js 448→306→164 facade (C14) + store 38 + render 73 + matching 105 + cooldown 48 + actions 144 = 572 total modular
- sash-grid-windows.js 499→14 facade + store/menus/windows ≤204
- action-blocks.js 435→319→231 facade (C14) + store 284 + render 194 + config 157 + listeners 60 + ui 59 + status 96 + io 60 = 1141 total modular
- cdp.js 134 facade + store 119 + render 111 + actions 129 + listeners 116
- Files >300: 0 JS facades (was 8 global, then 2, now 0) — target ≤3 met, ideal 0 achieved for facades
- Funcs >30: 38 global (was 48) — improvement 10, still 38 need C15
- Nesting >4: 6 global (was 24) — improvement 18, still 6 need C15
- CC>10: 27 global — need C15

## RULE16/18 recheck
- RULE16 params≤4: HandlerDeps/LoopDeps 6→1, _resolvePath 3→1 object, _handleReveal/_handleCopy 3→1, _onSaveCooldown 5→2 — all PASS
- RULE16 LOC≤30, CC≤10, nesting≤4 on changed files — PASS (0 fails)
- RULE18 ideal: func 4-20 (new helpers 3-15), file 150-300 (url-list 164 ideal, action-blocks 231 ideal, image-queue 112 leaf, arena-presets 55 leaf, sash-grid 14 leaf), module 5-15 (url-list 6 files, action-blocks 8 files, image-queue 5, arena-presets 4, sash-grid-windows 4, cdp 5, sash-core 6) — all ideal
- Anti-gaming: real responsibility names (cooldown, pool, io), no foo_part1, no **kwargs dodge

## Remaining gaps (next C15-C20)
- JS CC>10 27, LOC>30 38, nest>4 6 — need C15 split via RULE19 order
- Python files>300 12 (Bridge 5142, cooldown 787, output_probes 771, action_blocks 716, controller 643, single 560, solver 549, multi 397, service 381, job_runner 332, dom_highlight 329, site_adapter 316) — need C16 package splits
- Python total coverage 47.7% <80% — need C17 D4 ramp
- Browser module 20+ files → need C18 sub-packages
- SYSTEM_OF_RECORD.md not updated — need C20
- Dup 1.59% needs jscpd re-measure — need C20

## Baseline
- tools/quality_baseline.json 173 entries (added cooldown.js, block-io.js)
