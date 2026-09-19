# Problem priority — Round 2026-09-18

Ranked from the measurements in [`metrics-baseline-2026-09-18.md`](metrics-baseline-2026-09-18.md)
and the open items of the 2026-09-18 captcha reports
(`docs/archive/2026-09-18-captcha-bot-failure-analysis/verification-and-problem-diagnostic.md`
F-B…F-E, P9; `docs/archive/2026-09-18-captcha-solve-comparison-diagnostic/`).

## Severity model

Each problem is scored on five axes (1–5 each), weighted, then mapped to a band.
The weights are deliberately about *cost of leaving it*:

| Axis | Weight | Question |
|---|---:|---|
| Blast radius | 3 | how much of the codebase / how many behaviours does it touch? |
| Evidence strength | 2 | is the problem proven from the tree, or suspected? |
| Gate impact | 2 | how many RULE 16 fails / % of uncovered lines does it own? |
| Defect correlation | 2 | do the recorded bugs (RC-*, P-*) live here? |
| Cost of delay | 1 | does it block other work or get more expensive later? |

Band: **Critical ≥ 75 · High 55–74 · Medium 35–54 · Low < 35** (max 50 × 2 = normalise to 0–100).

---

## P1 — `_do_run_batch` mega-function + the duplicated job pipeline (Critical, 96)

**Where.** `app/ui/bridge.py:2530-3734` (`Bridge._do_run_batch`), lines 2,676–3,671
are an inline `for block in …` loop; the same lifecycle already exists in
`app/services/single_job_runner.py` (handler map + `run_blocks_for_image`),
used by `app/services/multi_page_dispatcher.py` on the pooled path.

**Evidence.**
* 1,205 LOC, radon CC **354**, cognitive **1,097**, nesting **23** — every one of
  them the highest in the repository, by 10–35×.
* 17 block types handled through an `if/elif` chain vs. 12 handled by the
  service handler map; convergence requires porting 8 handlers
  (`HIGHLIGHT_ATTACH`, `HIGHLIGHT_PROMPT`, `HIGHLIGHT_SUBMIT`, `HIGHLIGHT`,
  `PAUSE`, `TYPE_PROMPT`, `VERIFY_ATTACHMENT`, `VERIFY_PROMPT`).
* 0% coverage on the function (831 statements) — it holds the largest single
  block of uncovered code in the repo.
* Every block-level behaviour change (captcha rounds 5–11, revival, resubmit,
  send-ready) had to be applied twice: once here, once in `single_job_runner`.
  That duplication is the mechanism behind "fixes that work in one path and not
  the other" — exactly the class of bug the last five report rounds chased.

**Fix.** Area A, steps A1–A4. Highest-value single change in this round.

## P2 — `Bridge` god class (Critical, 92)

**Where.** `app/ui/bridge.py` — `class Bridge`, 4,991 LOC, 200 methods, 119 `@Slot`s.

**Evidence.** 53 of 120 gate fails (44%); MI **0.00**; LCOM4 **11**; fan-out 31
(the only seam between UI and the rest of the app); coverage 10.7%
(3,500 uncovered lines = 53% of the repo's total); `__init__` 122 LOC with CC 14.

**Fix.** Area A, steps A5–A6 (facade + mixins/services), with the slot-contract
test (`tests/test_bridge_slots.py`) as the regression guard: 200 slots must keep
their names and signal signatures.

## P3 — Dead legacy stack: 1,239 LOC that nothing calls (High, 74)

**Where.** `app/browser/controller.py` (643), `app/services/job_runner.py` (332),
`app/browser/output_detector.py` (155), `app/services/job_state_machine.py` (109).

**Evidence.** Import analysis over `app/` + `tests/` + `tools/` → no production
importer for any of the four; `job_runner` is imported by nothing at all,
`controller` only by `job_runner`; `output_detector` / `job_state_machine` are
imported by tests only. `controller.py` / `job_runner.py` sit at 0.0% coverage; `output_detector.py` (71%)
and `job_state_machine.py` (100%) are covered only by their own unit tests.
Together they carry 16 gate fails and 661 statements, 550 of them uncovered
(8.3% of the repo's uncovered lines). They are
also where the second-highest CC values live (`run_single_job` CC 24).

**Fix.** Area B, step B2 — with a one-round "declare and delete" policy: if the
pipeline needs a predicate from them (e.g. `output_detector.decide_ready`), port
that predicate into the live runner *in the same commit* that deletes the module.

## P4 — RULE 21 violated on the live path (High, 68)

**Where.** `app/browser/site_adapter.py` (316 LOC, tested) vs. inline selector
literals in `app/browser/cdp_arena.py`, `dom_highlight.py`, `output_probes.py`.

**Evidence.** `site_adapter` has exactly one importer — the dead
`controller.py`. RULE 21 and `docs/current/DOM_SELECTORS.md` declare it the
single source of truth with primary + fallbacks; the live path bypasses it.
The practical cost: selector fixes (the most frequent change in this project,
per `DOM_SELECTORS.md`) are edited in JS payload strings that no test reads.

**Fix.** Area B, step B3 — generate probe selectors from `site_adapter` and add
a test that fails when a probe string hardcodes a selector that drifted.

## P5 — Silent captcha-evidence loss in the recorder (High, 66)

**Where.** `app/services/captcha_recording/network.py` (`on_event` / `drain`),
`recorder.py::_run` (report P9, OPEN).

**Evidence.** `on_event` runs on the websocket receive thread while `drain()`
runs on the bridge loop; `drain` uses `while not empty(): get_nowait()` — a put
between the check and the get raises `QueueEmpty`, which kills the recorder
worker task and loses the session's evidence with no error surfaced. This is
the failure mode that makes report rounds 5–11 unprovable: the recordings that
would attribute a bot failure to RC-1…RC-4 can silently vanish.

**Fix.** Area D, step D1 (lock-protected deque or `call_soon_threadsafe` +
dropped-event counter + worker-thread regression test).

## P6 — Coverage 43%/32% vs 80%/75%, and a gate that lets regressions through (High, 63)

**Where.** the test suite as a whole; `tools/verify_quality.py --allow-legacy`.

**Evidence.** Line 43.4%, branch 32.0%, test∶code 1∶0.38, mutation unmeasured.
Worse than the number: `--allow-legacy` downgrades **every** breach in a
baseline file to a warning, so a new 40-line function added to `bridge.py` or
`cdp_client.py` passes the pre-push hook silently. `coverage.json` is not
produced by the hook, and `vulture`/duplication are never run in CI.

**Fix.** Area D, steps D4–D6 + Round 0 R0.3–R0.4 (baseline ratchet, JS gate,
coverage + vulture + duplication lanes).

## P7 — Complexity hotspots outside bridge (Medium-High, 52)

**Where.** 51 fails across 18 files. Worst symbols: `watcher.check_once`
(124 LOC / CC 35 / cog 82 / class 269 LOC), `cdp_client._connect_inner`
(CC 27 / cog 41), `cdp_client.fetch_tabs_sync` (36 LOC / nesting 5),
`cdp_arena.highlight_selector` (CC 13), `verification.validate_downloaded_file`
(42 LOC / CC 14 / nesting 5), `persistence.reconcile_with_filesystem`
(101 LOC / CC 21 / cog 34), `scanner.scan_folder` (CC 13 / cog 21),
`layout_service.normalize_grid_tree` (cog 21), `undo_service` (38 LOC + CC 12),
`preset_store` (22 methods), `main_window.__init__` (31 LOC).

**Fix.** Area C, steps C1–C6, in descending CC — RULE 19 order inside each step.

## P8 — Un-gated JavaScript mass (Medium, 47)

**Where.** `app/ui/web/js/**` — 34 files, 7,427 lines, 995 functions.

**Evidence.** RULE 16 sees none of it: 48 functions > 30 LOC, 24 functions
nesting > 4 (max 11), the largest file is 838 lines and the largest real
function 169 LOC (CC ≈ 90). Worst: `panels/action-blocks.js`,
`panels/cdp.js`, `panels/arena-presets.js`, `panels/image-queue.js`,
`arena-app.js::setupBridgeListeners` (164 LOC), `arena-history.js` (depth 11).
The Old App's audit called exactly this "the frontend is the largest un-gated
mass" — the new app repeats the pattern.

**Fix.** Round 0 R0.2 (JS gate) + Area C step C7 (split panels, extract pure
logic under `node --test`), C8 (the `cdp.js` ↔ `url-list.js` clone).

## P9 — Duplication and dead symbols (Low-Medium, 33)

**Where.** 55 clone groups (1.51%); Bridge's undo cluster (3,167–3,544,
10 internal pairs); persistence loader triple (27 lines × 2 pairs);
`output_probes` internal pairs; `cdp.js`/`url-list.js` 17-line pair;
2 unused imports + 30 vulture @60% candidates.

**Fix.** Area B steps B4–B5, Area C step C8.

---

## What each area is expected to move

| Area | Fails resolved | LOC delta | Coverage delta (line) | MI delta | Notes |
|---|---:|---:|---:|---|---|
| B dead code | −16 | −1,239 | 43.4% → 45.0% (−661 stmts, 550 uncovered) | unchanged (floor is `bridge.py` 0.00, fixed by A) | reversible by one revert; no behaviour change |
| A run pipeline + bridge | −53 (bridge) | bridge 5,118 → ≤300 + ~2,500 in services/panels | +12 pts | bridge 0.00 → ≥60 | the round's centre of gravity |
| C hotspots | −51 → ≤5 | ±0 (moves only) | +8 pts | mean 57.5 → ≥62 | parallel with D |
| D verification | 0 (enables all) | tests +~4,000 | 43% → 80% line, 32% → 75% branch | — | gate has no hole at the end |

## Explicitly *not* in this round

* Rewriting the captcha solver/detection path (rounds 5–11 territory) — only the
  evidence pipeline (`captcha_recording/**`) is in scope, for P5 and F-B/F-C.
* Migrating off PySide6/QWebChannel, or replacing the INI/JSON config stores.
* Performance work: no measurement shows it as a problem (444 tests in 10 s).
* Churn-driven risk analysis: impossible until per-PR history exists (R0.1
  starts recording it).
