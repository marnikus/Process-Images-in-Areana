# Step 1 — Understand fully, split into 10 prioritized sub-steps

**Goal:** No code change, only measurement and proof. Each sub-step has: what to measure, command, evidence, decision, owner, and why its priority.

Priority = severity model: Blast×3 + Evidence×2 + Gate×2 + Defect×2 + Delay×1. Score from `problem-priority.md`.

---

## 1.1 — Re-measure baseline with one command (Round 0 R0.1) — Enables all

**Why first:** Without one command, numbers drift. Current numbers from `67fae78` may be stale (now 121 fails, bridge 5,127 vs 5,118). Must reproduce within ±1%.

**Measure:**
- `python tools/verify_quality.py --json > /tmp/gate.json` → fails 121, breakdown by metric/file
- `QT_QPA_PLATFORM=offscreen coverage run --branch --source=app -m pytest tests -q` → line 43.4% branch 32.0%
- `radon cc -s app`, `radon mi -s app`, cognitive, nesting, LOC distribution (appendix A.4)
- `jscpd app tests --min-tokens 60`, `vulture app --min-confidence 90/60`, LCOM4, coupling

**Evidence:** `/tmp/gate.json`, `/tmp/coverage.json`, `tools/metrics_report.py` (to be built) must output same tables as `metrics-baseline-2026-09-18.md` ±1%.

**Decision:** Build `tools/metrics_report.py` that prints all six families. Done when `python tools/metrics_report.py` reproduces baseline.

**Owner:** Round 0, single owner, before areas branch.

---

## 1.2 — Critical path: `Bridge._do_run_batch` mega-function (P1, score 96, Critical)

**Why:** 1,205 LOC / CC 354 / cog 1,097 / nest 23, 0% covered, 995-line inline `for block in` loop re-implementing 17 block types vs `single_job_runner` handler map (12 types). Every block fix applied twice. Holds 44% fails, 53% uncovered.

**Measure:**
- `grep -n "_do_run_batch" app/ui/bridge.py` → lines 2,533–3,742 (now 1,209 LOC)
- `radon cc -s app/ui/bridge.py | grep _do_run_batch`
- Compare block types: `grep -n "elif btype" app/ui/bridge.py` vs `grep -n "def _handle" app/services/single_job_runner.py`
- Missing handlers: `HIGHLIGHT_ATTACH`, `HIGHLIGHT_PROMPT`, `HIGHLIGHT_SUBMIT`, `HIGHLIGHT`, `PAUSE`, `TYPE_PROMPT`, `VERIFY_ATTACHMENT`, `VERIFY_PROMPT` (8 types)

**Evidence:** Two implementations of one lifecycle. Bridge loop 17 branches, service map 12.

**Decision:** Converge pipelines: port 8 handlers into `single_job_runner`, then extract outer loop into `batch_orchestrator.py`, then delete duplicate. Needs golden harness first (A1).

**Owner:** Area A steps A1–A4.

---

## 1.3 — God class: `Bridge` (P2, score 92, Critical)

**Why:** 4,991 LOC (now 5,000), 200 methods, 119 @Slots, LCOM4 11 (187 + 9 clusters), MI 0.00, fan-out 31, coverage 10.7% (3,500 uncovered = 53% total). Only seam UI↔rest.

**Measure:**
- `wc -l app/ui/bridge.py`, `grep -c "@Slot" app/ui/bridge.py`, `grep -c "def " app/ui/bridge.py`
- LCOM4 via appendix A.9 script → 11 components
- `radon mi -s app/ui/bridge.py` → 0.00
- `grep -n "import app\." app/ui/bridge.py | wc -l` → fan-out 31

**Evidence:** 53/121 fails, 53% uncovered, LCOM4 11 latent classes.

**Decision:** Split into facade + panel mixins `app/ui/panels/` (12 files, ≤300 lines, ≤10 methods each) by LCOM4/domain clustering. `Bridge` becomes `Bridge(CoreMixin, LayoutMixin, …)` with only `__init__`, signals, slot delegations 1–5 lines. `__init__` 122 LOC / CC 14 → `BridgeContext` + `_wire_*()` ≤15 LOC each.

**Owner:** Area A steps A5–A6.

---

## 1.4 — Dead legacy stack (P3, score 74, High) — Quick win, do first in implementation

**Why:** 1,239 LOC, 661 stmts (550 uncovered), 16 fails, 0% coverage for `controller.py` 643 + `job_runner.py` 332. No prod importer. Second-highest CC lives here (`run_single_job` CC 24). Deleting shrinks map for A.

**Measure (three detectors, appendix A.6):**
1. Import graph: `mods` over `app/` + `tests/` + `tools/` → zero importers for 4 modules
2. Symbol refs: `grep -rn "BrowserController\|JobRunner\|can_job_transition\|decide_ready" app tests tools`
3. Runtime: coverage 0.0% after full suite, no string import

**Evidence:** Table module→detector→result. `output_detector.py` 155 LOC 71% (own test only), `job_state_machine.py` 109 LOC 100% (own test only) — imported only by tests.

**Decision:** Delete 4 modules + 2 test files in one commit, with rule "port predicate if live pipeline needs it, in same commit". Expected: fails 121→105, line 43.4→45.0% with no new test.

**Owner:** Area B step B2, runs first.

---

## 1.5 — Selector centralisation violated (P4, score 68, High)

**Why:** RULE 21 + `DOM_SELECTORS.md` says selectors live in `site_adapter.py` 316 LOC primary+fallbacks, tested. That module imported only by dead `controller.py`. Live probes `cdp_arena.py`, `dom_highlight.py`, `output_probes.py` hardcode literals in JS payload strings. Most frequent prod change is selector drift.

**Measure:**
- `grep -rn "site_adapter" app/` → only dead controller
- `grep -n "querySelector" app/browser/cdp_arena.py app/browser/dom_highlight.py app/browser/output_probes.py`
- Compare literals vs `site_adapter.py` primary list

**Evidence:** Single source unreachable from prod.

**Decision:** Preferred: generate probe selectors from `site_adapter` (probes receive selector list as JSON param). Fallback: delete `site_adapter.py` and make `DOM_SELECTORS.md` reference with lint test. Timebox one session, ≤150 LOC for generator.

**Owner:** Area B step B3.

---

## 1.6 — Silent evidence loss (P5, score 66, High) — Live bug, can start immediately

**Why:** `captcha_recording/network.py` `on_event` runs on websocket thread, `drain()` on bridge loop, `while not empty(): get_nowait()` can raise `QueueEmpty` when put lands between check and get → recorder worker dies, session loses network evidence silently. Makes rounds 5–11 unprovable.

**Measure:**
- Read `network.py` `drain()` loop
- Write regression test: hammer `on_event` while `drain` runs, expect failure on current code
- Check `recorder.py::_run` exception handling

**Evidence:** P9 report OPEN, `dropped_events` counter missing.

**Decision:** Replace check-then-get with lock-protected `deque` + `popleft()` try/except or `loop.call_soon_threadsafe`. Add `dropped_events` to manifest, regression test.

**Owner:** Area D step D1, can start immediately parallel with Round 0.

---

## 1.7 — Coverage & gate hole (P6, score 63, High)

**Why:** Line 43.4% vs 80%, branch 32.0% vs 75%, test:code 1:0.38, mutation unmeasured. Worse: `--allow-legacy` downgrades every breach in baseline file to warning, so new 40-line func in `bridge.py` passes pre-push. `coverage.json` not produced by hook, vulture/duplication/JS never run.

**Measure:**
- `python tools/verify_quality.py --changed --allow-legacy` vs `--changed` → shows hole
- `cat tools/pre_push_check.sh` → lanes missing
- `ls coverage.json` → missing
- `grep -rn "allow-legacy" tools/`

**Evidence:** Gate hole lets regressions through.

**Decision:** Baseline ratchet: per-metric maxima per file, gate fails on any increase even in legacy. JS gate via acorn, lanes: fast pytest, coverage, JS tests, vulture @90, jscpd delta. Changed-file detection uses merge-base with `origin/main`.

**Owner:** Area D steps D4–D6 + Round 0 R0.3–R0.4.

---

## 1.8 — Complexity hotspots outside bridge (P7, score 52, Med-High)

**Why:** 51 fails across 18 files after A/B. Worst: `watcher.check_once` 124 LOC / CC 35 / cog 82 / class 269 LOC, `cdp_client._connect_inner` CC 27 / cog 41, `fetch_tabs_sync` 36 LOC / nest 5, `highlight_selector` CC 13, `validate_downloaded_file` 42 LOC / CC 14 / nest 5, `reconcile_with_filesystem` 101 LOC / CC 21, etc.

**Measure:**
- `python tools/verify_quality.py --json` → filter fails not in bridge/controller/job_runner
- Sort by CC descending

**Evidence:** One hot symbol per file, all fixable locally with RULE 19 order.

**Decision:** Split by decision, not line count. Extract `_collect_queue_snapshot`, `_should_dispatch`, `_pick_dispatch_target` etc. Each ≤20 LOC, CC ≤7, nesting ≤3. Use predicate tables, dispatch maps.

**Owner:** Area C steps C1–C6.

---

## 1.9 — Un-gated JS mass (P8, score 47, Medium)

**Why:** 34 files / 7,427 lines / 995 funcs, 48 funcs >30 LOC, 24 nesting>4, max file 838 lines, max func 169 LOC CC≈90 (`action-blocks.js:525`), `setupBridgeListeners` 164 LOC CC≈66. RULE 16 sees none.

**Measure:**
- `find app/ui/web -name "*.js" | wc -l`, `wc -l app/ui/web/js/**/*.js`
- Acorn metrics via `/tmp/jsacorn/metrics.mjs` → >30 LOC 48, nesting>4 24, CC>10

**Evidence:** Old App audit same: "frontend is largest un-gated mass".

**Decision:** Round 0 R0.2 JS gate (acorn: func ≤30, params ≤4, nesting ≤4, rough CC ≤10, file ≤300). Then C7 split panels: `action-blocks.js` 838 → `block-store.js` + `block-config.js` + `block-render.js`, etc. Extract pure logic under `node --test`.

**Owner:** Round 0 + Area C steps C7–C8.

---

## 1.10 — Duplication & dead symbols (P9, score 33, Low-Med)

**Why:** jscpd 55 groups / 597 lines / 1.51% low overall but clustered: persistence loader triple 27 lines ×2, Bridge undo cluster 3,189–3,544 10 internal pairs, `cdp.js`↔`url-list.js` 17-line, `output_probes` internal. Vulture @90 2 unused imports, @60 30 candidates.

**Measure:**
- `npx jscpd app tests --min-tokens 60 --reporters json`
- `vulture app --min-confidence 90` and 60
- `grep -n "build_order_check_text" app/browser/cdp_arena.py`, `_is_cooling` in `page_status.py`

**Evidence:** Duplication not systemic, but prevents single-source fix.

**Decision:** B4 delete 2 unused imports + triage @60 with payload grep. B5 extract `json_store.py` (`load_json`, `save_json_atomic`) for persistence triple. C8 dedup JS into `ui-helpers.js`. Bridge undo deferred to A5/A7.

**Owner:** Area B steps B4–B5 + Area C C8.

---

## Prioritized implementation order (different from understanding order)

Understanding order = severity score. Implementation order = cost of delay + dependency:

1. **Round 0** (measure & enforce) — one owner, base for all
2. **B** (dead code purge) — quick win, −16 fails, −1,239 LOC, shrinks A's map, reversible
3. **A** (run pipeline + Bridge) — centre of gravity, −53 fails, MI 0.00→≥60
4. **C** (hotspots) + **D** (verification) parallel after A, but **D1 (P5 bug) starts immediately**

This order ensures global fails strictly decrease each area, coverage never decreases, and each step has test that fails if unit deleted (RULE 8).
