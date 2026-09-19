# Area A — Run-pipeline unification + Bridge decomposition — Design (2026-09-19)

**Parent plan:** `docs/archive/2026-09-19-code-quality-implementation-plan/`
**Scope:** A1–A7 only. No B/C/D files touched (ownership: B owns dead modules,
C owns hotspots/cdp/watcher/cooldown/captcha internals).
**Gates:** RULE 16 (0 fails on new/changed files) + RULE 18 ideals
(func 4–20, file 150–300, class ≤120/≤10 methods) + RULE 19 order
(nesting → CC → cognitive → size).

Note on models: session runs on Arena Agent Mode (model fixed by platform);
the "use Opus" request cannot change the model, so this design compensates
with mechanical, verifiable steps (goldens first, one panel per commit).

## 0. Measured starting point (2026-09-19)

- Gate: **120 fails**, **52 in `app/ui/bridge.py`** (30 symbols incl. class-loc/methods).
- `Bridge`: 200 methods, **119 `@Slot`** (every public method is a slot),
  81 underscore helpers. `_do_run_batch`: **1209 LOC / CC 355 / nest 23**.
- `single_job_runner.py`: 0 fails, 12 handlers mapped; **8 block types missing**:
  `HIGHLIGHT, PAUSE, TYPE_PROMPT, HIGHLIGHT_ATTACH, HIGHLIGHT_PROMPT,
  HIGHLIGHT_SUBMIT, VERIFY_ATTACHMENT, VERIFY_PROMPT`
  (`TYPE_PROMPT` handled by the loop but not a registered block).
- Tests: **459 green**. Cognitive lib not installed → gate skips cognitive
  (kept low by construction anyway).

## 1. Contracts that must not break

1. **JS slot surface**: 119 slot names frozen (QWebChannel). Guarded by
   `tests/test_bridge_slots.py` (will scan `panels/` too after A5).
2. **Service-facing bridge API** used outside Area A (C-owned / captcha
   callers — must stay methods, call sites NOT churned):
   `_log` (RULE 2 names it), `_emit_pool_status`, `_captcha_service`,
   `_persist_cooldowns` (+ attrs `_page_pool`, `_cancel_requested`, …).
3. **`app.ui.bridge` module funcs** used by `tests/test_url_selection.py`:
   `_urls_gate_error, _checked_tabs_ready, _dedupe_state_rows,
   _tab_already_owned, _add_missing_rows` → single source moves to panels,
   `bridge.py` keeps **compat re-exports**.
4. **`Bridge.<grid helper>` binding** in `tests/test_grid_layout.py` binds 5
   helpers (`_parse_preset_input`, `_extract_*`, `_build_preset_doc`) to a fake.
   Math: 119 slots + 5 helpers = 124 > 12×10 budget → helpers become module
   functions and the test drops the (now-dead) binding loop. Zero assertion
   change; methods under test stay real (RULE 8).
5. **No `services/**` → `PySide6` imports** (source-scan seam); panels import
   Qt via one guarded shim (`app/ui/qt_compat.py`), services never import panels.
   Direction: `panels → services/core/browser`, never the reverse.

## 2. A1 — Characterization harness (goldens pin the OLD loop)

- New `tests/characterization/`: `fakes.py` (FakeCDP, scripted FakeCtrl,
  signal recorders, scripted `find_and_click`), `harness.py` (real `Bridge`
  on tmp dirs + `RUNNERS` registry + golden compare, `UPDATE_GOLDENS=1` to
  regenerate), `test_batch_goldens.py`, `goldens/*.json` (12 scenarios).
- Trace is **structural** (behavior contract, not log text):
  `events[(block_id, status)]`, `clicks[visual-runner selectors]`,
  `evals[count]`, `signals[job_started/finished]`, `images[status/error-class]`,
  `files[output basenames]`, `run_state`, plus hand-picked `log_markers`
  (substrings verified on both paths).
- 12 scenarios: happy-20-block, happy-2-images, disabled-skips,
  non-required-mid-fail-continues, required-mid-fail-breaks-job,
  cancel-before-next-block, stop-after-current, captcha-pause-resume
  (patched `handle_captcha` seam — same seam both paths use), tab-abort
  (real PagePool + `request_tab_abort`), unknown-block-skipped,
  custom-find-fallback, no-usable-tab.
- Deliberately NOT golden-pinned (paths differ by design, each covered by
  module tests instead): WAIT reload cycles / JOB-ID mismatch recovery
  (old loop) vs revival-based wait (new runner); mid-wait captcha settle.

## 3. A2 — Converge pipelines (port 8 handlers, all ≤20 LOC, params ≤3)

All in `app/services/single_job_runner.py` (stays 0-fail):
- New: `_handle_highlight`, `_handle_pause`, `_handle_type_prompt`,
  `_handle_marker_highlight` (registered for all 3 `HIGHLIGHT_*`),
  `_handle_verify_attachment`, `_handle_verify_prompt` (+ small helpers
  `_custom_fallbacks`, `_attach_open_dialog`, `_submit_visual_first`…).
- Parity fixes: emit `skipped` for disabled blocks and unknown types (was
  silent/`success`); SUBMIT order → visual-first + fallback list +
  controller last resort (RULE 1: visual confirmation first); WAIT emits the
  intermediate `waiting`/`running` status; SECURITY emits `running` while
  solving; `_mark_waiting/_mark_busy` fixed to use `_page_pool` attr
  (today they call nonexistent `_ensure_page_pool` and silently no-op —
  latent bug); `JobCtx.ext` + VALIDATE ext inference; SAVE highlight emit.
- Tests: new `tests/test_single_job_runner.py` (each handler incl. fail paths).

## 4. A3 — `batch_orchestrator.py` + `run_state.py` (new, 0-fail)

- `batch_orchestrator.py`: `BatchCtx` + `should_continue`,
  `await_pause_or_abort`, `resolve_and_claim_tab`, `await_cooldown_if_pooled`,
  `mark_processing`, `build_job_ids`, `finish_image`, `run_batch` (+ tiny
  `prepare_batch`/`finalize_batch`), each ≤20 LOC / CC≤7 / params≤3.
  Replicates legacy semantics exactly: parallel-dispatch probe, batch-ready
  gate, per-image flow, cancel ⇒ no `job_finished` + stop batch,
  rate-limit note, finish-page, 1s spacing, idle+emit at end.
- `run_state.py` (the plan's "scheduling seam"): decomposed `ensure_bg_loop`
  + `schedule_coro` (fixes 2 gate fails) + shared tab/pool glue
  (`resolve_tab_info`, `ensure_pool_page`, `restore_page_state` + sub-helpers)
  used by BOTH orchestrator and panels (single source, ui→services direction).

## 5. A4 — Flip + delete

- `start_run` schedules `run_batch(self)`; delete `_do_run_batch` (1209 lines)
  and helpers used exclusively by it (verified by grep per symbol);
  `schedule_coro` batch-future heuristic `_do_run_batch` → `run_batch`.
- Harness `RUNNERS`: legacy → orchestrator. **Same 12 goldens stay green.**

## 6. A5 — Bridge → 12 panel mixins (each ≤300 lines, ≤10 methods)

- `app/ui/panels/`: 12 files, each = ONE mixin (slots only) + module functions.
  Packing (11×10 + 1×9 = 119, verified by script during implementation):
  `run_control, watcher_captcha, page_pool, browser_tabs, url_queue,
  queue_scan, blocks_stack, blocks_library, undo_history, layout_state,
  app_settings, cdp_tools` (exact slot assignment in implementation log).
- `bridge.py` keeps: signals, `__init__` (A6), 8 tiny API methods
  (`_log` full; `_emit_pool_status`, `_persist_cooldowns`, `_captcha_service`
  full; `_get_action_blocks`, `_emit_job_action_status`, `_save_arena`,
  `_emit_arena_state` as 3-line delegations to panel functions) + compat
  re-exports. Target: file ≤300, class ≤120 LOC / ≤10 methods.
- All 30 failing symbols decomposed in RULE 19 order while moving
  (dispatch tables for undo/connect/settings/presets; per-section splits for
  `_arena_to_js`, thumbnail, scan, watcher-config, cdp-config…).
- `@Slot` lives on mixin methods; `Bridge(QObject, *mixins)` inherits them
  (standard PySide6 inheritance; names guarded by updated AST test).
- Overflow rule: if a panel cannot fit 300 lines after decomposition, logic
  moves DOWN to services/core/ui-services (never a 13th panel, never gaming).

## 7. A6 — `__init__` 122 LOC → `BridgeContext` + `_wire_*()` ≤15

- New `app/ui/bridge_context.py`: `BridgeContext` dataclass + `build_context()`
  + `wire_cdp/wire_watcher/wire_page_pool/wire_thumb` (each ≤15 LOC).
- `Bridge.__init__` ≤20 LOC: `super().__init__`, build, attach attrs
  (same attribute surface — no caller changes), wire, log version.
  Also inits `_batch_future = None` (today only set on first run).

## 8. A7 — Sweep + recheck

- Orphan/dead-import sweep of Area A files; `test_bridge_slots.py` scans
  panels; `SYSTEM_OF_RECORD.md` §7 + `docs/README.md` updated (RULE 17);
  `implementation-area-a.md` written; full gate + suite + coverage;
  RULE 18 audit table (every ideal deviation carries `ideal-size:` reason).

## 9. Risks

- Inherited Qt slots: mitigated by frozen-name AST test + unchanged
  `registerObject` call; no Qt in CI to runtime-prove (documented).
- Golden brittleness: structural traces only; volatile ids normalized.
- Panel packing math: verified by script, not by eye.
