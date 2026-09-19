# Refactor cycle X — integrating R0 + A + B + C into one branch

*2026-09-19. Areas R0 (tooling), A (bridge/panel split + run pipeline),
B (dead code, RULE 21, duplication, gate integrity) and C (core/browser/JS
splits) were developed on three parallel arena branches from the same base
(`8529d6b`). This record explains how they were merged into the current
branch, which side won each conflict and why. Area D is not part of this
cycle.*

## 1. Why a plain `git merge` could not work

`git merge-tree --write-tree` before touching anything:

| Merge | Conflicts | Meaning |
|---|---|---|
| current (R0+C) × A | 3 files | A and C both rewrote `bridge.py`, `single_job_runner.py`, `SYSTEM_OF_RECORD.md` |
| current (R0+C) × B | ~85 files | B and C are alternative implementations of the same files |
| A × B | 172 files | A and B chose different decompositions of the same areas |

A and B are *not* additive: A split `bridge.py` into 12 domain panels plus
`ui/services/*` and converged both run lanes onto one
`single_job_runner`; B split it into 21 panels, left the sequential lane in
its own `batch_orchestrator` copy, and deleted four modules A still carries.
C never touched `bridge.py` (4,592 lines at the tip) but did all the core,
browser and JS work A and B left alone.

So the merge was decided per deliverable, not per file:

| Deliverable | Source | Why |
|---|---|---|
| Bridge facade + panel split | **A** | 12 panels (RULE 18 module ideal 5–15 files) vs B's 21; panels delegate to `ui/services/*`; `bridge.py` 149 LOC / 10 methods vs B's 108 with 21 panels |
| Run pipeline (`batch_orchestrator`, `single_job_runner`, `run_state`) | **A** | one block pipeline for sequential *and* parallel lanes (`batch_orchestrator` 492 LOC / max func 17 / max CC 7); B kept two copies (1,484 LOC orchestrator, own `_BLOCK_HANDLERS`) |
| Behaviour lock | **A** | 12 batch goldens + harness (B has 3) |
| Slot-surface contract | **A** | exact 119-slot test + 12-panel packing test |
| Core/browser/JS splits, param objects, gate lanes R0.1–R0.6 | **C** | C did the whole long tail A/B did not: `cdp/`, `cdp_arena/`, `dom_highlight_js`, `WaitSpec`/`OutputSpec`/`ScanSpec`, watcher split, `js/panels/*` splits, `metrics_report.py` |
| Dead-code purge | **B** | proof (import graph + symbol refs + runtime coverage) that `controller.py`, `job_runner.py`, `output_detector.py`, `job_state_machine.py` are dead |
| RULE 21 single selector source | **B** | `probe_selectors.py` + lint/wiring tests; C still had literals in `cdp_arena` payloads |
| Duplication: one atomic JSON store | **B** | `json_store.py` replaces four copies |
| Gate integrity | **B** | per-symbol legacy ratchet, tamper-proof coverage floor, honest `--changed` fallback, negative tests for the tool itself |

## 2. What the integration actually changed

1. **X1 — Area A merged in** (`4465407`). A's UI cluster arrived on top of
   C's core: `app/ui/panels/*` (12 mixins), `bridge_context.py`,
   `qt_compat.py`, `ui/services/*`, `services/batch_orchestrator.py`,
   `run_state.py`, the converged `single_job_runner.py` and
   `tests/characterization/*`. One real API seam had to be adapted:
   `save_image` built the legacy 6-kwarg `get_output_path(...)` call →
   now builds `OutputSpec` (C's param object). `scan_service` auto-merged.
2. **X2 — Area B ported in** (`e7b4fbd`): the four dead modules and their
   tests deleted; `site_adapter` → `probe_selectors` rewiring of every probe
   payload (`cdp_arena/js_snippets.py` uses `_inject` placeholders, `submit.py`,
   `output_probes.py`, `new_chat.py`, `single_job_runner` defaults,
   `cdp_tools` panel, `cdp/dom.py` constant); `json_store.py` dedup; B's
   gate tool, pre-push script and tool tests.
3. **Tools merged**: B's `verify_quality.py` (per-symbol legacy ratchet,
   coverage-floor guard, honest fallback) **plus** C's JS lane
   (`tools/js_metrics.js` via acorn) and C's per-file coverage ratchet. The
   pre-push script now runs B's lanes (pytest, node, fresh coverage, gate
   with `--coverage-ratchet`) and C's R0.4 lanes (vulture @90 with the
   whitelist, jscpd, metrics report).
4. **Baseline re-recorded** (`--record-baseline`, the reviewed
   integrator-only path): 125 py + 74 JS entries, coverage floor
   `line 68.44 / branch 61.02`. This is the only action that may raise a
   recorded maximum, and it was needed because X1/X2 replace whole files.

## 3. Regressions found by integrating (all fixed, all now covered by tests)

| Regression | Detected by | Fix |
|---|---|---|
| `@Slot` sat on the private helper `_find_image_by_id` while the JS-called `get_image_thumbnail` lost its decorator (QWebChannel drops such calls silently) | A's exact 119-slot test | taking A's panel split; `get_image_thumbnail` is a real slot again |
| **`CDPClient.connect()` raised `TypeError` on any real-Qt machine**: on a QObject *subclass*, PySide6 resolves an inherited `disconnect` to `QObject.disconnect` (built-in) instead of the transport coroutine. C's `cdp/` split introduced the inheritance, so the bug was live in the R0+C line | B's cdp stub-server tests, ported in X2 | `CDPClient` defines its own `disconnect` + `test_disconnect_is_not_shadowed_by_qobject` |
| Probe payloads lost RULE 21 wiring (selector literals inline) | B's `test_probe_selectors.py` | `_inject` placeholders + `probe_selectors` |
| `tests/js/test_composer_probes.mjs`, `tests/test_action_block_defaults.py` still pointed at pre-C7/C3 file shapes | ported tests | candidates lists for the facade/package split |

Payload equivalence was checked, not assumed: the 16 rendered JS payloads
(`JS_FIND_TEXTAREA`, `JS_INSERT_PROMPT`, `JS_PAGE_READY`, `JS_CHECK_NEW_OUTPUT_V3`, …)
were dumped before/after the port and differ only in JSON quote style and
B's semantic-preserving JS helpers (`jobRecord`, `assocShape`,
`oldWasNotReady`, `mismatchReturn`).

## 4. Verification

| State | pytest | node --test | Full gate fails | Coverage line / branch |
|---|---|---|---|---|
| C tip `b7d3155` | 548 | 135 | **33** (25 `bridge.py`, 2 `controller.py`, 6 ratchet drift) | floor 41 / 32 |
| A tip `908d4da` | 583 | 105 | 86 | — |
| B tip `9294ced` | 622 | 115 | 3 | floor 58.83 / 51.16 |
| **X (this branch)** | **776 passed / 4 skipped** | **135** | **0** | **68.44 / 61.02** (ratchet; 80/75 = D4 target, warns) |

Commands (all green on this branch):

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q
npm run test:js
.venv/bin/python tools/verify_quality.py --allow-legacy --coverage-ratchet
bash tools/pre_push_check.sh
```

## 5. RULE 18 audit (read the file, then trust it)

* `bridge.py` 4,592 → **149** LOC / 10 methods; panels 278–544 LOC, each with
  an `ideal-size:` reason where it exceeds 300 (their class LOC is ≤150 and
  every function ≤30).
* 15 files remain >300 LOC. All but three carry an `ideal-size:` reason;
  this merge **added** reasons to `core/action_blocks.py` (catalog table),
  `browser/output_probes.py` (atomic JS payloads) and
  `services/captcha/solver.py` (co- dependent state machine). The largest,
  `services/single_job_runner.py` (875), is the intentional price of the
  pipeline convergence: every block handler lives in one dispatch table.
  Splitting it is a candidate for the next cycle, together with the JS
  `ui-helpers.esm.mjs` copy that jscpd reports as 118 duplicated lines.
* Gate met: class LOC ≤150 (max 0 over), function LOC ≤30 (1 override:
  `build_watcher_overlay_js_from_spec`, embedded JS literal, RULE 16.1.5),
  CC ≤10, cognitive ≤15, nesting ≤4, params ≤4, vulture @90 clean.

## 6. Not in this cycle

* **Area D** (the explicitly deferred area).
* Absolute coverage target 80 / 75 (D4): the ratchet floor is 68.44 / 61.02
  and must only move up from here.
* The 15 >300-LOC files and the ESM/`ui-helpers` duplication pair — listed
  above so the next cycle starts from facts, not from a re-measurement.
