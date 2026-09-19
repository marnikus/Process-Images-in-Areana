# Area A — Implementation log (2026-09-19)

Parent design: `docs/archive/2026-09-19-area-a-bridge-pipeline/design.md`
(full A1–A7; this file records what actually happened per step).

## A1 — Characterization harness (commit `c03260e`)

- New `tests/characterization/`: `fakes.py`, `harness.py`, `test_batch_goldens.py`,
  `goldens/*.json` (12 scenarios). Structural traces only; volatile ids normalized.
- Verdict: 473 passed, gate TOTAL 120 (baseline, no new fails).

## A2 — Converge pipelines (commit `41329ae`)

- `app/services/single_job_runner.py`: 20 block types (ported 8 missing handlers),
  ~832 lines with `ideal-size:` reason; visual-first submit; skipped emits;
  `_mark_waiting/_mark_busy` `_page_pool` fix; `JobCtx.ext`.
- `tests/test_single_job_runner.py`: 20 handler tests. 493 passed, 0 fails on file.

## A3 — Orchestrator + run-state seam (commit `c6a3d76`)

- New `app/services/run_state.py` (~380 lines, reasoned): bg loop, schedule,
  tab/pool ensure/restore, cooldown persist — shared by orchestrator AND panels.
- New `app/services/batch_orchestrator.py` (~480 lines, reasoned): `BatchCtx` /
  `ImageResult` + prepare / parallel-gate / sequential / finish + `run_batch`.
- `tests/test_run_state.py` + `tests/test_batch_orchestrator.py`: 36 tests.
- 529 passed, 0 fails on new files.

## A4 — Flip + delete (commit `a0637eb`)

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

### A5.1 `layout_state` (+ `qt_compat`, `arena_serialize`, `window_preset_service`)

- …
