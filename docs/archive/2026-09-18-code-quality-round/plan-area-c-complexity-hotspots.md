# Area C — Complexity hotspots outside bridge (Python + JavaScript)

**Problem fixed:** P7 (Medium-High), P8 (Medium), P9-JS.
**Branch (recommended):** `arena/quality-c-hotspots` — runs in parallel with Area D.
**Owns (writes):** `app/browser/{cdp_client,cdp_arena,output_wait,output_state,output_probes,dom_highlight,visual_click}.py`,
`app/services/{watcher,verification,cooldown_service}.py`,
`app/core/{scanner,persistence,undo_service,layout_service,naming,models,action_blocks}.py`,
`app/persistence/preset_store.py`, `app/ui/main_window.py`, `app/ui/web/js/**`,
new `tests/test_*_refactor.py` + `tests/js/*.mjs` **new files only**.
**Must not touch:** `app/ui/bridge.py`, `app/ui/panels/**` (Area A), `app/services/job_runner.py`
(deleted by B), `tests/**` existing files owned by A/B/D.

## Why

After Areas A and B, `Bridge` and the dead stack are gone; what remains is the
ordinary tail: **51 fails across 18 files**, one hot symbol per file, all
fixable locally with the RULE 19 order (nesting → CC → cognitive → size).
The JS lane is the same story with no gate at all.

## Steps — biggest problem first (Python)

### C1 — `watcher.check_once`: 124 LOC · CC 35 · cognitive 82 (the worst live function)

`app/services/watcher.py` — `WatcherService` is 269 LOC with 15 methods; `check_once`
holds the entire scan → decide → dispatch → cooldown → overlay flow nested in
one body. Split by **decision**, not by line count:

| Extract (≤20 LOC, CC ≤7) | Decision it names |
|---|---|
| `_collect_queue_snapshot(...)` | what images are eligible now |
| `_should_dispatch(...)` | run-idle / stop-after / pause gates |
| `_pick_dispatch_target(...)` | which image (oldest ready, folder filter) |
| `_announce_overlay(...)` | watcher overlay + log lines |
| `check_once(...)` | ≤20 LOC: snapshot → should → pick → dispatch → report |

Class: keep ≤150 LOC by moving overlay/persistence helpers into
`app/services/watcher_overlay.py`.
Verify: existing `tests/test_watcher.py` + `tests/test_watcher_overlay.py` green;
new tests for each extracted decision (they currently have no direct coverage);
nesting ≤3, CC ≤10 for the whole file.
Target: watcher.py 306 → ≤300 lines with 0 fails; coverage 27.4% → ≥80%.

### C2 — `cdp_client.py`: 647 LOC · class 469 LOC / 22 methods · 15 fails

`_connect_inner` CC 27 / cognitive 41, `fetch_tabs_sync` 36 LOC / nesting 5,
`connect` CC 13, plus `query_selector_all`, `_is_devtools_url`, `_filter_real_tabs`
flagged unused. Split by transport concern into a package:

```
app/browser/cdp/transport.py   socket + send/recv + lock (I-22 invariant stays here)
app/browser/cdp/connect.py     version/target discovery, devtools filtering
app/browser/cdp/tabs.py        fetch_tabs_sync → small helpers per fallback step
app/browser/cdp/probe.py       evaluate/probe helpers (JS payload passing)
app/browser/cdp_client.py      ≤150-line facade keeping the current public API
```
Verify: existing fakes (`tests/fakes/fake_cdp.py`) drive new unit tests for
connect/tabs/probe; the facade keeps the exact method names `cdp_arena.py`,
`page_pool.py` and `bridge.py` call (grep-verified); no behaviour change in the
connect lock ordering (I-22).
Target: 15 fails → 0; class 469 → ≤150 LOC; coverage 9.3% → ≥80% for the new modules.

### C3 — `cdp_arena.py`: class 371 LOC / 30 methods · 3 fails

`highlight_selector` CC 13 (highlight phases), plus attach/submit/wait methods.
Split into `cdp_arena_highlight.py` (find/click/clear overlays, RULE 1 colours),
`cdp_arena_attach.py` (attach + verify attachment), `cdp_arena_submit.py`
(submit + send-ready), keeping `CDPArenaController` as the ≤150-LOC composition
root that the pipeline calls. RULE 1 single-runner contract unchanged.
Verify: `tests/test_cdp_arena_submit.py` + new tests per module; overlay colour
constants still imported from `probe_requests.py` (no literals re-introduced).
Target: 3 fails → 0; coverage 29.4% → ≥80%.

### C4 — `verification.validate_downloaded_file`: 42 LOC · CC 14 · nesting 5

Flatten with guard clauses (RULE 19 step 1) and separate the three decisions:
`is_html_response(bytes)`, `has_valid_image_dimensions(bytes)`, `is_nonempty(bytes)`;
`validate_downloaded_file` becomes ≤15 LOC composing them, returning a
`ValidationResult` dataclass (I-13 fail-closed semantics unchanged).
Verify: `tests/test_verification.py` extended with the negative matrix
(HTML, zero-byte, 1×1, undecodable) — each predicate gets a failing-on-delete test.
Target: 3 fails → 0; coverage 38.8% → ≥90%.

### C5 — Core `core/` fixes (5 fails, small each)

| Symbol | Now | Action |
|---|---|---|
| `persistence.reconcile_with_filesystem` | 101 LOC · CC 21 · cog 34 | split into `_read_known`, `_discover_new`, `_remove_missing`, `_merge`; the file keeps a ≤20-LOC orchestrator |
| `scanner.scan_folder` | 66 LOC · CC 13 · cog 21 | replace the `if/elif` filter chain with a predicate table (RULE 19 step 2: dispatch instead of branching) |
| `undo_service.undo` / `kind_projection` | 38 LOC / CC 12 | dispatch table per undo kind (kinds are already an enum), ≤20 LOC each |
| `layout_service.normalize_grid_tree` | cog 21 | name the predicates (visible/leaf/hidden), early returns (I-11 validation unchanged) |
| `naming.get_output_path` / `models.create` | 6 and 5 params | parameter object (`OutputSpec`, `ImageSpec`) — the only 2 of the 6 param failures in this area |
| `action_blocks` (2 fails) | 716 LOC | split definitions data from behaviour (data module + stack ops); the file is data-heavy but its functions still breach |
Verify: existing `tests/test_scanner.py`, `tests/test_persistence.py`, `tests/test_undo.py`,
`tests/test_grid_layout.py`, `tests/test_naming.py` stay green; add the
predicate-table cases the refactor introduces.
Target: 5 fails → 0; each edited file ≥80% covered.

### C6 — `output_wait` / `dom_highlight` / `main_window` / `preset_store` (7 fails)

* `output_wait.wait_for_new_output_loop` — 5 params + CC 12 + cognitive 30:
  introduce `WaitSpec` (timeout, poll, stop-flag, on_diag, baseline) and split
  the poll body into `_poll_once` (≤20 LOC); I-6 (stop inside inner waits) must
  keep its early-exit test.
* `dom_highlight.build_highlight_rect_js` (7 params) and `build_highlight_js`
  (5 params) — these build one JS literal each; replace params with a
  `HighlightSpec` dataclass (already exists in `probe_requests.py`) and keep the
  payload contract byte-identical (test asserts the rendered string).
* `preset_store` 22 methods → split into `preset_store_read.py` /
  `preset_store_write.py` behind the existing class API.
* `main_window.__init__` 31 LOC → `_build_services()` + `_build_ui()`.
Verify: existing tests + the payload-equality test; no parameter object may
change a public signature used by bridge (grep).
Target: 7 fails → 0.

## Steps — JavaScript lane (same rules, after Round 0 adds the JS gate)

### C7 — Split the panels and extract pure logic (tests first)

Order by measured size:

| File | Lines | Worst function | Action |
|---|---:|---|---|
| `panels/action-blocks.js` | 838 | anon 169 LOC / CC ≈90; second 126 LOC | extract `block-store.js` (data/CRUD) + `block-config.js` (config form) + `block-render.js`; keep the panel as a ≤200-line coordinator |
| `panels/arena-presets.js` | 358 | 97 LOC, 75 LOC, 72 LOC (render + import/export) | split model (load/save/validate) from view |
| `panels/image-queue.js` | 396 | 73 LOC, 61 LOC (depth 10), 61 LOC | extract row-state helpers + status rendering |
| `panels/cdp.js` | 549 | 71 LOC, 59 LOC | split connect view from pool view; **de-duplicate with `panels/url-list.js` (17-line clone)** |
| `arena-app.js` | 333 | `setupBridgeListeners` 164 LOC / CC ≈66 | build a listener registry table (dispatch, not a wall of `if`), one handler per ≤20-line function |
| `arena-history.js` | 251 | 81 LOC / depth 11 | flatten the nested diff loop (RULE 19 step 1) |
| `panels/{watcher,page-pool,settings,url-list,folder-picker}.js` | 217–447 | 26–66 LOC | extract per-decision helpers as needed to reach the JS gate |

Rules: every extracted pure function gets a `tests/js/*.mjs` test (Tier A,
`node --test`, no browser); DOM-only code is covered by the existing harness
(`tests/js/sash_harness.mjs`, jsdom after `npm ci`).
Target: functions > 30 LOC 48 → ≤10; nesting > 4 24 → 0; files > 300 lines 8 → ≤3;
all panels pass the new JS gate with no baseline entry for new files.

### C8 — JS duplication and payload hygiene

Remove the `cdp.js` ↔ `url-list.js` clone and repeated panel boilerplate into
`app/ui/web/js/core/ui-helpers.js` (currently 105 lines, already the home for
shared DOM helpers); add `c8` coverage instrumentation for the JS lane so the
JS number exists next round.

## Acceptance criteria (area exit)

* [ ] gate fails 104 → **≤5**, all of them documented `quality-override:` with a named constraint
* [ ] Python: 0 functions > 30 LOC outside `app/ui/bridge.py` (Area A's), 0 nesting > 4, 0 classes > 150 LOC, params ≤ 4 everywhere
* [ ] every edited/created function ≤20 LOC, CC ≤7, cognitive ≤10, nesting ≤3
* [ ] files created/edited are 150–300 lines (data modules exempt, with `# ideal-size:` reason)
* [ ] coverage of every module touched ≥80% line; global coverage never decreases
* [ ] JS gate green for all files with no new baseline entries; JS functions > 30 LOC ≤ 10; JS files > 300 lines ≤ 3
* [ ] `npm run test:js` green and includes a test for every extracted pure function
* [ ] no public API used by `bridge.py` changed without a grep-verified same-name replacement

## Risks and rollback

| Risk | Mitigation |
|---|---|
| `cdp_client`/`cdp_arena` split breaks the live browser path | fakes + smoke run (`tests/manual_test_checklist.md`); keep a facade with the exact old method names; I-22 lock ordering asserted by test |
| JS split breaks the QWebChannel/panel wiring | keep file headers/global names (`SashCore`, panel factory names) stable; jsdom harness loads each panel; run the app once per PR |
| Payload-equality tests too brittle for JS literals | compare normalised whitespace, assert the selector/semantic content (that is the real contract) |
| Overlap with Area A in `bridge.py` calls | A is finished first for the pipeline; C never edits `bridge.py` — if a call site must change, it is raised to A's owner |
| Rollback | file-scoped commits; the split is mechanical, revert per file |
