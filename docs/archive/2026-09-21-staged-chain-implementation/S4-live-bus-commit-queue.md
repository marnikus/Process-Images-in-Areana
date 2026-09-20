# S4 — LiveBus + `commit_queue` funnel + reset re-queues (D-6R)

*Chain stage 4 of the staged chain per `docs/archive/2026-09-20-dynamic-urls-and-worker-debug/`,
implemented 2026-09-21 on top of S3 (`c22ce1d`, plus the `bb3bc23` S2 follow-up). Contract:
`tdd-interfaces.md` §S4; plan invariants I-39…I-46 land as **I-47…I-54** (merge-note).*

## What landed

- **New package `app/services/live/`** —
  - `bus.py`: `LiveBus` — one durable wake channel per bridge. `threading.Lock + deque(reasons)`,
    `attach(loop)` lazily binds an `asyncio.Event`, `wake(reason)` is thread-safe
    (`loop.call_soon_threadsafe`, safe with no loop), `wait(timeout)` drains ONE reason or
    answers `""`, `throttle(key, window_ms)`, `reasons()` non-destructive drain for the debug
    window. `live_bus(bridge)` is the lazy accessor.
  - `feed.py`: `eligible_images(images)` delegates to `core.run_scope.in_run_scope` minus
    `processing` (no rule clone); **`commit_queue(bridge, reason, undo=True)`** — THE funnel:
    `recalculate_progress` (under `bridge._state_lock` if present, else `nullcontext`) →
    `_save_arena()` (which emits per I-39 — so save+emit is ONE step, not two) → undo hook →
    `live_bus(bridge).wake(reason)` → returns the eligible count; `recover_stale_processing(bridge)`
    re-queues `processing` rows whose basename no pool page reports as `current_image`
    (basename matching — dispatchers store basenames via `cooldown_service.set_tab_image`);
    `clear_row_assignments(bridge, row_ids)`; `reset_to_pending(img)` (D-6R: re-SELECTS).
    Undo reaches the panel layer via the module hook (`feed.set_undo_hook`), because services→ui
    imports are banned.
  - `__init__.py`: facade re-export only (RULE 16 §16.0 compatibility-facade waiver, inline comment).
- **`app/services/run_state.py`** — `_track_batch_future` (the `co_name == "run_batch"` sniff)
  deleted; `_submit_tracked` slimmed to submit + done-callback; new `schedule_batch(bridge, coro)`
  tracks `bridge._batch_future` DELIBERATELY (locked, owned by run_state).
- **`app/ui/bridge_context.py::init_run_state`** — gains `_live_bus = LiveBus()` and
  `_state_lock = threading.RLock()` (the lock the funnel recalcs under).
- **Panels funnelled** (every queue-mutation tail through `commit_queue`, one reason each):
  `run_control`: `reset_image_state(img)` 1-param (the deselecting 2-param variant is GONE — D-6R),
  `retry_failed`, `retry_image`, `reset_all` (logs `↻ Reset all: {count} images re-queued`),
  `reset_image`; `start_run` runs `recover_stale_processing` before `schedule_batch`.
  `queue_scan`: registers `feed.set_undo_hook(push_queue_undo)` at import; `clear_queue_images`
  KEEPs its pre-mutation `push_queue_undo` (undo restore semantics require the pre-state
  snapshot) then funnels with `undo=False`; `run_scan_merge` / `run_scan_new_batch` /
  `set_image_selected` / `bulk_select` funnels (scan workers pass `undo=False` from worker
  threads — the bus wake is thread-safe). `app_settings`: `import_preset` / `load_arena_preset`
  funnel with `undo=False`.

## Adaptations vs the plan (documented deltas)

1. **Save+emit collapse** — the plan's 5-step funnel `(recalc → save → undo → emit → wake)`
  collapses save and emit: `_save_arena` emits `arena_state_updated` + `progress_updated` itself
  (I-39). Effective ordering pin in the funnel test: `["recalc", "save", ("undo","queue"), wake]`.
2. **Undo-hook injection** — services must not import panels, so `feed._UNDO_HOOK` module
  global + `set_undo_hook(push_queue_undo)` registration in `queue_scan` (module import).
  A test pins `_UNDO_HOOK is queue_scan.push_queue_undo`.
3. **Stale-recovery matching by basename** — pool pages carry `current_image` as a basename
  (dispatchers pass `os.path.basename(img.relative_path)`), so recovery matches basenames
  instead of a heavier `tab_has_live_job` path.
4. **Start gate vocabulary** — `start_run` answers `{"ok": False, "error": "no background loop"}`
  when `schedule_batch` returns None (bug, RULE 4 loud); the I-45 batch gate is untouched.
5. **Funnel + clear undo order** — clear pushes undo BEFORE mutation (restore-curve requires
  the pre-clear snapshot; verified against `UndoService.undo()` restoring the entry below the
  current index), so it funnels with `undo=False` instead of re-pushing an empty queue.
6. **Facade waiver** — `app/services/live/__init__.py` only re-exports (RULE 16 §16.0 row for
  compatibility facades, inline `# S4 facade:` comment).

## Tests (RED → GREEN)

- New: `tests/test_live_bus.py` (7), `tests/test_live_feed.py` (7),
  `tests/test_reset_requeues.py` (6) — RED confirmed at collection (`No module named
  app.services.live`), GREEN on the implementation.
- Coverage-ratchet repair (this stage also restored floors the S0 baseline recorded but the
  committed suite had slipped under): `tests/test_cdp_arena_output_helpers.py` (12) covers
  `_run_resume_gate` / `_scan_safely` / `_settle_timed` (clock charge incl.) /
  `_poll_diag_or_revive` / `_poll_output_diag`; `tests/test_app_settings_helpers.py` (6)
  covers the module-level appliers. `app/browser/cdp_arena/output.py` 89.22 % → **97.01 %**
  (floor 91.6), `app/ui/panels/app_settings.py` 72.33 % → **81.33 %** (floor 72.4).
- Adapted (named deltas of existing tests): `tests/test_run_state.py` — the old
  co_name-tracking test rewritten as `test_schedule_coro_runs_without_tracking_and_schedule_batch_tracks`;
  `tests/test_run_control_gate.py` + `tests/test_panel_slots.py` — monkeypatch target renamed
  `rc.schedule_coro` → `rc.schedule_batch`; `tests/test_file_dialogs.py` — the import-preset
  fake grows `state.images=[]` (the funnel reads the queue).

## Gate numbers

- `bash tools/stage_gate.sh`: **all 5 lanes green** — quality ratchet 0 fails; frozen seams
  **88 passed** (134 slots exact, window table, cooldown 4-arg wait untouched); suite
  `pytest`: **1701 passed, 4 skipped** (S4 adds 38 tests net: 20 live/bus + 18 ratchet-repair);
  characterization goldens **14/14 identical**; JS lane skipped (no `.js` touched).
- `/usr/bin/python tools/verify_quality.py --allow-legacy --all`: **no fails** (both coverage
  floors above their baselines after the repair, no `--record-baseline` needed).
- Frozen seams untouched: Σ slots = 134; `_map_wait_result` 4 params; `_security_gate` 2 params;
  `wait_captcha_cleared` 4-arg; `PagePool.add_page` CC at limit.

## Rules ledger

- RULE 16: funnel + helpers all ≤20 LOC, CC ≤ 4, ≤ 3 params; file sizes inside 150–300.
- RULE 18: no deviation flag needed on new modules; `app_settings.py` class LOC stays at the
  ratchet ceiling (funnel removed the duplicated tail instead of growing it).
- RULE 8: new tests keep real production seams (REAL PagePool + `cooldown_service.set_tab_image`
  in the stale-recovery test; real `LiveBus` wiring; 4-thread commit under `_state_lock`).
