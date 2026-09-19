# Code-quality Implementation Plan — 2026-09-19

**Status:** Planning only, no production code changed (RULE 17).
**Based on:** `docs/archive/2026-09-18-code-quality-round/` baseline `67fae78`, branch `arena/01a0b6ac-process-images-in-areana`.
**Current snapshot:** `cb74334` (reconstructed round), branch `arena/01a0b7f3-process-images-in-areana`.
**Gate now:** 121 fails (was 120), Bridge 5,127 LOC / 200 methods / CC 355 / nesting 23, line coverage ~43%.

## 1. IMPLEMENTATION PROCESS (from AGENT_RULES.md RULE 16 §16.6)

| Step | What | Output |
|---|---|---|
| **1. Understand fully** | Measure, prove, prioritize — no code yet | This folder: split into 10 sub-steps by severity |
| **2. Research & Design** | For each area, record current radon, target, dishonest reductions rejected, seams, invariants | Area docs in this folder |
| **3. Implement** | One area at a time, RULE 19 order nesting→CC→cognitive→size, tests first (RULE 8) | Commits, each passes `verify_quality --changed` |
| **4. Verify** | RULE 16 hard gates + RULE 18 ideals recheck | Checklist in `verification-checklist.md` |

This round enforces **RULE 16** (hard fails: func LOC 30, class 150, params 4, methods 15, CC 10, cognitive 15, nesting 4, coverage 80%/75%) and **RULE 18** (ideals: func 4–20 LOC ~8–12, file 150–300 ~200, module 5–15 files, context 60–200).

## 2. Why split first step?

"Understand the problem fully" is 80% of the work here. The codebase is not uniformly bad: 71.6% funcs are 4–20 LOC, mean CC 4.16 grade A, duplication 1.51%. The tail is **one function + one class + dead code**. If we implement before measuring, we fix twice (bridge vs `single_job_runner`) and miss the 3-detector dead-code proof.

So Step 1 is split into 10 prioritized sub-steps (see `step1-understand-prioritized.md`), ordered by **severity model** from `problem-priority.md`: Blast radius×3 + Evidence×2 + Gate impact×2 + Defect correlation×2 + Cost of delay×1.

## 3. All areas — ownership & order

| Order | Area | Owns (writes) | Problems | Fails | Expected delta |
|---|---|---|---|---|---|
| **Round 0** | Measure & enforce | `tools/metrics_report.py`, `verify_quality.py`, `quality_baseline.json`, `pre_push_check.sh` | Gate hole, JS un-gated, churn, mutation gap | 0 (enables) | One command reproduces all numbers ±1% |
| **1st** | **B** Dead code & duplication | `controller.py`, `job_runner.py`, `output_detector.py`, `job_state_machine.py`, `site_adapter.py`, `persistence/json_store.py` | P3, P4, P9-py | −16 | LOC −1,239, stmts −661 (550 uncovered), line 43.4→45.0% |
| **2nd** | **A** Run pipeline & Bridge | `bridge.py`, `panels/**`, `single_job_runner.py`, `multi_page_dispatcher.py`, `batch_orchestrator.py` (new), `run_state.py` (new) | P1, P2 | −53 | bridge 5,127→≤300 + ~2,500 services/panels, MI 0.00→≥60, +12 pts coverage |
| **3rd** | **C** Hotspots | `cdp_client.py`, `cdp_arena.py`, `output_wait.py`, `dom_highlight.py`, `watcher.py`, `verification.py`, `core/*`, `web/js/**` | P7, P8, P9-js | −51→≤5 | JS >30 LOC 48→≤10, nesting>4 24→0 |
| **parallel** | **D** Verification & evidence | `tests/**`, `tools/**`, `captcha_recording/**` | P5, P6 | 0→enables | 43%/32%→80%/75%, mutation ≥70%, P9 fixed |

Ownership is by path, so areas can be built in parallel worktrees after Round 0+B. No file touched by two areas.

## 4. Prioritization inside first step

From `problem-priority.md` scores:

| # | Problem | Score | Why first? |
|---|---|---|---|
| P1 | `_do_run_batch` 1,205 LOC / CC 354 / cog 1,097 / nest 23, duplicated pipeline | 96 Critical | 44% fails, 53% uncovered, every block fix twice |
| P2 | Bridge god class 4,991 LOC / 200 methods / LCOM4 11 / MI 0.00 | 92 Critical | Only seam UI↔rest, fan-out 31, 10.7% covered |
| P3 | Dead legacy 1,239 LOC, 0% coverage, 16 fails | 74 High | Quick win, shrinks A's map, reversible |
| P4 | RULE 21 broken: `site_adapter` unreachable, probes inline literals | 68 High | Most frequent prod change (selectors) edited in 3 JS strings |
| P5 | Silent evidence loss `network.py` QueueEmpty kills recorder | 66 High | Live bug, makes RC-1…RC-4 unprovable |
| P6 | Coverage 43%/32% + gate hole `--allow-legacy` downgrades all | 63 High | Gate lets new oversized code in baseline files pass |
| P7 | Hotspots 51 fails across 18 files, worst `watcher.check_once` 124 LOC / CC 35 | 52 Med-High | Ordinary tail, fixable locally |
| P8 | JS 34 files / 7,427 lines, 48 funcs >30 LOC, no gate | 47 Med | Frontend is largest un-gated mass |
| P9 | Duplication 55 groups + 2 unused imports + 30 vulture | 33 Low-Med | Clustered in Bridge undo + persistence loader |

Implementation order **differs** from understanding order: **B first** (cheap, −1,239 LOC, no behaviour change), then **A** (centre of gravity), then **C+D parallel**. D1 (P5 bug) can start immediately, even before Round 0.

## 5. RULE 16 & RULE 18 recheck at end

Every area exit must satisfy `verification-checklist.md`:

- `python tools/verify_quality.py --changed` → 0 fails in owned files, global fails strictly lower
- Every new/edited func ≤20 LOC (ideal) / ≤30 fail, ≤3 params (ideal) / ≤4 fail, CC ≤7 ideal / ≤10 fail, cognitive ≤10 ideal / ≤15 fail, nesting ≤3 ideal / ≤4 fail
- Every file 150–300 lines (ideal), deviations carry `# ideal-size: … reason=…` with named constraint ≥20 chars
- Every class ≤120 LOC ideal / ≤150 fail, ≤10 methods ideal / ≤15 fail
- No new vulture, no new duplication, coverage ≥80%/75% per module, global never decreases
- Each extracted unit has test that fails if deleted (RULE 8)
- No `quality-override:` without named constraint
- `quality_baseline.json` regenerated by integrator only
- `SYSTEM_OF_RECORD.md` + `README.md` updated if behaviour/module layout moved (RULE 17)

Projected end-state: max func LOC ≤30, max class ≤150, 0 fails, MI floor ≥40 mean ≥65, coverage ≥80/75, duplication ≤1%, dead 0, JS gated.

## 6. What is NOT in this round

- Rewriting captcha solver/detection (rounds 5–11 territory) — only evidence pipeline `captcha_recording/**` for P5/F-B/F-C
- Migrating off PySide6/QWebChannel or INI/JSON stores
- Performance (444 tests in 10s)
- Churn analysis (needs per-PR history from now on)

## 7. Files in this folder

| File | Holds |
|---|---|
| `design.md` | This file: process, area map, priority table, gates |
| `step1-understand-prioritized.md` | Step 1 split into 10 sub-steps, each with measure command, evidence, decision, owner |
| `area-plans-prioritized.md` | All areas A-D + Round 0, each split into ≤20 LOC steps, RULE 19 order, metrics Before→After |
| `verification-checklist.md` | RULE 16 + RULE 18 recheck template, per-step gate, per-area exit, final recheck |
| `implementation-2026-09-19.md` | Empty for now — will hold implementation record when implementation starts (NO implementation for now) |

Old App source for detailed rules: `Process Images in Areana/Old App/docs/current/` and `archive/`.
