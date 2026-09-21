# S5 — Live supervisor: `run_live` loop, single run-state writer, idle waits (D-5)

*Chain stage 5 of the staged chain per `docs/archive/2026-09-20-dynamic-urls-and-worker-debug/`,
implemented 2026-09-21 on top of S4 (`1ca6428`). Contract: `tdd-interfaces.md` §S5 →
SoR **I-49**.*

## What landed

- **`app/services/live/supervisor.py`** (new, 153 lines) — the always-live run loop:
  - `WAIT_SEC = 60` heartbeat between wake-ups; `is_live(bridge)` is the single loop
    predicate (`_cancel_requested` or `_stop_after` end it; `_run_state` must already be
    `"running"` — the loop never writes it, so a leftover terminal value would ride forever).
  - `plan_pass(bridge)` — a pure snapshot decision: `PassPlan(reason="")` means *a pass may
    run*; otherwise the named wait reason (`"no_images" | "no_urls" | "cdp_down" |
    "no_tab" | "all_cooling"`) drives the wait. Cooling reads the REAL `PagePool`
    (`is_cooling`/`try_expire`).
  - `wait_reason(bridge, plan, bus)` — throttled log line per reason
    (`live_bus(bridge).throttle("live:" + reason, 60_000)` — one idle line per window, not
    per wake), then `bus.wait(WAIT_SEC)`.
  - `run_pass(bridge, plan) -> bool` — one batch body: `prepare_batch` (prepare itself
    decides claim-vs-decline vs the plan) → parallel try → batch gate (D-24 kept) →
    sequential → `pass_complete`. `False` when the claim declined.
  - `declined_plan(plan)` — a declined claim re-plans as a `no_tab` wait, never a hot
    re-pass loop (real defect found by the `no_tab` golden: without it the loop spins at
    100 % CPU when prepare declines every pass).
  - `run_live(bridge)` — flags the run live (`_live_supervisor = True`, set only here),
    `while is_live: plan → wait_reason | (run_pass or declined wait)`; the `finally`
    writes the ONE owner state, emitting like today's stop paths: cancel → `"idle"` +
    `⏹ Cancelled`, else **cancel always wins over stop-after** (`🔴 Run idle`), and the
    owned state + `batch_switched_line` go through the same two writes, and the owner
    state is declared `idle` + exported in `app/services/live/__init__.py`.
- **`app/services/batch_orchestrator.py`** — surgery to the pass-completion contract:
  `prepare_batch(bridge, plan)` takes the PassPlan (images/urls/tab from the plan; claim
  failure logs once and returns `None` — **no state write**); `_claim_tab` re-reads the
  LIVE URL rows per image; `pass_complete(ctx)` = old `_finish_batch` minus the
  state write (`🏁 Batch complete` + `job_finished` emit); `_abort_no_tab` /
  `_finish_batch` / `_run_guarded` / `_cancel_batch` / `_crash_batch` / `run_batch`
  **deleted**; `_await_batch_gate` lost its idle-write false branch; the `_run_sequential`
  run-complete tail removed (owner writes end-state now).
- **`app/services/multi_page_dispatcher.py::_finalize_batch`** — the `idle` write dropped
  (the supervisor owns background-settling from S5).
- **`app/ui/bridge_context.py::init_run_state`** — seeds `_live_supervisor = False`
  (the one flip lives in `run_live`).
- **`app/ui/panels/run_control.py`** — `start_run` checks the live branch FIRST via the
  module-level `live_recheck_payload` (live + connected ⇒ `live_bus.wake("start")`, log
  `🟢 Run already live — queue re-checked ({queued} queued)`, `{"ok": True, "live": True}`,
  no state write); the cold path seeds flags and schedules `run_live(self)` — `run_batch`
  is gone; pause/resume/stop-after/cancel route through `set_run_state` like the other
  writers (cancel keeps emitting `"idle"` — supervisor tails own the cancelled vocabulary).
- **`app/ui/panels/queue_scan.py::run_folder_ai_request`** — the D-5 guard: refuses only
  while an image is `processing` (module predicate `_any_processing`) instead of keying off
  `_run_state` — a live run now sits `"running"` between passes, so the old guard would have
  closed folder-AI forever.
- **`tests/characterization/harness.py`** — `RUNNERS["supervisor"]: run_supervisor` wraps
  `run_live` for scenario processes (stop lever: `job_finished` countdown → `_stop_after`,
  plus the no-usable-tab wait line as a valid no-work endpoint).

## Tests (RED → GREEN)

- New `tests/test_live_supervisor.py` (12) — RED at base (module missing), then GREEN:
  plan-naming matrix over all four wait reasons against a REAL cooling `PagePool`,
  start gates (running/paused/stopping inside a window; stop_before_loop),
  `run_live` picks work mid-idle (start_run fakes), live-branch `start_run` writes nothing,
  cancel/crash tails write the owner state once, supervisor keeps the D-5 folder-AI guard
  and `start_run`-as-process ends when the supervisor is cancelled. No fake clocks — real
  asyncio with `sup.WAIT_SEC` monkeypatched to 0.02 s.
- Adapted existing (named): `tests/test_batch_orchestrator.py` — `_finish_batch` →
  `pass_complete` contract (state unchanged through completion), `prepare_batch` takes the
  plan (`sup.plan_pass(bridge)` in tests), the `_run_guarded` shell test rewritten as
  `test_run_pass_chain` (the supervisor sequence `prep/par/gate/seq/tail`), cancelled/crash
  tails now owned by `run_live` (`test_run_live_handles_cancel_and_crash`), `run_batch` shell
  test removed; `tests/test_multi_page_dispatcher_run.py` — the two `idle` assertions
  replaced by S5 comments (owner writes end-state).

## Adaptations vs the plan (documented deltas)

1. **No separate `pass_tail` API** — folded into `pass_complete`; a second tail emit would
   double `arena_state_updated` per batch and drift the golden signal counts, which are
   trace-compared unchanged. `finally` emits nothing either: emits live exactly where the
   removed flows emitted them.
2. **Real time, no fake clock** — the plan's fake-clock fixtures became real asyncio with
   `sup.WAIT_SEC` monkeypatched (0.02 s); sleeps stay production code (RULE 8).
3. **Stop-after mid-pass** — delegated to the characterization goldens through the
   supervisor runner (`RUNNERS["supervisor"]`); the unit contract covers stop-before-loop.
4. **Reason matrix** — `test_plan_pass_names_the_wait_reason` is parametrized over the
   four reasons with a real `PagePool` made cooling post-`add_page`
   (`add_page` promotes to STEADY; status + far-future `cooldown_until` set after).
5. **Cancel keeps the idle-emission value** — `cancel_current` still emits `"idle"` (slot
   output preserved); the supervisor tails supply the `⏹ Cancelled` vocabulary — plan said
   differently, today’s button contract won.
6. **Declined-claim wait** (discovered by the `no_tab` golden) — a claim decline used to
   end the batch; on the live loop it must become a `no_tab` wait or the loop spins hot.
7. **Quality-ratchet shapes** — `live_recheck_payload` is a module function (the class
   ratchet caps methods/class-LOC), `start_run` compresses its flag seeding and walrus
   guard to stay at ≤19 LOC (baseline unchanged), `queue_scan` grows `_any_processing`
   instead of inlining the guard comment.

## Gate numbers

- `bash tools/stage_gate.sh` — **all 5 lanes green**: quality ratchet **0 fails**;
  frozen seams **88 passed, 1 skipped** (134 slots exact, window table, cooldown 4-arg wait
  untouched); suite **1706 passed, 11 skipped** (S5 adds 12 supervisor tests);
  characterization goldens **14/14 byte-identical** driven through the supervisor runner;
  JS lane skipped (no `.js` touched).
- Sizes: `supervisor.py` 153 (ideal), `__init__.py` 28 (facade), `batch_orchestrator.py`
  436 (has `# ideal-size:` reason), `run_control.py` 284, `queue_scan.py` 315
  (`# ideal-size:` reason kept).

## Rules ledger

- RULE 16: gates green above (ratchet-verified refactors; no `--record-baseline`).
- RULE 18 / RULE 16-ledger: new module inside 150–300; test seam documentation kept in
  the stage record.
- RULE 8: tests use REAL pools/live objects — the cooling matrix uses a real `PagePool`,
  the `start_run` live branch tests the real slot with a real `LiveBus`; the zero-activity
  assertions carry positive controls (the batch DOES run in `test_run_live_runs_a_pass`).
- Frozen seams untouched: 134 slots; `PagePool.add_page` CC at limit stays; no wait-contract
  edits.
