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
