# Area A — Implementation log (2026-09-19)

Parent design: `docs/archive/2026-09-19-area-a-bridge-pipeline/design.md`
(full A1–A7; this file records what actually happened per step).

## A1 — Characterization harness (commit `99eef38`, with A2–A3)

- New `tests/characterization/`: `fakes.py`, `harness.py`, `test_batch_goldens.py`,
  `goldens/*.json` (12 scenarios). Structural traces only; volatile ids normalized.
- Verdict: 473 passed, gate TOTAL 120 (baseline, no new fails).

## A2 — Converge pipelines (commit `99eef38`, with A1/A3)

- `app/services/single_job_runner.py`: 20 block types (ported 8 missing handlers),
  ~832 lines with `ideal-size:` reason; visual-first submit; skipped emits;
  `_mark_waiting/_mark_busy` `_page_pool` fix; `JobCtx.ext`.
- `tests/test_single_job_runner.py`: 20 handler tests. 493 passed, 0 fails on file.

## A3 — Orchestrator + run-state seam (commit `99eef38`, with A1–A2)

- New `app/services/run_state.py` (~380 lines, reasoned): bg loop, schedule,
  tab/pool ensure/restore, cooldown persist — shared by orchestrator AND panels.
- New `app/services/batch_orchestrator.py` (~480 lines, reasoned): `BatchCtx` /
  `ImageResult` + prepare / parallel-gate / sequential / finish + `run_batch`.
- `tests/test_run_state.py` + `tests/test_batch_orchestrator.py`: 36 tests.
- 529 passed, 0 fails on new files.

## A4 — Flip + delete (commit `324c9e4`, with A5.1–A5.4)

- `start_run` schedules `run_batch(self)`; deleted `_do_run_batch` (1209 lines)
  + 11 loop-exclusive helpers (grep-verified per symbol); heuristic flipped.
- Harness `RUNNERS`: legacy → orchestrator. **Same 12 goldens green, zero drift.**
- `bridge.py` 4989 → 3761 lines. 529 passed, gate TOTAL 115.

## A5 — Bridge → 12 panel mixins

Packing decision (proven by exhaustion during implementation; the design doc's
`11×10+1×9` sketch is incoherent — the 9 homeless STATE/FILE/FOLDER-AI slots
cannot fill the TABS/URL/LIB/CDP holes without gaming, and `page_pool` admits
no 10th member while `browser_tabs` admits no coherent growth from the
surplus; forcing the numbers would split coherent families or stretch
assignments, violating RULE 1 + the no-gaming rule):

| Panel | Slots | Notes |
|---|---|---|
| `run_control` | 10 | 5 run + retry/retry/reset/reset/clear (run lifecycle) |
| `watcher_captcha` | 10 | 7 watcher + 3 captcha |
| `page_pool` | 9 | pool + cooldown (no coherent 10th; stays 9) |
| `browser_tabs` | 7 | tab discovery/connect/popup/find/diag |
| `url_queue` | 9 | URL CRUD + test + 4 URL presets |
| `queue_scan` | 12 | scan + queue + queue file tools + folder-AI (`ideal-size:` reason: frozen JS queue surface; file/AI tools operate on queue items) |
| `blocks_stack` | 10 | 6 stack + 3 stack presets + save_stack_history |
| `blocks_library` | 9 | 5 library + 4 prompt presets |
| `undo_history` | 10 | 6 undo + 4 stack-history |
| `layout_state` | 14 | grid + window states/presets + app/arena state accessors (`ideal-size:` reason: frozen JS layout/state surface; accessors serialize layout-owned stores) |
| `app_settings` | 10 | prompt/settings/import-export + 4 arena presets + theme + refresh shim |
| `cdp_tools` | 9 | CDP config + test flows + highlight tools |

Sum 119. All ≤ 15 (RULE 16 hard line); the two deviations carry reasons.
Rules applied per panel: mixin holds slots only (class LOC ≤ 150 hard, thin
slots delegate to module funcs); helpers → panel module funcs or ui-services;
shared-by-2+ → services; panels never imported by services; Qt via
`app/ui/qt_compat.py` only. `Bridge` ends at `__init__` + 9 API methods
(4 full + 5 delegations; `_emit_action_blocks` added — called by the
orchestrator) + signals + compat re-exports.

### A5.1–A5.4 first four panels (commit `324c9e4`, with A4)

- A5.1 `layout_state` (+ `qt_compat` shim, `arena_serialize`,
  `window_preset_service`): 14 slots, grid/window/preset/arena surface.
- A5.2 `blocks_library`: 9 slots, custom blocks + prompt presets.
- A5.3 `blocks_stack`: 10 slots, action-block stack + stack presets.
- A5.4 `undo_history`: 10 slots, undo timeline + stack/grid history.

### A5.5–A5.12 remaining panels (R2–R9, one commit each)

- A5.5 `url_queue` (`153eaa6`, R2): 9 slots + I-33 ownership helpers;
  bridge keeps compat re-exports (contract §1 item 3, live via
  `tests/test_url_selection.py`). Kills 0.
- A5.6 `queue_scan` (`34912b5`, R3): 12 slots + `file_service.py` /
  `folder_ai_service.py` + `selected_images` + `merge_scanned`. Kills 7.
- A5.7 `app_settings` (`4e9055e`, R4): 10 slots, dispatch-split
  save/import/preset flows. Kills 7.
- A5.8 `watcher_captcha` (`1681ff1`, R5): 10 slots (7 watcher + 3
  captcha). Kills 1.
- A5.9 `page_pool` (`3713414`, R6): 9 slots + run_state cooldown flip
  (bridge/restore twins deleted after equivalence proof). Kills 0.
- A5.10 `browser_tabs` (`5906d92`, R7): 7 slots, connect/find phase
  splits, 7 schedule flips; 87/87 behavior checks. Kills 7.
- A5.11 `cdp_tools` (`df2d2df`, R8): 9 slots, `HighlightArgs` params,
  shared `read_cdp_config`; 70/70 behavior checks. Kills 4.
- A5.12 `run_control` (`df85287`, R9): 10 slots, F8 `JobAction` seam,
  last schedule flips, `_ensure_bg_loop`/`_schedule_coro` deleted;
  39/39 behavior checks. Kills 7.

A5 end state: `bridge.py` 2710 → 159 lines, 125 → 10 direct methods,
slots 119 = 0 bridge + 119 panel, gate TOTAL 97 → 64 (bridge 35 → 2).
Each panel round verified 119/119 slots + suite green + gate diff.

## A6 — BridgeContext (commit `7158247`, R11)

- New `app/ui/bridge_context.py` (196 lines): `BridgeContext` dataclass
  + `build_context()` + `wire_cdp/wire_watcher/wire_page_pool/wire_thumb`
  (≤15 LOC) + run/tracking flag groups + config/endpoint/log splits.
- `Bridge.__init__` 122 → 15 LOC, straight-line; `_batch_future=None`
  initialized (was lazy); dead `_watcher_cb` dropped; `_log_build_version` /
  `_on_cdp_error` → module funcs. Kills 2 (`__init__`×2) — bridge 0 fails.
- +8 construction tests (`tests/test_bridge_context.py`).

## A7 — Sweep (R12)

- Vulture (`--min-confidence 90`, @Slot whitelist per F15) + per-file
  unused-import sweep: removed 10 dead imports
  (`Slot`, grid/model/scanner orphans, unmarked service imports in
  `bridge.py`; `Any/Dict/List/Tuple` in `window_preset_service.py`);
  only accepted findings are the 5 contract re-exports (live test users)
  and `_`-prefixed dummy args. Area A clean.
- F5: `test_frozen_slot_surface_exact` (119 names, exact match).
  F6: `test_panel_packing` (per-panel counts + total) +
  `test_bridge_direct_methods_capped` (≤10, slots live in panels).
- F7: `tests/test_file_dialogs.py` — fake-QFileDialog branches for all 5
  dialog sites (layout export/import, stack export, settings import,
  pick_folder incl. cancel/headless).
- Coverage baseline (2026-09-19, `coverage run --branch --source=app`,
  590 green): whole-app line 59.1% / branch 50.1% (never-decrease
  anchor per RULE 16.3); every R10/R11/R12-scope function hit
  (R10 helpers, `bridge_context`, file/folder-ai/scan services,
  shim clipboard, runner wait/settle/stop paths).
- R10 ideals sweep (`dd6e925`, part of A7 preparation): 8 extracts
  (all mains ≤20 LOC / ≤7 CC), 3 ideals-TABLED notes (`_handler_map`,
  `_handle_wait`, `settings_to_js`), 4 `ideal-size:` class reasons,
  clipboard centralized into `qt_compat` (panels PySide6-free).
- Docs (RULE 17): this log finished; SYSTEM_OF_RECORD.md §7 rewritten
  to the Area A end-state; docs map archive entry added.
- F17 (follow-up, NOT A7): committed tests for the ~200 moved slot
  bodies/helpers (0-hit by construction — proven equivalent by the
  per-round differential scripts: R7 87/87, R8 70/70, R9 39/39, results
  recorded in `review-and-improvement-plan.md`; scripts were /tmp
  point-in-time proofs, not committed).

Area A end state: 590 green, gate TOTAL 62 (bridge 0), Bridge 159 lines /
10 methods, 12 panels + `bridge_context` + 8 ui-services, direction
panels→services/core/browser + one Qt shim holds (F13 closed, F14 stands).
