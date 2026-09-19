# Worst-First Remediation Roadmap — research & design (2026-09-19)

**Supersedes the execution order of**
`archive/2026-09-19-code-quality-implementation-plan/area-plans-prioritized.md`
(the area contents remain valid input; the sequencing and approach are
replaced). Reason: the Area-B-first execution produced **−21 gate fails
in 24 commits (0.9/commit) and +3.1 coverage points** while the single
worst offender — `bridge.py`, **50% of all fails** — was never touched.
This document re-plans the remaining work around efficiency: worst-first,
one head at a time, every step lands a measurable delta.

## 1. Diagnosis — why the previous approach was slow

| Cause | Evidence |
|---|---|
| Hygiene area executed first | B1–B20 = dead code, gate tooling, docs. Real, but only −21 fails; the top file was out of scope by design |
| Heavy harness front-loading | Old Area A required A1 (8–12 goldens) before any bridge fail could drop; the harness never got built, so **0 of 64 bridge fails moved** |
| Meta-work gravity | ~15 of 24 commits touched tools/docs; each round spawned a new review+plan round instead of production changes |
| Parallel-area plan | 4 areas × 33 steps with cross-dependencies; no single KPI driving order |

## 2. Research — fresh measurements (2026-09-19, HEAD `1487945`)

### 2.1 Where the 128 gate fails live

| Fails | File | Worst symbols (radon) |
|---|---|---|
| **64** | `app/ui/bridge.py` | `_do_run_batch` **CC 356 / 1,209 LOC**, `_apply_undo_entry` CC 42, `_remember_global_edit` CC 39, `_do_connect_tab` CC 25, `load_arena_preset` CC 24, `__init__` 122 LOC; class `Bridge` 5,000 LOC / 200 methods |
| **18** | `app/browser/cdp_client.py` | `_connect_inner` CC 27 / 106 LOC, `fetch_tabs_sync` nest 5 |
| **7** | `app/browser/output_wait.py` | `wait_for_new_output_loop` 5 params, CC 16 |
| **5** | `app/browser/cdp_arena.py` | class 359 LOC / 28 methods |
| 4 each | `layout_service`, `scanner`, `verification`, `watcher` | `check_once` CC 35 / 124 LOC (watcher), `scan_folder` 66 LOC, C4 verification set |
| 3 each | `action_blocks`, `persistence`, `undo_service` | `reconcile_with_filesystem` CC 21 / 101 LOC |
| 2 each | `dom_highlight`, `models`, `naming` | `build_watcher_overlay_js` 198 LOC, `recalculate_progress` CC 19 |
| 1 | `preset_store` | 22 methods (C6) |

### 2.2 Biggest coverage holes (uncovered lines)

`bridge.py` **3,504** (10.7%) · `cdp_client` 427 (9.2%) ·
`single_job_runner` 241 (34.1%) · `cdp_arena` 224 (30.9%) ·
`multi_page_dispatcher` 169 (41.5%) · `output_wait` 162 (11.7%) ·
`watcher` 148 (27.4%) · `main_window` 112 (0%) · `visual_click` 105
(21.5%). Bridge alone is ~34% of all uncovered code in the app.

### 2.3 Corrections to the old backlog

- **D1 "P0 live bug" (network.py silent event loss) is ALREADY FIXED** —
  lock-protected deque in `network.py`, with the exact regression test the
  plan asked for (`test_network_collector_no_loss_across_threads`:
  feeder thread hammering `on_event` while the loop drains). Remove from
  backlog; nothing to do.
- **D6 negative test is now enforced** (B19 per-symbol legacy ratchet) —
  the gate BLOCKS adding any >30-LOC function anywhere, including
  `bridge.py`. This changes the economics: bridge can only be fixed by
  real extraction, and every extraction step is police-checked.
- Bridge imports **headless** (Qt shims) — full bridge characterization
  is possible in this container; no UI runtime needed.

## 3. Design — the efficient approach

**Principles (each fixes a diagnosed cause):**

1. **Worst-first by damage score** — order = gate fails, then uncovered
   lines, then CC. No parallel areas; a single ranked queue.
2. **One shared harness, built once** — `tests/doubles/` (FakeCDPClient,
   FakePagePool, RecordingBridge, job fixtures) reused by every phase.
   Kills the A1 front-load: the harness grows *with* the first bridge
   step, not before it.
3. **Minimal goldens** — 3 scenarios (happy path, mid-fail abort, captcha
   pause/resume) + the existing 541 tests, slot-name freeze and payload
   byte-locks. Not 8–12.
4. **Every step lands a delta** — a step that does not move gate fails or
   module coverage does not get merged. KPI table below is the only
   progress report.
5. **Meta-work capped at zero** — no review rounds, no gate changes, one
   implementation record at the very end. (The gate now works; stop
   polishing the gate and use it.)
6. **B19 ratchet as the extraction police** — any new symbol >30 LOC
   fails the pre-push lane; refactors are structurally forced to comply.

## 4. Roadmap — steps worst-first

Effort: S ≤ half session · M ≤ one session · L ≤ two sessions.
Predicted deltas are honest estimates against the KPI table in §5.

### Phase W0 — verify & quick kills (S)

| # | Step | Action | Exit criteria | Pred. delta |
|---|---|---|---|---|
| W0.1 | Backlog correction | Mark D1 done (already fixed + tested, §2.3); record in old plan file | no code change | removes phantom P0 |
| W0.2 | `output_wait` (7 fails) | `WaitSpec` dataclass + `_poll_once` ≤20 LOC; behaviour locked by existing node output-probe tests + new unit tests | 0 fails in file, cov ≥60% | gate −7 |

### Phase W1 — bridge, the head of the snake (64 fails = 50% of gate)

| # | Step | Action | Exit criteria | Pred. delta |
|---|---|---|---|---|
| W1.1 | Shared doubles + 3 goldens | `tests/doubles/` + goldens for `_do_run_batch` (happy / mid-fail / captcha pause); bridge imports headless | goldens green on unmodified bridge | safety net for W1.3–W1.5 |
| W1.2 | `__init__` decomposition | `BridgeContext` dataclass + `_build_*()` / `_wire_*()` wirers ≤15 LOC each; `__init__` ≤20 | `__init__` cov ≥80%, slot freeze green | gate −2–3 |
| W1.3 | Undo cluster | `_apply_undo_entry` CC42 / `_remember_global_edit` CC39 → dispatch table per undo kind | both ≤20 LOC CC ≤7, undo tests green | gate −4–6 |
| W1.4 | Pipeline convergence (old A2) | port 8 missing handlers onto `single_job_runner` handler map (≤20 LOC each, JobCtx) | `single_job_runner` cov ≥80% | coverage +4–5 pts |
| W1.5 | Extract `batch_orchestrator` + delete the 1,209-LOC loop (old A3+A4) | flatten guards → named funcs (`should_continue`, `await_pause_or_abort`, `resolve_and_claim_tab`, …); flip `start_run`; delete inline loop | goldens byte-equal semantics, max func ≤30, `_do_run_batch` gone | gate −25–35 |
| W1.6 | Panel-mixin split (old A5) | `Bridge(CoreMixin, …)` + `panels/` by LCOM4 clusters; facade ≤300 LOC, ≤10 methods | bridge.py ≤300 LOC, Bridge ≤120/10 | gate −20–25 |

**Phase exit: bridge fails 64 → 0. Predicted gate after W1: ~55–60.**

### Phase W2 — cdp_client (18 fails, 9.2% coverage)

| # | Step | Action | Exit criteria | Pred. delta |
|---|---|---|---|---|
| W2.1 | Characterize | fake CDP doubles from W1.1 + local websocket stub server (`websockets` already in venv) | transport tests green | cov 9→40% |
| W2.2 | Package split | `cdp/transport.py` (socket+lock, I-22), `cdp/connect.py`, `cdp/tabs.py`, `cdp/probe.py`; facade ≤150 LOC | 0 fails in file, cov ≥60% | gate −18 |

### Phase W3 — long tail (39 fails, ≤4 per file)

One step per file, RULE 19 order (nesting→CC→cognitive→size), same
discipline: characterize → extract named responsibilities → ratchet
enforces sizes. Order by CC: `watcher.check_once` CC35 (overlay helpers
→ `watcher_overlay.py`) → `persistence.reconcile_with_filesystem` CC21 →
`scanner.scan_folder` → `verification` (C4 guards + `ValidationResult`)
→ `layout_service.normalize_grid_tree` → `models.recalculate_progress`
→ `undo_service` dispatch → `action_blocks` data/behaviour split →
`dom_highlight.build_watcher_overlay_js` 198 LOC move → `naming` param
object → `cdp_arena` composition split (C3) → `preset_store` read/write
split (C6) → `main_window.__init__`.
**Exit: gate ≤5 documented overrides.**

### Phase W4 — coverage ramp (old D4) with the same doubles

W1/W2 already lift bridge/single_job_runner/cdp_client. Remaining:
`multi_page_dispatcher`, `watcher`, `visual_click`, `cdp_arena`,
`core/**` fail-closed invariants → ratchet the baseline floor UP per
sub-phase to **80/75 global** (only upward, via the guarded flag).
**Exit: absolute coverage lanes warn-clean, gate = structural only.**

## 5. KPI table (the only progress report)

| KPI | Now (1487945) | W0 | W1 | W2 | W3 | W4 |
|---|---|---|---|---|---|---|
| Gate fails | 128 | 121 | **~55–60** | ~37–42 | **≤5** | ≤5 |
| Coverage line/branch | 44.31/35.10 | 44.5/35.4 | **~52/43** | ~56/47 | ~60/50 | **80/75** |
| Max function LOC | 1,209 | 1,209 | **≤30** | ≤30 | ≤30 | ≤30 |
| Bridge LOC / fails | 5,128 / 64 | — | **≤300 / 0** | — | — | — |

Each step's commit message records its row delta; `pre_push_check.sh`
(exit-0 lane) enforces no regression per step — including the B19
per-symbol ratchet that makes skipping the extraction impossible.

## 6. NOT-scope (unchanged owners)

JS panels gate (R0.2 acorn), mutation runner (R0.6/D5), metrics report
tool (R0.1), captcha milestones D2/D3 — separate tracks; the B19 ratchet
already covers their gate-integrity core.
