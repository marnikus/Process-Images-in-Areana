# Area A — Review vs spec + improvement plan (2026-09-19)

Parent design: `docs/archive/2026-09-19-area-a-bridge-pipeline/design.md`
(§1 contracts, §2–§8 steps). Progress log:
`docs/archive/2026-09-19-area-a-bridge-pipeline/implementation-area-a.md`

Measured review state: **551 passed, gate TOTAL 97**, `bridge.py`
2710 lines / 35 fails, 119/119 slots present (76 in `bridge.py`, 43 in
4 panels), **0 fails on all Area A new files**. Counting method (all R1+
numbers): `verify_quality.py` output lines matching
`app/…:<line> [<tag>]` with tag in loc/cc/params/methods/nesting —
i.e. every FAIL the gate reports, none of the WARN/prose lines.
(Earlier drafts said 103/36: same fails, looser counting that swept in
prose lines; re-measured exactly on the R1 tree.)

Note: the gate uses `radon cc -s` when installed (else an AST approx that
under-counts comprehension-`for`). All R1+ numbers are radon-based
(stricter). This caught one latent CC 11 (`delete_action_block`, fixed in
R1 via `_remove_block`).

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
- **R2 — `url_queue` (9).** ✅ done. Moved CRUD/test/URL-presets + 5 URL
  module funcs + `_URL_GATE_MSG`; bridge keeps compat re-exports
  (contract §3 — incl. `_URL_GATE_MSG`, used by `start_run`'s gate, and
  `enabled_urls`, which `_get_enabled_urls` now delegates to);
  lazy auto_connect imports hoisted to panel top level (no cycle:
  services never import ui). Verified: 119/119 slots (67 bridge + 52 in
  5 panels), full suite 551 green, gate fails byte-identical before/after
  (97/35, 0 on `url_queue.py`), HEAD-vs-panel behavior diff clean
  (only deliberate change: `None` input → "empty URL" instead of
  `AttributeError`). Kills: none (all small), bridge −174 lines.
- **R3 — `queue_scan` (12).** ✅ done. 12 slots moved (thumbnail, reveal,
  copy, pick/set-folder, 2 scans, select/bulk, `clear_images` alias,
  AI twins); `clear_queue` target stays for R9 per log table
  ("retry/retry/reset/reset/clear"); new `file_service.py` (OS reveal +
  subprocess clipboard chain, log-callback, no Qt) and
  `folder_ai_service.py` (bridge-opaque worker); `merge_scanned` added to
  `scan_service` (new-batch reuses it post-clear, equivalent to the inline
  loop); `selected_images(images)` pure helper added and
  `_get_selected_images` flipped to it (R2 `enabled_urls` precedent);
  `_push_queue_undo` kept as a 2-line R9 shim (4 R9 callers left);
  orphaned `ImageItem` import dropped. Verified: 119/119 slots, mixin
  109 LOC, all new funcs ≤20 LOC / CC ≤7, 551 green, gate 97→90
  (bridge 35→28, exactly the planned 7: thumbnail×2, reveal, copy×2,
  scan×2), Bridge methods 125→106. Deliberate changes: none (only
  merge-loop equivalence + in-place drop refactor, both behavior-equal).
  Also repaired 3 R2 plan-doc edits lost to a parallel-edit race (re-baseline
  header, R10 kills, end-state 62) — same-file edits now done serially.
- **R4 — `app_settings` (10).** ✅ done. 10 slots moved (theme, prompt,
  settings, export/import, 4 arena presets, refresh shim); dispatch-split
  `save_settings` (scalar-key specs + generation/watcher appliers in exact
  original section order), `import_preset` (shared `apply_preset_settings`
  + `restore_import_sections`), `save_arena_preset` (`build_*_snapshot` +
  `build_arena_preset_doc`), `load_arena_preset` (per-section
  `restore_preset_*`; JS-vs-state wire formats kept distinct).
  `action_blocks`/`clamp_seconds` imports stay lazy (load-bearing fault
  tolerance: failure degrades, must not break panel import). Orphaned
  `UrlRow`/`save_preset`/`load_preset`/`QFileDialog` imports dropped.
  Verified: 119/119 slots, mixin 123 LOC, all funcs ≤20/CC ≤7, 551
  green, gate 90→83 (bridge 28→21, exactly the planned 7), Bridge
  methods 106→95. Deliberate changes: none.
- **R5 — `watcher_captcha` (10).** ✅ done. 10 slots moved (7 watcher +
  3 captcha); `set_watcher_config` split (validate/clamp + persist +
  shared `create_watcher_service`); `_get_watcher_cdp_controller` /
  `_on_watcher_state` → module funcs + `__init__` lambda edits;
  watcher/captcha/CDP imports stay lazy (load-bearing fault tolerance);
  `clear_watcher_overlay` if/else twins folded (identical schedule order);
  `Bridge._captcha_service` kept as a 2-line delegation — main_window +
  app/services/captcha call that seam (permanent, not an R9 shim).
  Verified: 119/119 slots, mixin 127 LOC, all funcs ≤20/CC ≤7, 551
  green, gate 83→82 (bridge 21→20: the planned set_watcher_config
  loc), Bridge methods 95→83. Deliberate changes: none (dead
  `import asyncio` in clear-body dropped — it was unused).
- **R6 — `page_pool` (9).** ✅ done. 9 slots moved; `_reset_stuck_page`
  → module func; `_do_connect_page_pool` split (connect-client /
  finish-join phases, ≤4 params); `_persist_cooldowns` → Bridge
  delegation to run_state (contract §2, `_emit_pool_status` unchanged);
  deleted `_cooldowns_path` + 4 restore twins + `_pooled_ids` after
  flipping all callers to run_state (bridge/run_state restore proven
  equivalent line-by-line incl. log strings and miss/order semantics;
  a missed 3rd `_do_connect_page_pool` caller in `_join_new_tabs` was
  caught by the post-surgery sweep and flipped too). Cooldown imports
  hoisted (run_state already top-imports them: zero marginal boot
  risk); browser imports stay lazy (R5 precedent). Verified: 119/119
  slots, mixin 139 LOC, all funcs ≤20/CC ≤7, 551 green, gate 82→82
  (kills 0 by design), Bridge methods 83→66, bridge −276 lines.
  Deliberate changes: none.
- **R7 — `browser_tabs` (7).** ✅ done. 7 slots moved (get/diagnose/
  auto-scan/popup/ensure/connect/find); `_do_connect_tab` (84) → 9 phase
  funcs (`cached_tab_identity` added beyond plan: or-chain CC 9 → 5+6,
  genuine cached-vs-live split); `_do_find_tab` (35) → 4 funcs;
  `_report_auto_plan` → `plan_has_changes` predicate + 4-param report
  (presence tuple, honest); `claim_connect_slot`/`claim_find_slot`
  debounces (+`find_dupe_recent`, `claim_auto_rows`, `popup_row_title`
  predicate extracts — every new split ≤7 CC); 7 `_schedule_coro` sites
  → `run_state.schedule_coro`; `_resolve_tab_info` deleted after
  flipping both callers to run_state (page_pool flip + panel identity;
  `_pooled_ids` already died in R6); first acyclic panel→panel imports
  (url_queue/page_pool single-source); `__init__` exports all 10.
  Behavior script caught + fixed a real bug: restore-on-reuse (original
  restores only on dedicated/fallback — port now faithful). Verified:
  119/119 slots, mixin 76 LOC/7 methods, all funcs ≤20/CC ≤7, 87/87
  behavior checks + literal-multiset diff clean, 551 green, gate 82→75
  (bridge 20→13, exactly the planned 7), Bridge methods 66→43, bridge
  −418 lines. Deliberate changes: none (schedule flip names the real
  owner in the outer-fail log now).
- **R8 — `cdp_tools` (9).** ✅ done. 9 slots moved (highlight×2, clear,
  get/set-cfg, launch-cmd, 3 test flows); `HighlightArgs` parameter object
  kills the 5-param problem honestly (`_do_highlight` → evaluate +
  `report_highlight_result`); `set_cdp_config` → `first_present` /
  `parse_cdp_port` (ValueError → identical error JSON via outer except) /
  `parse_cdp_config` / `apply_cdp_config`; shared `read_cdp_config`
  (launch reuses it — dedup by design); `build_chrome_commands`,
  `test_image_match`+`find_test_image`, `run_flow_prompt` phases; 6
  `_schedule_coro` sites → run_state (only `start_run` left); dropped all
  3 dead browser import lines (11/13 names unused; panel lazy-imports 2).
  Fixed a stale harness patch: `fakes.py` patched `bridge.find_and_click`
  for the A4-deleted legacy loop — runner patch is the live one.
  Verified: 119/119 slots, mixin 104 LOC/9 methods, all funcs ≤20/CC ≤7,
  70/70 behavior checks + literal diff clean (shortfalls = deliberate
  dedups), 551 green, gate 75→71 (bridge 13→9, exactly the planned 4),
  Bridge methods 43→27, bridge −279 lines. Deliberate changes: none.
- **R9 — `run_control` (10).** Move run-lifecycle slots; split `start_run`
  (gate checks); F8 `JobAction` redesign (`_emit_job_action_status` →
  delegation); `enabled_urls(urls)` pure helper in url_queue, imported;
  flip last `_schedule_coro` sites; **delete** `_ensure_bg_loop`,
  `_schedule_coro` (run_state owns). Kills 6 (start_run + emit_job×3 +
  bg-loop loc + schedule loc; their CC passes under radon).
- **R10/R11 (renumbered — see §4).** Old R10 (A6) is now **R11**, old R11
  (A7) is now **R12**; new **R10** is the ideals sweep. §4 is authoritative.

Expected end state: TOTAL ≈ 97 − 35 = **62** (all `bridge.py` fails gone),
suite green, Bridge ≈ 300 lines / 10 methods, 12 panels + 8 ui-services.
Kill-map check: R3 7 + R4 7 + R5 1 + R7 7 + R8 4 + R9 7 + R11 2 (A6) = 35 ✓
(R2/R6/R10 kill 0 by design; R9 took the methods-count kill R11 planned).

## 3. Second review pass (post-R6, pre-R7)

Re-read of design §§0–9 against the R6 tree (`3713414`), per the standing
instruction (review full Area A vs spec → plan DOC first → implement).
Fresh state: **551 green, gate TOTAL 82** (bridge 20, 0 on Area A files),
`bridge.py` 1329 lines / 66 methods / 26 direct `@Slot`, 9/12 panels cut
(119 = 26 bridge + 93 panel), slots test scans panels
(`test_bridge_slots.py:52-61`), remaining 26 = 7 + 9 + 10 exactly as
planned (R7/R8/R9). Contract §1.2 ✅ (all four API methods on Bridge:
`_log:332`, `_emit_pool_status:231`, `_captcha_service:529`,
`_persist_cooldowns:259`); §1.3 ✅ (re-exports intact); §1.4 ✅ (zero
binding refs in `test_grid_layout.py`); direction ✅ (panels import only
services/core/browser/qt_compat/stdlib; no panel→panel; no NEW
services→Qt). New findings:

- **F9 — F4 was incomplete.** Fresh radon sweep (53 B-grade funcs, no C+)
  found 12 more ideals misses F4 never listed (first sweep only showed
  `head -20` — same trap). Verdicts: FIX the 8 with genuine splits,
  TABLE the 3 that would scatter, 1 already fixed (see R10 design).
- **F10 — F4 staleness.** `_move_to_tab` CC 8 → now B(6) (R1's `_pool_ws`
  extract resolved it); `save_preset_doc` 4 params → now 3 (R1 folded
  `stored_ws`). Both F4 rows closed, no action.
- **F11 — 4 mixins exceed the 120-class ideal with no in-code reason**
  (RULE 18.5): blocks_stack 135/10m, layout_state 148/14m, page_pool
  134/9m, watcher_captcha 127/10m (queue_scan/app_settings already carry
  reasons). R10 adds `ideal-size:` class-docstring reasons (all RULE
  16-legal; frozen slot surfaces, extraction already done — verified at
  implement time).
- **F12 — `panels/__init__.py` stale**: exports 4/9 mixins (R2–R6 never
  updated it). Harmless today (bridge imports submodules directly) but
  wrong. R10 exports all 9 (+3 as R7–R9 land).
- **F13 — §1.5 bypass**: `queue_scan._qt_clipboard_handle` /
  `try_qt_clipboard_copy` hold the ONLY Area A `PySide6` imports outside
  the shim (3 lazy sites; `bridge.py` itself is now at ZERO `PySide6`
  refs). R10 centralizes into `qt_compat.get_clipboard` /
  `clipboard_copy`, making "panels import Qt via one guarded shim" TRUE.
- **F14 — Qt-site truth table** (rest of `app/ui`, both NOT Area A, both
  correctly untouched): `main_window.py` top-level Qt (the real window
  owner — must construct widgets; the shim contract governs
  panels/services, not it); `captcha_recordings_bridge.py` guarded Qt
  (R0-grandfathered recordings UI).
- **F15 — vulture flags every `@Slot` method as unused** (JS-called,
  invisible to static analysis). A7 must run vulture with a slot
  whitelist, not bare (tooling note for R12).
- **F16 — A5 end-state trajectory.** Bridge 1329 lines / 66 methods after
  R6; R7–R9 remove 26 slots + ~15 helpers; A6 (R11) shrinks `__init__`
  + context. The §6 "≤10 methods per panel" target needs the same
  adjust-with-reason treatment packing got (layout_state 14,
  queue_scan 12 — both reasoned).

Radon-artifact note (F9 context): `_window_filter` CC 8 (6 lines) and
`_page_identity` CC 9 (10 lines, 1 if) are boolean-op/comprehension
counting artifacts on trivially simple code. The R10 fixes are genuine
dedups (shared predicates), NOT metric-gaming — and where no genuine
split exists (registry literal, flat mapping, linear legacy flow) the
honest verdict is TABLE with reason.

## 4. New steps R10–R12 (planned from second pass)

Old R10 (A6) → **R11**; old R11 (A7) → **R12** (bullets above kept for
history; this section is authoritative). Kill-map unchanged (R10 kills 0
by design — all targets already RULE 16-legal).

- **R10 — Ideals sweep.** 8 fixes + reasons + shim centralization:
  1. `run_state._page_identity` (CC 9) → extract `_cdp_attr(cdp, name)`
     (one `getattr-or-""` read); main → CC ~5. Suite covers via
     pool-ensure paths.
  2. `blocks_library.save_custom_block` (CC 8) → extract
     `_custom_block_list(raw)` normalizer, SHARED with
     `delete_custom_block` (kills duplicated normalize); save → 7.
  3. `layout_state._window_filter` (CC 8) → extract `_known_ids(items)`
     (kills duplicated predicate); main → ~4. Covered by
     `test_layout_state.py`.
  4. `layout_state.import_preset_file` (LOC 21) → extract
     `_preset_grid_error(doc)` validator; main → ~18. NEW direct unit
     test for the pure helper (dialog branches stay F7-covered at R12).
  5. `window_preset.parse_preset_input` (CC 8) → extract
     `_raw_tree_result(parsed, grid_json)` (raw-{v,tree} branch);
     main → ~5. Covered by `test_layout_state.py:56-69` ✅ existing.
  6. `single_job_runner.wait_for_output` (LOC 25, CC 9, legacy body) →
     extract `_poll_generation(ctx, timeout_ms)` core (poll + cancelled
     mark + src route); main (overlay/revival/cleanup scaffolding) →
     ~17/CC ~4. Golden coverage verified at implement; behavior-diff
     script if no golden covers it.
  7. `single_job_runner._run_one_checked` (LOC 23, A2 +2) → extract
     `_block_skip_reason(ctx, block)` (cancelled/disabled guards);
     main → 19. Covered by cancel/disabled goldens (verify at implement).
  8. `single_job_runner.check_security` (LOC 24, legacy body) → extract
     `_run_security_captcha(ctx)` tail (closures + handler invoke);
     main (visibility gate) → ~10. Covered by `captcha.json` (verify).
  9. TABLE with in-code/audit reasons (no split — would scatter):
     `_handler_map` (flat registry literal, A2 +3 entries),
     `_handle_wait` CC 9 (3 readable ternaries + single-level ifs, no
     nesting; legacy body preserved verbatim by A2 converge),
     `settings_to_js` LOC 21/CC 1 (flat 12-key view mapping).
  10. `ideal-size:` class-docstring reasons on the F11 four (DRAFT
      wording, verified against code at implement): frozen JS slot
      surface + module-level helpers already extracted; remaining LOC
      is per-slot validate/wire that cannot move without scattering.
  11. `panels/__init__.py` → export all 9 mixins (+3 as R7–R9 land).
  12. Clipboard → shim: `qt_compat.get_clipboard()` (handle chain,
      headless → None) + `qt_compat.clipboard_copy(text)` (exact
      `try_qt_clipboard_copy` behavior incl. lazy `QClipboard` import
      inside the try); panel deletes both funcs, call site imports from
      shim. qt_compat 35 → ~70 lines (still <150 ✅). Headless test:
      returns `(False, None)`.
  Each fix: implement → targeted tests/behavior-diff → gate (0 new) →
  suite. Single commit. Kills 0 by design.
  ✅ done. All 8 mains now ≤20 LOC / ≤7 CC (`_page_identity` 9→6,
  `save_custom_block` 8→7 with `delete` 6→5 via the shared normalizer,
  `_window_filter` 8→3, `import_preset_file` 21→19 LOC,
  `parse_preset_input` 8→5, `wait_for_output` 25→19 LOC/9→5,
  `_run_one_checked` 23→20 LOC, `check_security` 21→10 LOC; all 8
  helpers A-grade), plus `_cdp_attrs` delegated to `_cdp_attr` (same
  pattern, A1). Runner extracts proven by byte-compared goldens
  (cancel/disabled/captcha/wait paths green, no separate diff needed).
  Item 11 was verify-only (`__init__` already exports 12/12 since
  R7–R9). Item 12: shim 35→72 lines, moved bodies byte-identical,
  panels now PySide6-free. +4 tests (validator + 3 headless shim).
  Verified: 555 green, gate 64→64 byte-identical. Also fixed an R9
  doc race: the R11-bullet kills correction lost to a parallel edit.
- **R11 — A6 `BridgeContext`** (= old R10): `app/ui/bridge_context.py`
  dataclass + `build_context()` + `wire_cdp/wire_watcher/wire_page_pool/
  wire_thumb` (≤15 LOC); `Bridge.__init__` ≤20 (same attrs,
  `_batch_future=None`); `_log_build_version`/`_on_cdp_error` → module
  funcs. Kills 2 (`__init__`×2; the `[methods]` kill already fell in R9).
- **R12 — A7 sweep** (= old R11 + F15): (a) vulture with @Slot whitelist
  + unused-import sweep, Area A clean; (b) F5 frozen-119 test; (c) F6
  packing test; (d) branch coverage ≥80/75, no uncovered new funcs
  (dialog-fake tests; R10 helpers covered); (e) finish implementation
  log; SYSTEM_OF_RECORD.md §7 + docs/README.md (RULE 17); (f) RULE 18
  audit table (F9 TABLEs + F11 reasons + every deviation reasoned);
  full gate + suite.
