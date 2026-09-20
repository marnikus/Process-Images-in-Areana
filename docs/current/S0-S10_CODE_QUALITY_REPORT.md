# S0–S10 Code Quality Review

**Review date:** 2026-09-20  
**Branch:** `arena/01a0bf98-process-images-in-areana`  
**Reviewed commit:** `5a601c6`  
**Rules source:** `docs/current/AGENT_RULES.md` (RULE 16, RULE 18, RULE 19; behavioural RULES 1–15 and compliance RULES 20–23)

## Executive result

The full quality gate is **PASS**. No hard RULE 16 threshold failure was reported for the production surface. The implementation was pushed to the session branch. The table below gives file-level measurements for every changed production Python file; `NEW` identifies files introduced by S0–S10. Existing files are included because they were part of the staged implementation and must be reviewed for regression.

## Gate evidence

| Measure | Result | Rule comparison |
|---|---:|---|
| Python tests | 1,758 passed, 11 skipped | PASS; no failures |
| JavaScript tests | 270 passed | PASS |
| Line coverage | 89.0% statements (88.2% report aggregate) | ≥80%, above baseline |
| Branch coverage | 84.9% | ≥75%, above baseline |
| Quality verifier | 0 failures, 0 warnings | RULE 16 PASS |
| Max function LOC | 50 across full app inventory; 29 in listed changed files | hard fail only >30; legacy inventory/quality baseline governs existing code |
| Max class LOC | 150 full inventory; 139 in listed changed files | hard fail only >150 |
| Max parameters | 4 | hard fail only >4 |
| Max cyclomatic complexity | 10 | hard fail only >10 |
| Max cognitive complexity | 15 | hard fail only >15 |
| Max nesting | 4 | hard fail only >4 |
| Vulture | 0 findings at confidence 90 | PASS |
| Duplication | 1.081% / 23 groups / 399 lines | below 1.240% baseline |
| `git diff --check` | clean | PASS |
| Characterization goldens | unchanged | frozen seam PASS |
| Bridge slots/signals | no new slots/signals | frozen contract PASS |

The full-app informational metrics report records **161 files, 23,440 lines, 1,710 functions**, mean function size 8.30 lines, median 7, 1311 functions in the 4–20 ideal band, 365 under 4, and one function over 30. The one full-inventory >30 function is pre-existing/legacy according to the quality baseline; no changed production function exceeded the hard gate in the verifier.

## RULE 16 / RULE 18 / RULE 19 comparison

| Rule | Required comparison | Finding |
|---|---|---|
| 16.1 function size | Prefer 4–20; fail >30 | All changed-file maxima are ≤29. Several are above the ideal band but below the hard limit. Reasons: Qt/WebChannel slots, orchestration seams, and frozen protocol callbacks. |
| 16.1 class size | Prefer ≤120; fail >150 | Largest changed class is 139 LOC (`page_pool.py`); below hard limit, above ideal because it owns the page-pool UI state and bridge-facing actions. |
| 16.1 params | Prefer ≤3; fail >4 | All listed files max at 4; no >4 violation. Four-parameter functions are protocol/callback seams or existing APIs. |
| 16.2 cyclomatic | fail >10 | Max changed-file CC is 9; PASS. |
| 16.2 cognitive | fail >15 | Gate max is 15; PASS. |
| 16.2 nesting | fail >4 | Gate max is 4; PASS. |
| 16.3 coverage | line ≥80, branch ≥75, no uncovered new functions | 89.0% / 84.9%; tests cover new pause, CAPTCHA, live queue, reconciliation, receiver, window catalog, and debug paths. PASS. |
| 16.4 smells | no new dead code/duplication; documented overrides only | Vulture clean at 90%; duplication below baseline. PASS. |
| 16.5 legacy | do not worsen existing offenders | `verify_quality.py --changed --allow-legacy --coverage-ratchet`: 0 failures, 0 warnings. PASS. |
| 18 functions | ideal 4–20 lines | Most new functions are within band; small predicates/accessors are justified domain concepts, not metric-gaming. |
| 18 files | ideal 150–300 lines | Small leaf modules are intentionally under 150; large changed files are cohesive legacy/UI orchestration files and remain below hard limits. |
| 18 modules | ideal 5–15 cohesive files | `app/services/live/` has 7 cohesive files; `app/services/captcha/` remains a focused policy/service package. |
| 19 remediation | nesting → CC → cognitive → size | No threshold remediation was needed after the final gate; the implementation preserves named domain helpers and frozen seams rather than artificial splitting. |

## File-by-file production metrics

`LOC` is nonblank physical Python lines. Function LOC is inclusive AST span. CC is Radon maximum. These are static metrics; the authoritative threshold decision is `tools/verify_quality.py`.

| File | LOC | funcs | max func LOC | max params | classes | max class LOC | max CC |
|---|---:|---:|---:|---:|---:|---:|---:|
| app/browser/cdp_arena/output.py | 162 | 17 | 16 | 4 | 2 | 7 | 4 |
| app/browser/output_wait.py | 187 | 20 | 23 | 4 | 2 | 4 | 8 |
| app/core/layout_service.py | 211 | 22 | 20 | 2 | 1 | 4 | 9 |
| app/core/models.py | 250 | 11 | 28 | 3 | 6 | 74 | 4 |
| **NEW** app/core/pause_clock.py | 51 | 7 | 7 | 2 | 1 | 36 | 4 |
| app/core/run_scope.py | 51 | 6 | 7 | 2 | 0 | 0 | 4 |
| **NEW** app/core/window_catalog.py | 56 | 3 | 16 | 3 | 0 | 0 | 1 |
| app/persistence/config_manager.py | 103 | 17 | 13 | 2 | 3 | 44 | 4 |
| app/services/batch_orchestrator.py | 353 | 31 | 17 | 3 | 2 | 10 | 7 |
| **NEW** app/services/captcha/policy.py | 81 | 11 | 7 | 2 | 1 | 14 | 3 |
| app/services/captcha/service.py | 258 | 24 | 22 | 4 | 2 | 34 | 7 |
| app/services/captcha/signals.py | 104 | 5 | 16 | 1 | 2 | 44 | 8 |
| **NEW** app/services/live/__init__.py | 28 | 0 | 0 | 0 | 0 | 0 | 0 |
| **NEW** app/services/live/bus.py | 73 | 8 | 11 | 2 | 1 | 59 | 5 |
| **NEW** app/services/live/debug_view.py | 59 | 6 | 9 | 1 | 0 | 0 | 6 |
| **NEW** app/services/live/feed.py | 77 | 7 | 10 | 3 | 0 | 0 | 5 |
| **NEW** app/services/live/reconcile.py | 165 | 16 | 22 | 4 | 3 | 21 | 6 |
| **NEW** app/services/live/supervisor.py | 136 | 13 | 17 | 3 | 2 | 8 | 6 |
| **NEW** app/services/live/url_policy.py | 150 | 18 | 14 | 3 | 2 | 9 | 6 |
| app/services/multi_page_dispatcher.py | 328 | 27 | 29 | 4 | 6 | 9 | 8 |
| app/services/run_state.py | 340 | 34 | 18 | 3 | 2 | 7 | 7 |
| app/services/single_job_runner.py | 797 | 82 | 26 | 4 | 1 | 18 | 7 |
| app/ui/bridge.py | 122 | 10 | 15 | 4 | 1 | 95 | 3 |
| app/ui/bridge_context.py | 168 | 13 | 19 | 3 | 1 | 7 | 4 |
| app/ui/main_window.py | 138 | 11 | 26 | 1 | 1 | 123 | 6 |
| app/ui/panels/app_settings.py | 315 | 29 | 17 | 3 | 1 | 117 | 7 |
| app/ui/panels/browser_tabs.py | 400 | 35 | 20 | 3 | 1 | 76 | 7 |
| app/ui/panels/layout_state.py | 263 | 26 | 19 | 2 | 1 | 136 | 6 |
| app/ui/panels/page_pool.py | 209 | 14 | 16 | 4 | 1 | 139 | 7 |
| app/ui/panels/queue_scan.py | 260 | 24 | 19 | 3 | 1 | 82 | 7 |
| app/ui/panels/run_control.py | 244 | 21 | 19 | 3 | 1 | 110 | 6 |
| app/ui/panels/url_queue.py | 190 | 22 | 14 | 3 | 1 | 115 | 6 |
| app/ui/services/arena_serialize.py | 79 | 5 | 23 | 1 | 0 | 0 | 5 |
| app/ui/services/undo_entries.py | 324 | 35 | 17 | 3 | 0 | 0 | 7 |

## Added non-Python files

### Added browser/UI code

- `app/ui/web/css/live-debug.css`
- `app/ui/web/js/panels/live-debug.js`
- `app/ui/web/js/panels/live-debug/actions.js`
- `app/ui/web/js/panels/live-debug/render.js`
- `app/ui/web/js/panels/live-debug/store.js`
- `app/ui/web/js/panels/url-list/interval.js`

The JavaScript lane reports **83 files / 1,800 functions**, no JS function over 30 lines, no JS nesting over 4, and one JS CC value over 10 in the full inventory; the JS test lane passed all 270 tests. The new UI tests execute panel behaviour through the JS harness rather than string-only assertions.

### Added tests, tooling, and archive evidence

- 20 new Python tests covering S2–S10 contracts.
- 3 new JavaScript test files covering live debug, URL interval, and receiver icon behaviour.
- `tools/stage_gate.sh` for repeatable staged gates.
- `docs/archive/2026-09-21-staged-chain-implementation/S0-baseline.md` for staged evidence.

Tests/tools/docs are outside production size thresholds under RULE 16.0, but they are included in the gate and required to prove the new production behaviour.

## Rule-by-rule behavioural/compliance review

- **RULES 1–15:** Existing shared visual runner, logging, instance-owned block settings, empty/broken states, incremental progress, filtering, stop predicates, real CDP/DOM tests, non-stalling guards, single decision controls, scan-only semantics, global undo, validated persistence, queue/output separation, and two-step output verification remain covered by the existing suite and characterization goldens.
- **RULE 16:** PASS as detailed above.
- **RULE 17:** Current rules/system docs and dated staged archive were updated; no new top-level feature document was introduced.
- **RULE 18:** Ideal-size deviations are intentional and documented here: cohesive UI/Qt orchestration, protocol-compatible callbacks, and small leaf/policy modules. Hard thresholds, rather than ideal preferences, determine gate status.
- **RULE 19:** No metric-gaming helpers or artificial branch removal detected by the quality gate; domain helpers retain ownership boundaries.
- **RULE 20:** Watcher OFF produces zero CAPTCHA activity; ON mode detects/waits and uses bounded cumulative pause without pipeline solving. Covered by `test_watcher_off_zero_activity.py`, scope, cap, reason, and pause-clock tests.
- **RULE 21:** URL/receiver and live UI selectors preserve the semantic/structural priority convention.
- **RULE 22:** Existing correlation-token verification remains in the output path and characterization tests.
- **RULE 23:** Existing baseline, image validation, and atomic `_AI` output save path remain frozen and golden-tested.

## Outstanding observations

1. Pytest emits five existing coroutine/resource warnings in CDP/panel tests; they do not fail the gate, but should be cleaned in a separate maintenance change.
2. The informational full-app report contains legacy functions/files outside the changed hard-gate surface; the quality baseline prevents silent metric growth.
3. No mutation-testing lane was run in the final gate; it is explicitly optional/on-demand in `pre_push_check.sh`.

**Conclusion: S0–S10 satisfies the executable RULE 16 gate and preserves the required RULE 18/19 design constraints, with the observations above recorded for future maintenance.**
