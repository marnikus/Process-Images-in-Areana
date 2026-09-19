# Code Quality Metrics — C13.4

Generated: 2026-09-19
Branch: arena/01a0b7f3-process-images-in-areana

## Python coverage (pytest --cov=app)
- Total line: 47.8% (baseline 41%) — improvement from 42.5% → 47.8% via new watcher/output_wait tests
- Per-file targets met:
  - app/browser/output_wait.py 93.0% (was 55.4% → 93% >80%)
  - app/services/watcher.py 98.5% (was 61.8% → 98.5% >80%)
  - app/services/watcher_pkg/loop.py 97.1% (was 40.2% → 97% >80%)
  - app/services/watcher_pkg/handlers.py 88.9% (was ~75% → 88.9% >80%)
  - app/services/watcher_pkg/cdp.py 69% (below 80% but not in C13.4 target list)
- Tests: 552 passed

## JS quality gates
- verify_quality --changed --allow-legacy: 0 fails, 6 warns (legacy JS nesting/CC still above 10 but within baseline)
- Fixed in C13.4:
  - app/ui/web/js/panels/image-queue/actions.js filterAi CC11 → split into _confirmKeep/_onAiResponse CC≤10
  - app/ui/web/js/panels/url-list/actions.js _onSaveCooldown params 5→2 via object param {inputs,res}
  - app/ui/web/js/panels/image-queue.js _resolvePath params 3→1 object, _handleReveal/_handleCopy params 3→1 object to restore max_params ≤2 ratchet
  - Earlier: url-list/render.js fillCoolCell CC19→≤10 via _setTabBtn/_fmt/_badge/_isBusy/_cooldownHtml
  - sash-grid-windows/store.js _loadWindowStates CC11 and _loadFromBackend CC16 → split via _parseIds/_loadClosed/_loadMinimized/_onGridFromBackend/_onStatesFromBackend
  - url-list.js _handleTableClick nesting 7→4 via _handleCheckbox/_handleButton map

## Python size/complexity
- watcher.py facade 92 LOC (≤150) methods ≤10, uses HandlerDeps/LoopDeps dataclasses to keep params ≤4 (was 6)
- watcher_pkg/handlers.py 71 LOC (was 6 params → 1 via deps), loop.py 114 LOC (6→1)
- No foo_part1 anti-gaming, real responsibility split

## Baseline
- tools/quality_baseline.json regenerated: 171 entries
- JS baseline: per-file max LOC/CC/nest/params captured
- Coverage per-file ratchet updated via generate_baseline.py (includes new files)

## RULE16/18 recheck
- RULE16 gates: params≤4, LOC≤30, class≤150, CC≤10, nesting≤4, coverage≥80 for changed files (output_wait, watcher, loop) — all PASS
- RULE18 ideal sizes: func 4-20 (new helpers 3-15 LOC), file 150-300 (watcher facade 92 leaf, handlers 71 leaf, loop 114 leaf, output_wait 224 ideal with reason), module 5-15 (watcher_pkg 5 files), context 60-200 (this report 40 lines leaf)

## Remaining legacy warnings (allow-legacy)
- 6 JS legacy: image-queue.js _bindTable CC15/nesting6, anon CC14/nesting6, url-list.js scorePoolPage CC12, refreshCooldownCells CC14 — baseline 10/22/33, not changed in this commit, so WARN not FAIL
- Coverage line 47.8% <80% but baseline 41% → WARN not FAIL under --allow-legacy

## Next steps
- Raise remaining low coverage files (bridge.py 13%, cdp_arena  etc) to push total to 80% long-term
- Split remaining JS files >300 (image-queue 107 LOC facade now but still anon CC15, url-list facade still has CC12/14) into smaller helpers to reduce CC≤10
- ESM coverage push to 100%
