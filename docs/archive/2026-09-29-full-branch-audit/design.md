# Full Branch Audit — All Code Added on `arena/01a0e9c1-process-images-in-areana`

Date: 2026-09-29
Base: `origin/main` (217fbe8)
Head: `485d7b2` (workspace refactor + prior fixes)
Scope: ALL files changed vs origin/main (40 files) — not just workspace

> This doc extends `docs/archive/2026-09-29-global-save-restore-refactor/design.md` which covered workspace only.
> Here we audit the whole branch as requested.

## 1. Code Map — Complete Feature Set Added on Branch

### 1.1 Workspace Save/Restore (already audited, refactored)

- `app/persistence/workspace/` — 5 files, low-level IO, manifest, integrity, errors
- `app/services/workspace/` — 11 files + 8 providers + 5 new refactored files (_base, selection, transaction, restore_runner, preview)
- `app/ui/panels/workspace.py` — UI seam, 6 slots, thin delegation
- Tests: `test_workspace_*.py` (8 files) + `test_workspace_refactor_char.py`

### 1.2 New Tab Handover (I-79) — "Start new chat as new tab"

- `app/services/new_tab.py` — 668 LOC, setting read/save, handover planning, open+prove, cookie/storage copy, context verification, owner preservation, worker move, old tab close
- `app/browser/cdp/tabs.py` — 199 LOC, sync fetch/open/close tabs, dedup, context handling
- `app/browser/cdp/transport.py` — 313 LOC, CDP transport, websocket, receive loop
- `app/browser/cdp_arena/controller.py` — 31 LOC, controller init (small)
- `app/browser/cdp_arena/mixins.py` — 167 LOC, mixins for controller
- `app/browser/cdp_arena/text_output.py` — 233 LOC, text output capture (new file)
- `app/browser/text_output_probes.py` — 475 LOC, JS probes for text output detection
- `app/browser/probe_selectors.py` — 154 LOC, selector helpers
- `app/browser/site_adapter.py` — 373 LOC, selector registry (pure data)
- Tests: `tests/test_new_tab_handover.py` 342 LOC

### 1.3 Block Runner & Action Blocks

- `app/core/action_blocks.py` — 912 LOC, ActionBlock dataclass, BLOCK_DEFINITIONS catalog
- `app/core/action_blocks_defaults.py` — 85 LOC, default blocks
- `app/core/naming.py` — 144 LOC, output path, atomic write
- `app/services/single_job_runner.py` — 1173 LOC, JobCtx, block handlers (OBSERVE_BASELINE, CHECK_SECURITY, ATTACH_IMAGE, etc.), has ideal-size override ~830 lines reason converged block-runner
- `app/ui/web/js/panels/action-blocks/*.js` — 4 files, block config/store/fields

### 1.4 Watcher & CDP

- `app/services/watcher_pkg/cdp.py` — 45 LOC
- `app/services/watcher_pkg/handlers.py` — 85 LOC
- `app/services/watcher_pkg/loop.py` — 125 LOC
- `app/services/new_tab.py` already, plus `app/services/single_job_runner.py`

### 1.5 App Close Cleanup

- `app/ui/main_window.py` — 332 LOC, after fix: _drop_browser_sockets uses bg_loop + run_coroutine_threadsafe, no pending Task warning, F5 reload + disconnect on close
- Docs: `docs/archive/2026-09-28-cdp-disconnect-and-grid-log/`, `2026-09-29-app-close-cleanup/`, etc.

### 1.6 JS & Listeners

- `app/ui/web/js/arena-app/listeners.js` —  listeners
- `app/ui/web/js/panels/action-blocks/*.js` — block UI

### 1.7 Quality Baseline

- `tools/quality_baseline.json` — 247 py entries after refactor (was 242)

## 2. Code Smells — Whole Branch

### Workspace (already fixed, see workspace audit S1–S15)

- S1–S15 fixed in commits 786b28d + 33e9396 (typed contexts, split apply, pure index, etc.)
- Remaining low: S9 provider.py mixing, S13 reports dict, S15 fsio race — acceptable for now

### New Tab Handover

- **N1 — File too large, single responsibility scattered**  
  File: `app/services/new_tab.py` 668 LOC, 40+ functions, dataclass _Move with 15 fields  
  Evidence: `_Move` has old_id, old_ws, old_url, label, endpoint, clients, new, old_owner, old_context, pattern, profile_count, profile_count_owner — param object but still large, functions like `_open_and_prove` does open + connect + cookie + storage + reload + prove (multiple responsibilities)  
  Violates RULE 18 file ideal 150–300, function ideal 4–20 (some functions 30+ LOC)

- **N2 — Duplicated endpoint/owner matching logic**  
  Files: `new_tab.py` `_endpoint_matches`, `_owner_matches`, `_count_profile_tabs`, `_count_profile_tabs_by_owner`  
  Evidence: 4 functions iterate pool._pages with lock, check endpoint, pattern, owner — similar loops, could be unified into `pool_matching_tabs(endpoint, pattern, owner?)` helper

- **N3 — Cookie/storage copy via JS string building**  
  File: `new_tab.py` `_get_storage_from_move`, `_set_storage_to_move`, `_get_cookies_from_move`, `_set_cookies_to_move`  
  Evidence: JS built via f-string with json.dumps payload, no validation of payload size beyond [:50] limit, error handling via broad except pass — hard to test, no seam for JS builder

- **N4 — Context verification duplicated**  
  File: `new_tab.py` `_verify_context_same`, `_context_from_targets`, `_get_old_context_id`, `_get_new_context_id`  
  Evidence: 4 functions all try to get browserContextId via _context_of or Target.getTargets — similar try/except, could be single `get_context_id(client, tab_id)` with fallback

- **N5 — Missing ideal-size override**  
  File: `new_tab.py` no `# ideal-size:` comment, but 668 LOC > 300 ideal, would fail quality gate if not in baseline? Actually baseline has it, but should have override reason per RULE 18.5

### Browser CDP Layer

- **B1 — tabs.py mixes sync HTTP + async logic**  
  File: `app/browser/cdp/tabs.py` 199 LOC  
  Evidence: `fetch_tabs_sync`, `open_tab_sync`, `close_tab_sync` use urllib sync, but also `open_tab_in_same_context` async, plus `_context_of` async — sync and async in same file, no clear boundary

- **B2 — transport.py large, handles websocket + JSON + error handling**  
  File: `app/browser/cdp/transport.py` 313 LOC  
  Evidence: 313 LOC, just over ideal 300, but has many responsibilities: connect, send, receive loop, error handling, task cancellation — could be split into transport + receiver

- **B3 — text_output_probes.py 475 LOC, JS string builders**  
  File: `app/browser/text_output_probes.py` 475 LOC  
  Evidence: Large file building JS probes for text output, similar to `dom_highlight.py` which has exception for JS payload size — but this file has no ideal-size override, should have one per RULE 18.5 (single JS payload)

- **B4 — site_adapter.py 373 LOC with override but still large**  
  File: `app/browser/site_adapter.py` has `# ideal-size: ~310 lines reason=pure-data registry` — okay, but actual 373 > 310, should update override or split

### Core Action Blocks

- **C1 — action_blocks.py 912 LOC, god file**  
  File: `app/core/action_blocks.py` 912 LOC  
  Evidence: Contains ActionBlock dataclass + BLOCK_DEFINITIONS catalog + methods for each block type — violates file ideal 150–300, but has comment `# ideal-size(reason): owns the BLOCK_DEFINITIONS catalog` — format not per RULE 18.5 (`# ideal-size: XX lines reason=...`), so quality gate may not recognize override. Should fix format or split catalog into separate file.

- **C2 — single_job_runner.py 1173 LOC with override but still very large**  
  File: `app/services/single_job_runner.py` 1173 LOC, has `# ideal-size: ~830 lines reason=single converged block-runner...` — actual 1173 > 830, override outdated, should update to ~1170 or split handlers into separate modules (e.g., `handlers/` folder)

- **C3 — Many small handlers in single file, high cognitive load**  
  File: `single_job_runner.py` has 24 block handlers + helpers like `_handler_map` returning dict literal (24 entries) — CC okay (max 9) but file large, hard to navigate, no clear ownership per handler

### UI Main Window

- **U1 — main_window.py 332 LOC, just over ideal, but fixed pending-task bug**  
  File: `app/ui/main_window.py` 332 LOC  
  Evidence: After fix, has 10+ helper functions (_drop_main_client, _drop_pool_sockets, _drop_one_pooled_tab, _run_pool_tab_cleanup_sync, _clean_pool_tab, _clear_badge_async, _hide_overlay_async, _reload_tab_async, _disconnect_client_async, _sync_drop_client) — each small, but file over 300. Has no ideal-size override, should add one per RULE 18.5 (Qt slot + cleanup helpers always change together)

### JS Panels

- **J1 — action-blocks JS files, 4 files, likely okay but need to check for duplication**  
  Files: `block-config.js`, `block-fields.js`, `block-store.js`, `action-blocks.js`  
  Evidence: These were added for new action blocks UI — need to ensure no duplicated logic, but JS lane skipped in quality gate due to missing acorn, so not checked. Should run `npm ci` + `npm run test:js` to verify.

### General

- **G1 — Many docs/archive design docs added, but no update to docs/README.md map**  
  Files: `docs/archive/2026-09-28-*`, `2026-09-29-*` (6 design docs)  
  Evidence: Each new feature adds archive doc, but `docs/README.md` may not list them — violates RULE 17 (one current doc, dated archive, map in README)

- **G2 — quality_baseline.json grows without pruning**  
  File: `tools/quality_baseline.json` 247 entries, was 242 — growth due to new files, but old entries for deleted files may remain? Should be re-recorded via `--record-baseline` after each refactor (we did)

## 3. Severity / Risk — Whole Branch

| # | File | Smell | Severity | Risk | Effort |
|---|------|-------|----------|------|--------|
| N1 | new_tab.py | 668 LOC file, 15-field dataclass, mixed responsibilities | **High** | Hard to test handover, cookie/storage copy bugs, rollback incomplete | M |
| N2 | new_tab.py | Duplicated pool iteration loops | Medium | Copy-paste bug, inconsistent matching | S |
| N3 | new_tab.py | JS string building for storage/cookies, broad except | Medium | Security, injection, silent failure | S |
| N4 | new_tab.py | Context verification duplicated 4 functions | Medium | Wrong profile, account mismatch | S |
| B1 | tabs.py | Sync+async mixed | Low | Confusion, testing | S |
| B2 | transport.py | 313 LOC, websocket+receive | Low | Hard to test receive loop | S |
| B3 | text_output_probes.py | 475 LOC, no ideal-size override | Medium | Quality gate may fail without override | S |
| B4 | site_adapter.py | 373 vs 310 override | Low | Override outdated | S |
| C1 | action_blocks.py | 912 LOC, god file, override format wrong | **High** | Hard to add new block, catalog drift | M |
| C2 | single_job_runner.py | 1173 vs 830 override | **High** | Block handler changes scatter, high cognitive | M |
| U1 | main_window.py | 332 LOC, no override | Low | Already fixed pending task, but file over ideal | S |
| J1 | JS panels | JS lane skipped, not tested | Medium | UI break, no quality gate | S |
| G1 | docs/README.md | Archive docs not mapped | Low | Doc drift, onboarding | S |

## 4. Proposed Interfaces / Boundaries — Whole Branch

### For new_tab.py (N1–N4)

- Split into modules:
  ```
  app/services/new_tab/
    __init__.py      — public handover() + setting helpers
    settings.py      — clean_url, read_setting, save_setting, wanted_url
    move.py          — _Move dataclass + _plan, _clients_on, _endpoint_from_client, _resolve_endpoint
    matching.py      — _endpoint_matches, _owner_matches, _count_profile_tabs, _count_profile_tabs_by_owner, _matches_pattern, _get_pattern → single pool_matching_tabs()
    storage.py       — _get_storage_from_move, _set_storage_to_move (JS builders extracted)
    cookies.py       — _get_cookies_from_move, _set_cookies_to_move, _cookie_base, _cookie_params, _set_one_cookie, _reload_after_cookies
    context.py       — _verify_context_same, _context_from_targets, _get_old_context_id, _get_new_context_id, _pick_client_for_context → get_context_id()
    owner.py         — _read_owner_from_client, _check_owner_preserved, _preserve_owner_after_move
    handover.py      — _hold_reconciler, _open_and_prove, _try_open_same_context, _prove_new_chat, _connect_all, _roll_back, _move_worker, _close_old, _gone, _log, _quietly
  ```
  Each file <150 LOC, functions ≤20 LOC. No behavior change, only move. `new_tab.py` becomes facade re-exporting for compat.

- Extract JS builders for storage into `app/browser/cdp/storage_probes.py` with `build_get_storage_js()`, `build_set_storage_js()` — testable via `tests/js_harness.js`

### For text_output_probes.py (B3)

- Add ideal-size override: `# ideal-size: 475 lines reason=single JS payload for text output probes; splitting string literal would break in-page contract` — same exception as `dom_highlight.py` per RULE 16.1.5

### For site_adapter.py (B4)

- Update override to actual size: `# ideal-size: 373 lines reason=pure-data registry, one SelectorObject per page element (RULE 18.2)` — or split into `selectors/` folder if grows further

### For action_blocks.py (C1)

- Fix override format to `# ideal-size: 912 lines reason=owns the BLOCK_DEFINITIONS catalog (one entry per block, always changes together per RULE 18.2)` — proper format per RULE 18.5
- Optionally split catalog into `block_definitions.py` (pure data) and keep `action_blocks.py` as dataclass + methods — but catalog + dataclass always change together, so override justified

### For single_job_runner.py (C2)

- Update override to actual: `# ideal-size: 1173 lines reason=single converged block-runner owns the block handlers sharing JobCtx; splitting handlers across files would scatter one per-image lifecycle that always changes together (RULE 18.2)`
- Long-term: extract handlers into `app/services/block_handlers/` with one file per handler, keep `single_job_runner.py` as dispatcher — but only if handlers stop sharing JobCtx tightly

### For main_window.py (U1)

- Add override: `# ideal-size: 332 lines reason=Qt MainWindow with 10 cleanup helpers that always change together (closeEvent + F5 reload + disconnect), splitting would scatter slot<->helper pairs (RULE 18.2)`

### For JS panels (J1)

- Ensure `npm ci` + `npm run test:js` passes, add JS files to `tools/quality_baseline.json` via `npm run test:js`? Actually JS metrics via acorn, need to install.

## 5. Ordered Refactor Plan — Whole Branch (small testable steps)

### Already done (workspace)

- Steps 0–9 from workspace audit — committed 786b28d + 33e9396 + 485d7b2, quality PASSED, 185 tests green

### New steps for whole branch

#### Step 10 — Add ideal-size overrides where justified (S, no behavior change)

- Files: `new_tab.py`, `text_output_probes.py`, `site_adapter.py`, `action_blocks.py`, `single_job_runner.py`, `main_window.py`
- Change: Add/update `# ideal-size: XX lines reason=...` per RULE 18.5
- Tests: `verify_quality --changed-files ... --allow-legacy` PASSED
- Rollback: Remove override comments

#### Step 11 — Split new_tab.py into package (M, structural)

- Create `app/services/new_tab/` with 7 files as proposed (settings, move, matching, storage, cookies, context, owner, handover)
- Keep `app/services/new_tab.py` as facade re-exporting `handover`, `read_setting`, `save_setting`, `wanted_url`, `clean_url` for compat
- Tests: `test_new_tab_handover.py` must still pass, plus new char tests for matching, context, owner
- Rollback: `git checkout HEAD~1 -- app/services/new_tab.py; rm -rf app/services/new_tab/`

#### Step 12 — Extract JS builders for storage (S)

- New file `app/browser/cdp/storage_probes.py` with `build_get_storage_js()`, `build_set_storage_js()`
- Update `new_tab/storage.py` to use builders
- Tests: `tests/js/test_storage_probes.mjs` via `tests/js_harness.js` (RULE 8)
- Rollback: Revert to inline JS

#### Step 13 — Fix action_blocks.py override format + split catalog (S)

- Update override comment format, optionally extract `block_definitions.py`
- Tests: existing block tests green
- Rollback: Revert

#### Step 14 — JS lane quality gate (S)

- Run `npm ci`, `npm run test:js`, ensure JS files pass metrics, record baseline
- Tests: `npm run test:js` green
- Rollback: Revert package-lock

#### Step 15 — Docs map update (S)

- Update `docs/README.md` to list new archive docs
- Update `docs/current/SYSTEM_OF_RECORD.md` if new_tab setting behavior changed
- Rollback: Revert docs

## 6. Behavior-Preservation + Rollback per Step

| Step | Preservation | Rollback |
|------|--------------|----------|
| 10 | Only comments, no logic change | Remove comments |
| 11 | Move functions verbatim, facade re-exports, existing tests pin behavior | `git checkout` old file, rm package |
| 12 | Extract JS string to builder, same JS output, test via harness | Revert builder |
| 13 | Fix comment format, optional pure data extraction | Revert |
| 14 | No prod code change, only baseline | Revert baseline |
| 15 | Docs only | Revert docs |

All steps keep `verify_quality --changed --base origin/main --allow-legacy` green and `pytest -k new_tab` green.

## 7. Tests Required Before/After Each

- Before: Existing `test_new_tab_handover.py` (14 tests) locks handover behavior, plus `test_workspace_*` (185)
- After Step 10: `verify_quality` only
- After Step 11: `pytest tests/test_new_tab_handover.py -q` + char tests for matching/context
- After Step 12: `npm run test:js` + `tests/js/test_storage_probes.mjs`
- After Step 13: `pytest tests/test_action_blocks* -q`
- After Step 14: `npm run test:js`
- Final: `pytest tests/test_workspace_* tests/test_new_tab_handover.py -q` + `verify_quality --changed --base origin/main --allow-legacy`

## 8. Documentation Changes

- Update `docs/README.md` with map to 6 new archive docs (2026-09-28/29)
- Update `docs/current/SYSTEM_OF_RECORD.md` with new_tab setting (new_chat_new_tab) behavior table
- No new top-level doc — archive docs are record

## 9. Before/After Quality Metrics — Whole Branch

### Before (origin/main 217fbe8)

- Files changed: 0 (baseline)
- Quality baseline: 242 py + 99 js, floor line 89.34 branch 86.37
- Largest files: action_blocks.py 912, single_job_runner.py 1173, new_tab.py 668, text_output_probes.py 475, site_adapter.py 373, transport.py 313, main_window.py 332

### After (485d7b2 + workspace refactor)

- Files changed: 40 (including 6 new docs, 5 new workspace modules, 2 new browser files)
- Quality baseline: 247 py + 0 js (js lane skipped due to missing acorn, need npm ci), floor unchanged
- `verify_quality --changed --base origin/main --allow-legacy` PASSED (34 py files, 0 fails, 2 warns legacy)
- `verify_quality --allow-legacy` PASSED (247 py, 0 fails)
- Workspace files now each <150 LOC, CC ≤8, after split
- new_tab.py still 668 LOC, needs Step 11 split to reach ideal
- action_blocks.py 912, single_job_runner.py 1173 still have overrides but format needs fixing (Step 13)

### Target After Full Refactor (Steps 10–15)

- new_tab/ package: 7 files each 50–120 LOC, functions ≤20 LOC, CC ≤8
- action_blocks.py override fixed format, 912 LOC with justified reason
- single_job_runner.py override updated to 1173, still large but justified per RULE 18.2 (converged lifecycle)
- All new files have ideal-size overrides where needed
- JS lane: `npm ci` + metrics, 99 js entries back
- Docs map updated
- Quality gate: no new function >30 LOC, no class >150, params ≤4, CC ≤10, cognitive ≤15, nesting ≤4
- Tests: 185 workspace + 14 new_tab + 31 char = 230+ green

## 10. Acceptance Criteria for Full Branch Refactor Done

- [x] Workspace S1–S15 fixed, quality PASSED, 185 tests green (done)
- [ ] new_tab.py split into package, 668 → 7×~100 LOC, tests green
- [ ] ideal-size overrides added/fixed for all large files (new_tab, text_output_probes, site_adapter, action_blocks, single_job_runner, main_window)
- [ ] JS lane `npm run test:js` green, baseline includes JS
- [ ] Docs README map updated
- [ ] `verify_quality --changed --base origin/main --allow-legacy` PASSED
- [ ] `verify_quality --allow-legacy` PASSED
- [ ] No behavior change: existing tests green, file formats unchanged
