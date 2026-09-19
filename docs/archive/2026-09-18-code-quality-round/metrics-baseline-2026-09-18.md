# Code-quality metrics — Arena Image Processor, 2026-09-18

Snapshot `67fae78`, branch `arena/01a0b6ac-process-images-in-areana`.
No production code was changed to produce this audit; every number is
re-measured from this tree with [`appendix-reproduction-commands.md`](appendix-reproduction-commands.md).

**Scope.** Python production: 78 files / **18,929 LOC** / 16,299 SLOC /
**1,047 functions** / 77 classes under `app/`. JavaScript production:
34 files / **7,427 lines** / **995 functions** under `app/ui/web/`.
Tests: 40 Python test files (7,267 LOC) + 11 Node suites (2,534 LOC).
Out of scope: `Process Images in Areana/Old App/**` (reference material),
`docs/**`, `config/**`, `tools/**`.

**Benchmark for context.** The Old App this project was adapted from last
measured (2026-09-14 audit): 3,172 tests green, line coverage 92.64%, branch
88.03%, mutation 99.37%, test∶code 1∶1.57, max CC 10, 0 functions over CC 10,
mean MI 68.05, JS coverage 82.8%. Those are the targets this codebase has to
converge to; the columns below are where it is today.

---

## 1. Complexity metrics

| Metric | Your threshold | Measured | Verdict |
|---|---:|---|---|
| Cyclomatic complexity — max (radon) | ≤ 10 | **354** — `Bridge._do_run_batch` (`app/ui/bridge.py:2530`) | ❌ 35× |
| Cyclomatic complexity — mean (1,096 blocks) | — | 4.16 (grade A) | ✅ average is fine, tail is not |
| Functions with CC > 10 | 0 | **43** (4.1% of functions) | ❌ |
| Cognitive complexity — max | ≤ 15 | **1,097** — same function | ❌ 73× |
| Functions with cognitive > 15 | 0 | **33** | ❌ |
| Nesting depth — max | ≤ 3–4 | **23** — same function | ❌ |
| Functions with nesting > 4 | 0 | **8** | ❌ |

The distribution is the story: **the median function is 8 lines and CC 1–2, and
the average grade is A.** Complexity is not a systemic problem here — it is
concentrated in a handful of symbols, and the top one is 100× the next.

Top complexity offenders (radon CC / cognitive / LOC / nesting):

| CC | Cognitive | LOC | Nest | Symbol |
|---:|---:|---:|---:|
| 354 | 1,097 | 1,205 | 23 | `app/ui/bridge.py:2530` `Bridge._do_run_batch` |
| 35 | 82 | 124 | 3 | `app/services/watcher.py:169` `WatcherService.check_once` |
| 42 | 61 | 104 | 12 | `app/ui/bridge.py:3871` `Bridge._apply_undo_entry` |
| 39 | 52 | 84 | 12 | `app/ui/bridge.py:3786` `Bridge._remember_global_edit` |
| 27 | 41 | 106 | 3 | `app/browser/cdp_client.py:337` `CDPClient._connect_inner` |
| 25 | 45 | 84 | 5 | `app/ui/bridge.py:4511` `Bridge._do_connect_tab` |
| 24 | 28 | 207 | 3 | `app/services/job_runner.py:57` `JobRunner.run_single_job` *(dead — §5)* |
| 24 | 37 | 66 | 3 | `app/ui/bridge.py:4754` `Bridge.load_arena_preset` |
| 21 | 34 | 101 | 3 | `app/core/persistence.py:69` `reconcile_with_filesystem` |
| 21 | 21 | 66 | 3 | `app/core/scanner.py:9` `scan_folder` |

Full list of the 33 functions with cognitive > 15 is in the reproduction
appendix (§A.4) — 23 of them are in `app/ui/bridge.py`.

## 2. Size & volume metrics

| Metric | Your threshold | Measured | Verdict |
|---|---:|---|---|
| Function LOC — max | ≤ 20–30 | **1,205** (`_do_run_batch`) | ❌ 40× |
| Functions > 30 LOC | few | **52 (5.0%)** | ❌ |
| Functions in the 4–20 ideal band | most | **750 / 1,047 (71.6%)** | ✅ the body of the code is right-sized |
| Functions < 4 LOC | few | 182 (17.4%) — mostly one-line helpers/shim predicates | ⚠️ spot-check per RULE 18.1 |
| Mean / median function LOC | — | **13.00 / 8** | ⚠️ mean inflated by the tail |
| Class LOC — max | ≤ 200–300 | **4,991** (`Bridge`) | ❌ 17× |
| Classes > 150 LOC (gate line) | 0 | **6** | ❌ |
| Classes > 300 LOC | 0 | **5** | ❌ |
| Methods per class — max | ≤ 10–15 | **200** (`Bridge`) | ❌ 13× |
| Classes > 15 methods | 0 | **5** | ❌ |
| Classes > 10 methods | 0 | **11** | ❌ |
| Parameters — max | ≤ 3–4 | **7** (`build_highlight_rect_js`) | ❌ |
| Functions > 4 params | few | **6** | ⚠️ small tail |
| File LOC — max | 150–300 | **5,118** (`app/ui/bridge.py`) | ❌ 17× |
| Files > 300 lines | few | **15** (10 of them > 500) | ❌ |
| Files in the 150–300 ideal band | most | 15 / 78 (19%) | ❌ inverted |
| Module size (`app/` subpackages) | 5–15 files | core 12, browser 18, services 17 (+3 sub-modules), ui 4, persistence 4, utils 5 | ⚠️ `browser` and `services` are past the split line |

Ten files over 500 lines (with MI and coverage):

| Lines | MI | Coverage | File |
|---:|---:|---:|
| 5,118 | 0.00 (C) | 10.7% | `app/ui/bridge.py` |
| 838 | n/a (JS) | untracked | `app/ui/web/js/panels/action-blocks.js` |
| 723 | 3.12 (C) | 88.9% | `app/services/cooldown_service.py` |
| 716 | 36.87 | 40.3% | `app/core/action_blocks.py` |
| 678 | 41.43 | 35.1% | `app/browser/dom_highlight.py` |
| 647 | 9.39 (B) | 9.3% | `app/browser/cdp_client.py` |
| 643 | 28.27 | **0.0%** | `app/browser/controller.py` *(dead — §5)* |
| 585 | 21.95 | 29.4% | `app/browser/cdp_arena.py` |
| 557 | 15.35 (B) | 33.9% | `app/services/single_job_runner.py` |
| 549 | 19.50 | 89.1% | `app/services/captcha/solver.py` |
| 527 | n/a (JS) | untracked | `app/ui/web/js/sash-core.js` |

**JavaScript size lane** (no gate sees it today):

| Metric | Threshold (applied to Python) | JS measured | Verdict |
|---|---:|---|---|
| Files | 150–300 | **34 files / 7,427 lines**, 8 files > 300, 3 > 500 (max 838) | ❌ |
| Functions > 30 LOC | few | **48 (4.8%)** | ❌ |
| Functions in 4–20 band | most | 480 (48.2%) | ⚠️ |
| Params > 4 | few | 3 | ✅ |
| Max function LOC | ≤ 30 | 169 (`panels/action-blocks.js:525`) + a 164-line `setupBridgeListeners` in `arena-app.js` | ❌ |
| Mean / median function LOC | — | 9.64 / 5 | ✅ |

## 3. Coupling & cohesion metrics

Package-level afferent/efferent coupling (import edges, packages aggregated to
`app.<layer>`):

| Package | Ca (in) | Ce (out) | I = Ce/(Ca+Ce) | Reading |
|---|---:|---:|---:|
| `app.core` | 24 | 2 | **0.08** | stable core, correct direction |
| `app.utils` | 10 | 0 | 0.00 | leaf utilities |
| `app.persistence` | 4 | 0 | 0.00 | leaf store, good |
| `app.browser` | 18 | 5 | 0.22 | stable, but see dead `controller.py` |
| `app.services` | 5 | 22 | **0.81** | orchestration layer, expected |
| `app.ui` | 1 | 31 | **0.97** | most unstable layer — Bridge depends on 31 internal edges |
| `app.main` | 0 | 2 | 1.00 | entry point |

No dependency cycles between layers (`core` never imports `browser`/`ui`).
The structural risk is the single-module `Bridge` (fan-out 31) acting as the
only seam between UI and everything else: any change anywhere reaches it.

Top fan-in modules (how many modules import them): `app.core.enums` 8,
`app.core.models` 5, `app.core.naming` 5, `app.browser.cdp_client` 4,
`app.browser.probe_requests` 4, `app.core.cooldown` 4,
`app.services.cooldown_service` 4.

**LCOM4 (connected components of methods sharing instance attributes; 1 = cohesive):**

| Class | Methods | LCOM4 | Largest components | Reading |
|---|---:|---:|---|---|
| `Bridge` | 200 | **11** | 187 + 9 clusters (1–2 methods each) | ~11 latent classes inside one god class |
| `CDPClient` | 22 | 3 | 19 + 2 + 1 | two separable concerns (tabs / probes) |
| `CDPArenaController` | 30 | 3 | 28 + 1 + 1 | one big body + 2 orphans |
| `BrowserController` *(dead)* | 22 | 1 | 22 | cohesive, just unused |
| `WatcherService` | 15 | 1 | 15 | cohesive, only over-long |
| `PresetStore` | 22 | 1 | 22 | cohesive but 22 methods (split by read/write) |

## 4. Test quality metrics

| Metric | Target | Measured | Verdict |
|---|---:|---|---|
| Tests green | 100% | **444 pytest passed, 0 failed, 10.0 s**; Node lane 98 passed / 1 error (`jsdom` missing — `npm ci` fixes) | ✅ |
| Line coverage | ≥ 80% | **43.4%** (5,063 / 11,662 statements) | ❌ |
| Branch coverage | ≥ 75% | **32.0%** (1,005 / 3,142 branches) | ❌ |
| Combined coverage (coverage.py `percent_covered`) | — | **41.0%** | ❌ |
| Mutation score | ≥ 70% | **not measured** — no mutation runner in the repo | ⛔ gap |
| Test ∶ code ratio | ~1 : 1 | **1 : 0.38** Python (7,267 / 18,929), 1 : 0.33 JS | ❌ |

Coverage by layer:

| Layer | Statements | Coverage |
|---|---:|---:|
| `app/services` | 3,545 | **69.9%** |
| `app/core` | 829 | **71.8%** |
| `app/persistence` | 451 | **64.5%** |
| `app/utils` | 151 | 52.7% |
| `app/browser` | 2,378 | **35.9%** |
| `app/ui` | 4,286 | **12.8%** |
| `app/main.py` | 21 | 0.0% |

Coverage is **inversely correlated with risk**: the two least-covered files are
the dead legacy stack (0%) and the two largest live files are next
(`bridge.py` 10.7%, `cdp_client.py` 9.3%). Uncovered lines are concentrated:

| Share of all uncovered lines | File |
|---|---:|
| 53% | `app/ui/bridge.py` (3,500 lines) |
| 6.5% | `app/browser/cdp_client.py` (429) |
| 4.5% | `app/browser/controller.py` (297, dead) |
| 3.5% | `app/browser/cdp_arena.py` (231) |
| 3.4% | `app/services/job_runner.py` (226, dead) |

The top 8 files hold **78% of all uncovered lines** — coverage work is not a
long tail, it is these files.

## 5. Code-smell metrics

**Duplicated code (DRY).** jscpd over `app/` + `tests/`, 60-token minimum:
**55 clone groups, 597 duplicated lines, 1.51% of 39,511 lines.** Low overall,
but clustered where it matters:

| Lines | Location A | Location B |
|---:|---|---|
| 27 | `persistence/config_manager.py:34` | `persistence/preset_store.py:15` |
| 27 | `persistence/config_manager.py:34` | `persistence/undo_store.py:11` |
| 20 ×4 + 19 ×2 + 17 ×3 + 12 ×2 + 10 | `ui/bridge.py:3167–3544` (undo/apply-entry clusters) | 10 distinct pairs inside Bridge |
| 17 | `ui/web/js/panels/cdp.js:346` | `ui/web/js/panels/url-list.js:217` |
| 14 | `browser/controller.py:483` (dead) | `browser/output_probes.py:84` |
| 14 ×2 | `browser/output_probes.py:339/354`, `686/743` | internal repetition |

The largest *structural* duplication is not a text clone: `Bridge._do_run_batch`
(lines 2,530–3,734) and `app/services/single_job_runner.py` are **two
implementations of one job lifecycle**. `single_job_runner` dispatches 12 block
types through a handler map (used by `multi_page_dispatcher` on the pooled
path); the bridge loop re-implements 17 branches inline through an
`if/elif` chain. Same phases, same order, two places to fix every block bug.

**Dead code.**

| Module | LOC | Coverage | Evidence | Gate fails |
|---|---:|---:|---|---:|
| `app/browser/controller.py` | 643 | **0.0%** | only importer is `app/services/job_runner.py`, itself unimported | 11 |
| `app/services/job_runner.py` | 332 | **0.0%** | no importer anywhere in `app/`, `tests/`, `tools/` | 5 |
| `app/browser/output_detector.py` | 155 | 71.0% (own unit test only) | **no production importer** — tests only; vulture: `is_job_id_match`, `decide_ready`, `flatten_diagnostics_pure` unused | 0 |
| `app/services/job_state_machine.py` | 109 | 100% (own unit test only) | **no production importer** — tests only | 0 |
| **Total** | **1,239** | — | 6.5% of the Python tree; 661 statements, 550 of them uncovered | **16** |

**Unused symbols / unused imports.** vulture @90%: 2 unused imports
(`build_order_check_text` in `cdp_arena.py`, `_is_cooling` in `page_status.py`).
vulture @60% returns 30 more candidates (unused methods such as
`CDPClient.query_selector_all`, `take_screenshot`, `_is_devtools_url`,
`_filter_real_tabs`, `output_probes.is_layout_reverse_js`) — these need a
per-symbol triage pass because several are dynamically reachable (JS payload
calls, Qt slots).

**God class / long method / feature envy.** `Bridge` is the repository's only
god class by every measure (4,991 LOC, 200 methods, LCOM4 11, fan-out 31,
MI 0.00). `_do_run_batch` is the only true long method at 40× the fail line;
`watcher.check_once` (124 LOC) and `run_single_job` (207 LOC, dead) are the
next tier.

**Selector centralisation (RULE 21) is broken on the live path.** RULE 21 and
`docs/current/DOM_SELECTORS.md` say selectors live in `app/browser/site_adapter.py`
(316 LOC, primary + fallbacks, tested by `tests/test_selector.py`). That module
is imported **only** by the dead `controller.py`; the live probes
(`cdp_arena.py`, `dom_highlight.py`, `output_probes.py`) carry selector
literals inline inside JavaScript payload strings. The documented single
source of truth is therefore unreachable from production.

## 6. Maintainability metrics

| Metric | Meaning | Measured |
|---|---|---|
| Maintainability index — mean | higher = better | **57.53** |
| MI — floor | higher = better | **0.00** (`app/ui/bridge.py`) |
| Files with MI < 20 | 0 | **5** (`bridge.py`, `cooldown_service.py`, `cdp_client.py`, `single_job_runner.py`, `captcha/solver.py`) |
| Files with MI < 40 | 0 | **19 of 78 (24%)** |
| Technical-debt ratio | remediation ÷ development cost | **≈1.95%** — estimate, model below |
| Churn | high = risky | **not measurable** — `git rev-list --count HEAD` = 1 (history squashed) |
| Bug density | bugs per 1,000 LOC | **0.79** — 15 documented defects (§ below) ÷ 18,929 LOC |

**Technical-debt model (estimate, not a measurement).** Sum of remediation
minutes over the 120 gate fails: `class-loc 0.5 min/line over 150`,
`methods 5 min/method over 15`, `loc 0.5 min/line over 30`, `CC 8 min/point
over 10`, `nesting 10 min/level over 4`, `params 5 min/param over 4` →
**11,093 min ≈ 185 h**, dominated by CC (5,064 min) and class size (3,072 min).
Development cost model: 30 min per LOC (SQALE default) × 18,929 = 9,464 h →
ratio **1.95%**. Interpret as "direction and weighting", not as a schedule:
`_do_run_batch` alone contributes ≈ 4,000 min of it.

**Bug density (proxy).** The 2026-09-18 reports document 5 root causes
(RC-1…RC-5) plus 10 verified recorder/viewer defects (P1–P10) in the captcha
path → 15 ÷ 18,929 LOC ≈ **0.79 per 1,000 LOC**. The reports also show the
*diagnostic* cost of the un-instrumented code: rounds 5–11 could not attribute
a specific bot failure to a specific mechanism until the viewer could display
the evidence (report P1–P4, F-A…F-E).

## 7. Metric gaps (things that cannot be measured yet)

| Gap | Why it matters | Owner |
|---|---|---|
| Mutation score | your threshold is ≥ 70%; no runner installed, so "tests catch bugs" is unproven | D5 |
| JS coverage | 34 files / 7,427 lines with no instrumentation; only "does it load" is tested | D4, C7 |
| JS gate | RULE 16 does not see `.js` at all, so 48 functions > 30 LOC and 24 nesting > 4 are invisible to CI | R0.2 |
| Churn | single-commit history; needs per-PR capture from now on | R0.1 |
| Duplication/vulture in CI | measured ad-hoc here; not enforced on push | R0.4 |
| Coverage ratchet | `--allow-legacy` currently downgrades every breach in a baseline file to a warning — a regression *inside* `bridge.py` passes the gate silently | R0.3 |

## 8. Reading of the numbers

1. The codebase is **not uniformly bad**: 71.6% of Python functions sit in the
   4–20 line ideal band, average CC is 4.16 (grade A), duplication is 1.51%, and
   444 tests run in 10 seconds. The quality problem is a **concentrated tail**.
2. That tail is dominated by **one function in one class**
   (`_do_run_batch` in `Bridge`): 44% of gate fails, 53% of uncovered lines,
   MI 0.00, and a duplicated second implementation of a pipeline that already
   exists in service form.
3. Removing dead code and splitting that class is therefore not cosmetic — it
   moves every headline metric at once and deletes the two places where a
   block-level bug has to be fixed twice.
4. Coverage cannot reach 80% without the same work: the top 8 files hold 78% of
   uncovered lines, and 9 of those 10 candidates disappear or become testable
   once Areas A and B land.
