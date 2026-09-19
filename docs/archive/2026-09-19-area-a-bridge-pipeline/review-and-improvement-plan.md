# Area A — Review vs spec + improvement plan (2026-09-19)

Parent design: `docs/archive/2026-09-19-area-a-bridge-pipeline/design.md`
(§1 contracts, §2–§8 steps). Progress log:
`docs/archive/2026-09-19-area-a-bridge-pipeline/implementation-area-a.md`

Measured review state: **551 passed, gate TOTAL 105** (baseline 120),
`bridge.py` 2713 lines / 37 fails (was 52), 119/119 slots present
(76 in `bridge.py`, 43 in 4 panels), **0 fails on all Area A new files**.

## 1. Review verdict per step

| Step | Spec | Actual | Verdict |
|---|---|---|---|
| A1 harness | 12 scenarios, structural traces, RUNNERS registry | 12 goldens, 14 characterization tests, all green | ✅ complete |
| A2 converge | 8 handlers ≤20 LOC, params ≤3, parity fixes | 20 types, 0 fails; new funcs ≤3 params; 2 new-func ideals misses (see F4) | ✅ complete, ideals notes |
| A3 seam | orchestrator + run_state, ≤20/CC≤7/≤3 params | 0 fails, 36 tests; 3 new-func ideals misses (see F4) | ✅ complete, ideals notes |
| A4 flip | delete loop, same 12 goldens green | loop + 11 helpers deleted, zero drift | ✅ complete |
| A5 panels | 12 mixins ≤300 lines ≤10 methods; bridge = signals+`__init__`+8 API | 4/12 cut; packing adjusted to (10,10,9,7,9,12,10,9,10,14,10,9) — doc's `11×10+1×9` proven incoherent (see log); bridge keeps 9 API (doc: 8) — `+_emit_action_blocks`, forced by orchestrator caller | 🟡 in progress, 2 deviations reasoned |
| A5 tests | slots test scans panels; grid loop dropped | ✅ both done | ✅ |
| A5 direction | panels→services; no services→Qt | ✅ new files clean (2 pre-existing Qt imports grandfathered, not Area A) | ✅ |
| A6 context | `BridgeContext` + `_wire_*()` ≤15, `_batch_future=None` | not started | ⬜ pending |
| A7 sweep | vulture, docs, coverage, RULE 18 audit | not started | ⬜ pending |

Findings (F = must fix or decide):

- **F1 — Commits lost.** Prior session's commits (A1–A5.3) are absent;
  all work sits uncommitted in the tree. R0 re-commits in logical chunks.
- **F2 — `undo_entries.py` 403 lines has no `ideal-size:` reason** (RULE 18.5).
  Keep one file (remember/apply/empty twins share kind vocabulary + row
  builders; splitting would scatter twins) + add reason.
- **F3 — Bridge delegations use lazy imports.** No import cycle exists
  (panels never import bridge), so hoist to top-level module imports.
- **F4 — New-code ideals misses** (all RULE 16-legal, fix the clean ones,
  audit-table the rest): `restore_page_state` 26 LOC, `_move_to_tab` CC 8,
  `_emit_job_finished` 4 params, `_handle_type_prompt` CC 8,
  `build_preset_doc` 4 params, `settings_to_js` 21 LOC,
  `export/import_preset_file` 22 LOC each, `save_preset_doc` 4 params,
  `check_security` 24 LOC (A2-touched legacy).
- **F5 — Slot freeze is partial.** `test_bridge_slots.py` guards ~25 of 119
  names; contract §1 freezes all 119. Add exact-match frozen set.
- **F6 — Packing unverified by script.** Design doc requires packing
  "verified by script"; add `tests/test_panel_packing.py` (per-panel counts
  + total 119 + Bridge ≤10 direct methods) once A5/A6 land.
- **F7 — Coverage not yet run for Area A** (RULE 16.3). Run branch coverage
  at A7; add dialog-fake tests for file-dialog branches (Qt absent in CI).
- **F8 — `_emit_job_action_status` 5-param seam** (legacy fail). Redesign to
  a `JobAction` event dataclass in the run_control commit (panel func takes
  2 params; Bridge keeps the 5-arg signature for the runner seam).

## 2. Improvement steps (implement in order)

Each step: implement → targeted tests → `verify_quality.py` (0 new fails) →
commit. Full suite at R1 end, every 2 panels, and R10/R11.

- **R0 — Preserve.** Chunk-commit the tree: (1) A1–A3 pipeline
  (characterization, single_job_runner, run_state, orchestrator + tests);
  (2) A4+A5.1–A5.4 (bridge.py, panels, qt_compat, ui-services, tests, log).
- **R1 — Ideals hardening.** F2 reason; F3 top-level delegation imports;
  F4 clean fixes: extract `_log_restore_miss` (run_state), `_pool_ws`
  (orchestrator), derive status/message inside `_emit_job_finished`
  (2 params), extract `_type_highlight` (runner), fold `stored_ws` into
  `info` (build_preset_doc → 3 params), extract `_write/_read_preset_doc`
  (preset files → ≤20); `__all__` in qt_compat; keep+extend tests.
- **R2 — `url_queue` (9).** Move CRUD/test/URL-presets + 5 URL module funcs;
  bridge keeps compat re-exports (contract §3); `_checked_tabs_ready` uses
  `bridge.state.urls` (fake-compatible, zero test change). Kills
  `_resolve_tab_info`? No — that dies in R7 (last caller). Kills: none (all
  small); adds re-exports.
- **R3 — `queue_scan` (12, reasoned).** Move scan/queue/file-tools/folder-AI;
  thin slots; delegate thumbnail to `thumbnail_service`, reveal/copy to new
  `ui/services/file_service.py`, folder-AI worker to
  `ui/services/folder_ai_service.py`, scan bodies via `scan_service`;
  `selected_images(images)` pure helper (run_control imports it).
  Kills 7 fails: thumbnail×2, reveal, copy×2, scan×2.
- **R4 — `app_settings` (10).** Move prompt/settings/import-export/arena
  presets/theme/refresh; dispatch-split `save_settings` (per-section),
  `import_preset`, `save_arena_preset`, `load_arena_preset` (per-section).
  Kills 7 fails.
- **R5 — `watcher_captcha` (10).** Move watcher+captcha slots; split
  `set_watcher_config` (per-key); `_get_watcher_cdp_controller` /
  `_on_watcher_state` → module funcs + `__init__` lambda edits. Kills 1.
- **R6 — `page_pool` (9).** Move pool/cooldown slots; `_do_connect_page_pool`
  + `_reset_stuck_page` → module funcs (run_state calls);
  `_persist_cooldowns` → Bridge delegation to run_state (contract §2);
  delete `_restore_*`, `_cooldowns_path` after flipping to run_state
  (verify callers). Kills 0 fails, deletes ~100 LOC.
- **R7 — `browser_tabs` (7).** Move tab slots; split `_do_connect_tab`
  (phases), `_do_find_tab`, `_report_auto_plan`; auto-plan helpers →
  module funcs (reuse `app/services/auto_connect.py`); flip
  `_schedule_coro` sites to `run_state.schedule_coro`; delete
  `_resolve_tab_info`, `_pooled_ids` after last flip. Kills 5.
- **R8 — `cdp_tools` (9).** Move CDP config/test/highlight slots; split
  `set_cdp_config` (per-key), `_do_highlight`, `cdp_attach_image_test`;
  `_do_cdp_*`, highlight demo → module funcs; flip `_schedule_coro` sites.
  Kills 4.
- **R9 — `run_control` (10).** Move run-lifecycle slots; split `start_run`
  (gate checks); F8 `JobAction` redesign (`_emit_job_action_status` →
  delegation); `enabled_urls(urls)` pure helper in url_queue, imported;
  flip last `_schedule_coro` sites; **delete** `_ensure_bg_loop`,
  `_schedule_coro` (run_state owns). Kills 8 (start_run + emit_job×3 +
  bg-loop×2 + schedule×2).
- **R10 — A6 `BridgeContext`.** `app/ui/bridge_context.py`: dataclass +
  `build_context()` + `wire_cdp/wire_watcher/wire_page_pool/wire_thumb`
  (≤15 LOC); `Bridge.__init__` ≤20 (attach same attrs, init
  `_batch_future=None`); `_log_build_version`/`_on_cdp_error` → module
  funcs. Kills `__init__`×2; Bridge class-loc/methods fixed by composition.
- **R11 — A7 sweep.** (a) vulture + unused-import sweep, Area A clean;
  (b) F5 frozen-119 test; (c) F6 packing test; (d) branch coverage ≥80/75,
  no uncovered new funcs (dialog-fake tests as needed); (e) finish
  implementation log; SYSTEM_OF_RECORD.md §7 + docs/README.md (RULE 17);
  (f) RULE 18 audit table (every deviation reasoned); full gate + suite.

Expected end state: TOTAL ≈ 105 − 37 = **68** (all `bridge.py` fails gone),
suite green, Bridge ≈ 300 lines / 10 methods, 12 panels + 8 ui-services.
