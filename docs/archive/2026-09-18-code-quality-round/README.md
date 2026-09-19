# Code-quality Round — 2026-09-18 (planning round, no production code changed)

Snapshot: `67fae78` ("Recording: on/off toggle + per-day session folders"), branch
`arena/01a0b6ac-process-images-in-areana`. Every number in this folder was
re-measured from this tree with the commands in
[`appendix-reproduction-commands.md`](appendix-reproduction-commands.md).

**Status: plan only.** No production file was modified to produce this round —
the deliverable is the measurement, the priority order, and the four area plans.

* Current behaviour/invariants: [`../../current/SYSTEM_OF_RECORD.md`](../../current/SYSTEM_OF_RECORD.md)
* Gates the plan must satisfy: [`../../current/AGENT_RULES.md`](../../current/AGENT_RULES.md) RULE 16 + RULE 18, RULE 19 remediation order
* Verification workflow: [`../../current/CODE_VERIFICATION.md`](../../current/CODE_VERIFICATION.md)

## Files in this folder

| File | Holds |
|---|---|
| `README.md` | This index: executive summary, scoreboard, priority table, area map, round order, shared gates |
| [`metrics-baseline-2026-09-18.md`](metrics-baseline-2026-09-18.md) | The full audit, organised by the six metric families (complexity, size, coupling/cohesion, tests, smells, maintainability) + the JavaScript lane + metric gaps |
| [`problem-priority.md`](problem-priority.md) | P1…P9 ranked, with the severity model, per-problem evidence and the area that fixes it |
| [`plan-area-a-run-pipeline.md`](plan-area-a-run-pipeline.md) | Area A — run pipeline unification + Bridge decomposition (biggest problem) |
| [`plan-area-b-dead-code-purge.md`](plan-area-b-dead-code-purge.md) | Area B — dead legacy stack, duplication, selector centralisation |
| [`plan-area-c-complexity-hotspots.md`](plan-area-c-complexity-hotspots.md) | Area C — complexity hotspots outside bridge (Python + JS) |
| [`plan-area-d-verification-and-evidence.md`](plan-area-d-verification-and-evidence.md) | Area D — coverage/mutation/gate hardening + captcha evidence correctness |
| [`appendix-reproduction-commands.md`](appendix-reproduction-commands.md) | Copy-paste commands and the ad-hoc analysis scripts used for every number here |

## Executive summary

**The single biggest problem is not spread over the codebase — it is one function
and the class that owns it.**

* `Bridge._do_run_batch` in `app/ui/bridge.py` is **1,205 lines, radon CC 354,
  cognitive complexity 1,097, nesting depth 23**. It is 40× the RULE 16 fail line
  for function length and holds a 995-line inline `for block in …` loop that
  re-implements the **same 17-branch action-block pipeline** that already exists,
  dispatched by a handler map, in `app/services/single_job_runner.py`.
* It lives in `Bridge`: **4,991 LOC, 200 methods, LCOM4 = 11**, maintainability
  index **0.00 (C)** — the only file in the repo with MI 0. Bridge alone carries
  **53 of the 120 RULE 16 fails (44%)** and **3,500 of the 6,599 uncovered lines (53%)**.
* Everything else is smaller and cheaper: **1,239 LOC of the production tree is
  dead legacy code** (no production importer, 16 fails, removable without
  behaviour change — `controller.py` and `job_runner.py` at 0.0% coverage), and
  the remaining **51 fails** are ordinary hotspot-sized problems (max CC 35,
  max 124 LOC) spread over 18 files.

Test/quality baseline: **444 pytest tests green in 10 s**, 99 Node tests
(98 green + 1 that only fails because `node_modules` is absent),
**line coverage 43.4%, branch 32.0%**, duplication 1.51%, mean MI 57.5 with a
floor of 0.00. The Old App that this project was adapted from last measured
92.6% line / 88.0% branch / 99.4% mutation / MI 68.05 — the gap is the distance
this round has to close.

## Scoreboard against your thresholds

| Family | Metric | Threshold | Measured now | Verdict |
|---|---:|---|---|
| Complexity | Cyclomatic (max) | ≤ 10 | **354** (`_do_run_batch`) | ❌ 35× |
| Complexity | Functions over CC 10 | 0 | **43** | ❌ |
| Complexity | Cognitive (max) | ≤ 15 | **1,097** | ❌ 73× |
| Complexity | Functions over cognitive 15 | 0 | **33** | ❌ |
| Complexity | Nesting (max) | ≤ 3–4 | **23** | ❌ |
| Complexity | Functions nesting > 4 | 0 | **8** | ❌ |
| Size | Function LOC (max) | ≤ 20–30 | **1,205** | ❌ 40× |
| Size | Functions > 30 LOC | few | **52 (5.0%)** | ❌ |
| Size | Mean / median function LOC | — | 13.0 / 8 | ⚠️ mean above the 8–12 sweet spot |
| Size | Class LOC (max) | ≤ 200–300 | **4,991** (`Bridge`) | ❌ 17× |
| Size | Classes > 150 LOC | 0 | **6** | ❌ |
| Size | Methods per class (max) | ≤ 10–15 | **200** (`Bridge`) | ❌ 13× |
| Size | Functions > 4 params | few | **6** (max 7) | ⚠️ small tail |
| Size | File LOC (max) | ~150–300 | **5,118** (`app/ui/bridge.py`) | ❌ 17× |
| Size | Files > 300 lines | few | **15** (10 of them > 500) | ❌ |
| Coupling | Instability per package | balance toward 0 | ui 0.97, services 0.81, browser 0.22, core 0.08 | ⚠️ expected for a UI layer; watch `app.ui` |
| Cohesion | LCOM4 (main classes) | closer to 1 | Bridge **11**, CDPClient 3, CDPArena 3, others 1 | ❌ Bridge holds ~11 latent classes |
| Tests | Line coverage | ≥ 80% | **43.4%** | ❌ |
| Tests | Branch coverage | ≥ 75% | **32.0%** | ❌ |
| Tests | Mutation score | ≥ 70% | **not measured** (no runner in repo) | ⛔ gap |
| Tests | Test : code ratio | ~1 : 1 | **1 : 0.38** (Python), 1 : 0.33 (JS) | ❌ |
| Smells | Dead code | 0 | **1,239 LOC / 4 modules** confirmed + 30 vulture candidates | ❌ |
| Smells | Duplication | low | **1.51%** (55 clones / 597 lines) | ✅ low, but clustered in Bridge |
| Smells | God class | 0 | **Bridge** (LCOM4 11) | ❌ |
| Smells | Long method | 0 | `_do_run_batch` 1,205 LOC | ❌ |
| Smells | Feature envy / dead symbols | 0 | 2 unused imports, 30 vulture hits @60% | ⚠️ triage |
| Maintainability | MI mean / floor | higher = better | **57.53 / 0.00** (5 files < 20) | ❌ |
| Maintainability | Technical-debt ratio | lower = better | **≈1.95%** (model in §6 of the audit) | ⚠️ estimate |
| Maintainability | Churn | high churn = risky | **not measurable** (history squashed to 1 commit) | ⛔ gap |
| Maintainability | Bug density | lower = better | **0.79 / 1,000 LOC** (15 documented defects from the 2026-09-18 reports) | ⚠️ proxy |

## Priority order (detail in `problem-priority.md`)

| # | Problem | Evidence | Severity | Fixed by |
|---|---|---|---|---|
| P1 | `_do_run_batch` mega-function + duplicated job pipeline | 1,205 LOC / CC 354 / cog 1,097 / nest 23; second implementation of the `single_job_runner` handler map | Critical | A2–A4 |
| P2 | `Bridge` god class | 4,991 LOC / 200 methods / LCOM4 11 / MI 0.00 / 53 fails / 53% of uncovered lines | Critical | A5–A6 |
| P3 | Dead legacy stack | controller 643 + job_runner 332 + output_detector 155 + job_state_machine 109 LOC, 0% covered, 16 fails | High | B2 |
| P4 | RULE 21 violated on the live path | `site_adapter.py` (selectors, tested) is reachable only from the dead controller; live probes inline selector literals in JS payload strings | High | B3 |
| P5 | Silent captcha-evidence loss (report P9) | `network.py` crosses threads on an `asyncio.Queue`; `drain()` can raise `QueueEmpty` and kill the recorder worker | High | D1 |
| P6 | Coverage 43%/32% vs 80%/75% + gate hole | `--allow-legacy` downgrades *every* breach in a baseline file to a warning; no JS gate; vulture/coverage not wired; mutation unmeasured | High | D4–D6 |
| P7 | Complexity hotspots outside bridge | 51 fails across 18 files; worst `watcher.check_once` (124 LOC / CC 35 / cog 82), `cdp_client._connect_inner` (CC 27) | Medium-High | C1–C6 |
| P8 | Un-gated JavaScript mass | 34 files / 7,427 lines; 48 functions > 30 LOC; 24 nesting > 4; no gate sees JS at all | Medium | C7 + Round 0 |
| P9 | Duplication + dead symbols | 55 clone groups; Bridge undo cluster 3,189–3,544; persistence loader triple; 2 unused imports, 30 vulture hits | Low-Medium | B4–B5, C8 |

## Round 0 — shared foundation (one owner, before the areas branch)

Round 0 is *measurement and enforcement*, not refactoring. It lands on the
session branch and is the base every area branches from.

| Step | Deliverable | Done when |
|---|---|---|
| R0.1 | `tools/metrics_report.py` — one command producing every number in `metrics-baseline-2026-09-18.md` (radon CC/MI, cognitive, nesting, LOC, coverage, duplication, vulture, coupling, LCOM4, JS via acorn) | `python tools/metrics_report.py` reproduces the baseline tables within ±1% |
| R0.2 | JS gate in `tools/verify_quality.py` (acorn-based: function LOC, params, nesting, rough CC; same fail lines as Python) | a deliberately bloated JS file fails the gate; current JS is grandfathered via baseline |
| R0.3 | Baseline ratchet: per-metric `tools/quality_baseline.json` (max func/class LOC, methods, CC, cognitive, nesting, coverage per file) and the gate **fails on any increase**, even in legacy files | editing `bridge.py` to add a 31st-LOC-worse function fails the gate |
| R0.4 | Wire `vulture` (unused code) + duplication (jscpd) + `coverage.json` generation into `tools/pre_push_check.sh` | `bash tools/pre_push_check.sh` runs all lanes and is what the pre-push hook calls |
| R0.5 | Lanes: `pytest -m "not slow and not e2e"` fast lane, `node --test tests/js/*` lane, `npm ci` in the docs for the JS lane | all three lanes documented and green (JS lane green after `npm ci`) |
| R0.6 | Decide the mutation runner (`mutmut` vs `cosmic-ray`) and record one baseline score for `app/core/**` + `app/services/**` | a mutation number exists to compare against ≥70% |

## The four areas (isolated, independently developable)

Ownership is by path, so the areas can be built in parallel worktrees/branches
without touching the same file. Test files are owned by the area that creates
them (`tests/**` inside an area is a *new* file only — no edits to another
area's test file).

| Area | Owns (writes) | Reads only | Suggested branch | Order |
|---|---|---|---|---|
| **A** Run pipeline & Bridge | `app/ui/bridge.py`, `app/ui/panels/**` (new), `app/services/single_job_runner.py`, `app/services/multi_page_dispatcher.py`, `app/services/batch_orchestrator.py` (new), `app/services/run_state.py` (new) | `app/browser/**`, `app/core/**` | `arena/quality-a-run-pipeline` | 2nd (after B) |
| **B** Dead code & duplication | `app/browser/controller.py`, `app/services/job_runner.py`, `app/browser/output_detector.py`, `app/services/job_state_machine.py`, `app/browser/site_adapter.py`, `tests/unit/test_output_detector.py`, `tests/unit/test_job_state_machine.py`, `docs/current/DOM_SELECTORS.md` | everything else | `arena/quality-b-dead-code` | 1st (quick win, shrinks A's map) |
| **C** Complexity hotspots | `app/browser/cdp_client.py`, `cdp_arena.py`, `output_wait.py`, `output_state.py`, `output_probes.py`, `dom_highlight.py`, `visual_click.py`, `app/services/watcher.py`, `verification.py`, `cooldown_service.py`, `app/core/{scanner,persistence,undo_service,layout_service,naming,models,action_blocks}.py`, `app/persistence/preset_store.py`, `app/ui/main_window.py`, `app/ui/web/js/**` | `app/ui/bridge.py` | `arena/quality-c-hotspots` | 3rd (parallel with D) |
| **D** Verification & evidence | `tests/**`, `tools/**`, `app/services/captcha_recording/**`, `app/ui/services/captcha_recordings_bridge.py` | `app/ui/web/js/panels/captcha-recordings*.js` (owned by C) | `arena/quality-d-verification` | parallel with C; D1 (P5 bug) can start immediately |

Not owned by anybody in this round: `app/core/cooldown.py`, `app/core/folder_ai.py`,
`app/browser/{page_pool,page_status,tab_matcher,new_chat,selector,probe_requests}`,
`app/persistence/{config_manager,undo_store,cooldown_store}`, `app/utils/**`,
`app/services/captcha/**` (service/solver/recovery/stats), `config/**`, `docs/current/*`
except the one B edits. They stay as they are unless a step above explicitly lists them.

## Shared acceptance gates (every area, every step)

RULE 19 order is mandatory inside a step: **nesting → cyclomatic → cognitive → size
last**. Size-only splitting (moving a decision into a new file) is rejected per §16.2.

Per-step gate (run before each area commit):

```
python tools/verify_quality.py --changed            # 0 fails on changed files
QT_QPA_PLATFORM=offscreen python -m pytest tests -q # 444+ green
npm run test:js                                     # 99 green (after npm ci)
bash tools/pre_push_check.sh                        # all lanes
```

Per-area exit criteria (RULE 16 + RULE 18 recheck at the end of each area):

* [ ] 0 RULE 16 fails in the files the area owns; global fail count strictly lower than the area's start
* [ ] every function created or edited is ≤ 20 LOC, ≤ 3 params, CC ≤ 7, cognitive ≤ 10, nesting ≤ 3 (ideals, not fail lines)
* [ ] every file created or edited is 150–300 lines; deviations carry `# ideal-size: … reason=…`
* [ ] every class created or edited is ≤ 120 LOC and ≤ 10 methods
* [ ] no new vulture finding, no new duplication group
* [ ] coverage of the area's modules ≥ 80% line / ≥ 75% branch; global coverage never decreases
* [ ] each extracted unit has a test that fails if the unit is deleted
* [ ] no `quality-override:` added without a named constraint and a reason ≥ 20 chars
* [ ] `tools/quality_baseline.json` regenerated by the **integrator only** (single writer), after the area is green
* [ ] `docs/current/SYSTEM_OF_RECORD.md` + `docs/README.md` updated if behaviour, module layout or docs moved (RULE 17)

## Round sequence and expected deltas

```
Round 0 (measure + enforce)
   └─ B (dead code purge)        fails 120 → 104, LOC −1,239, stmts −661 (550 uncovered), line cov 43.4 → 45.0%
        └─ A (run pipeline)      fails 104 → 51,  bridge 5,118 → ≤300 lines, MI 0.00 → ≥60, coverage +12 pts
             ├─ C (hotspots)     fails 51 → ≤5 (documented overrides), JS >30-LOC functions 48 → ≤10
             └─ D (verification) coverage 43%/32% → 80%/75%, mutation ≥70%, gate has no hole
                     └─ final recheck: RULE 16 report v2 + RULE 18 audit in Old-App report format
```

Projected end-state for the numbers in the scoreboard: max function LOC ≤ 30,
max class LOC ≤ 150, 0 fails, MI floor ≥ 40 and mean ≥ 65, coverage ≥ 80/75,
duplication ≤ 1%, dead code 0, JS gated like Python.
