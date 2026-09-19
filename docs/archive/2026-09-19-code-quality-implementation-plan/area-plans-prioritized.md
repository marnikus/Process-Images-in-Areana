# Area Plans — Prioritized, Split into ≤20 LOC Steps

**Based on:** `docs/archive/2026-09-18-code-quality-round/plan-area-*.md` but further split by RULE 19 order (nesting→CC→cognitive→size) and by importance.

Each step: ≤20 LOC funcs, CC ≤7 ideal / ≤10 fail, cognitive ≤10/15, nesting ≤3/4, file 150–300 ideal, test that fails if deleted.

---

## Round 0 — Shared foundation (one owner, before areas branch)

| Step | Deliverable | Priority | Done when |
|---|---|---|---|
| R0.1 | `tools/metrics_report.py` — one command reproducing every number in `metrics-baseline-2026-09-18.md` ±1% (radon CC/MI, cognitive, nesting, LOC, coverage, jscpd, vulture, coupling, LCOM4, JS acorn) | P0 | `python tools/metrics_report.py` reproduces tables |
| R0.2 | JS gate in `verify_quality.py` (acorn-based) | P0 | Bloated JS fails gate, current JS grandfathered via baseline |
| R0.3 | Baseline ratchet `quality_baseline.json` per-metric maxima per file, gate fails on increase even in legacy | P0 | Adding 31-LOC func to `bridge.py` fails |
| R0.4 | Wire vulture + jscpd + coverage.json into `pre_push_check.sh` | P0 | `bash tools/pre_push_check.sh` runs all lanes |
| R0.5 | Lanes: `pytest -m "not slow and not e2e"` fast, `node --test tests/js/*`, `npm ci` docs | P1 | All 3 lanes green (JS after `npm ci`) |
| R0.6 | Mutation runner decision (`mutmut` vs `cosmic-ray`) + baseline score for `core/**` + `services/**` | P1 | Mutation number exists ≥70% target |

---

## Area B — Dead code & duplication (1st, quick win)

**Owns:** `controller.py`, `job_runner.py`, `output_detector.py`, `job_state_machine.py`, `site_adapter.py`, `tests/unit/test_output_detector.py`, `test_job_state_machine.py`, `DOM_SELECTORS.md`, `persistence/{config_manager,preset_store,undo_store}.py` (B5 only)

| Step | Action | Priority | Metric delta | RULE 19 |
|---|---|---|---|---|
| B1 | Prove deadness 3 detectors (import graph, symbol refs, runtime 0% coverage) — no writes | P0 | Table in PR | — |
| B2 | Delete 4 modules + 2 tests, port predicate if live needs it in same commit | P0 | fails 121→105, LOC −1,239, stmts −661 (550 uncovered), cov 43.4→45.0% | size last |
| B3 | Restore RULE 21: generate probe selectors from `site_adapter` or fallback delete + lint test | P1 | 1 fail removed if fallback, prevents selector drift | CC→cognitive→size |
| B4 | Unused imports + vulture @60 triage (payload grep for `clear_highlights`, `take_screenshot` etc) | P1 | vulture @90 0 | nesting first |
| B5 | Duplication: extract `json_store.py` (27 lines×2), `output_probes` internal builder | P2 | dup 1.51→1.25% | size last |
| B6 | Baseline + docs: regenerate `quality_baseline.json` (integrator only), update `SYSTEM_OF_RECORD.md` §7 + `README.md` | P2 | Baseline consistent | — |

**Anti-gaming:** No `foo_part1`, no `**kwargs` dodge. Deletion is reversible by revert.

---

## Area A — Run pipeline unification + Bridge decomposition (2nd, biggest)

**Owns:** `bridge.py`, `panels/**` (new), `single_job_runner.py`, `multi_page_dispatcher.py`, `batch_orchestrator.py` (new), `run_state.py` (new), `tests/characterization/**`

| Step | Action | Priority | Metric delta | RULE 19 |
|---|---|---|---|---|
| A1 | Characterization harness: fake ctrl, fake CDP, fake bridge, action stacks covering 17 block types, trace (block,status,log,signal,file) per image. Scenarios: happy, disabled, mid-fail, cancel pre-delay, stop-after, captcha pause/resume, page-error abort. | P0 | 8–12 goldens, pass on unmodified `_do_run_batch` | — |
| A2 | Converge pipelines: port 8 missing handlers into `single_job_runner` handler map, one per ≤20 LOC func, params ≤3 (JobCtx) | P0 | `single_job_runner` cov 33.9→≥80%, block coverage 12→20 | nesting→CC→cognitive→size |
| A3 | Extract outer loop into `batch_orchestrator.py`: `should_continue`, `await_pause_or_abort`, `resolve_and_claim_tab`, `await_cooldown_if_pooled`, `mark_processing`, `build_job_ids`, `finish_image`, `run_batch` — each ≤20 LOC CC≤7 | P0 | No file >300, goldens green | flatten guards first (early continue/break) |
| A4 | Flip `start_run` onto shared runner + delete 995-line inline loop + `_do_run_batch` shell | P0 | 53 fails→0 for bridge, longest func 1,209→124 LOC, bridge 5,127→≤1,500 | size last |
| A5 | Split Bridge into facade + panel mixins `panels/` (12 files ≤300, ≤10 methods each) by LCOM4 clusters: run-control 9, browser/cdp 39, urls/folder/queue 33, layout/presets/theme 35, undo 11, settings/prompt/blocks 18, watcher 7, captcha 6, misc 42. Bridge = `class Bridge(CoreMixin, …)` with only `__init__`, signals, slot delegations 1–5 lines | P1 | bridge ≤300 lines, Bridge class ≤120 LOC / ≤10 methods, LCOM4 11→1 per mixin | methods→class LOC |
| A6 | Decompose `Bridge.__init__` 122 LOC / CC 14 → `BridgeContext` dataclass + `_build_context()` + `_wire_*()` ≤15 LOC each, `__init__` ≤20 LOC | P1 | `__init__` coverage 1%→≥80% | CC→cognitive→size |
| A7 | Sweep, recheck, handover: orphaned helpers, dead imports, update `SYSTEM_OF_RECORD.md` §7, write `implementation-area-a.md` | P2 | Global fails lower, no override | — |

**Seams:** `services/**` must not import PySide6 (source scan test), `bridge.py` ≤300 lines, every `@Slot` body ≤10 stmts, slot names frozen (`test_bridge_slots.py`).

**Risks:** Behaviour drift → goldens + per-handler tests before deletion. Slot breakage → signal-signature test + manual smoke. Async semantics → scheduling seam in one module `run_state.py`.

---

## Area C — Complexity hotspots (3rd, parallel with D)

**Owns:** `cdp_client.py`, `cdp_arena.py`, `output_wait.py`, `output_state.py`, `output_probes.py`, `dom_highlight.py`, `visual_click.py`, `watcher.py`, `verification.py`, `cooldown_service.py`, `core/{scanner,persistence,undo_service,layout_service,naming,models,action_blocks}.py`, `preset_store.py`, `main_window.py`, `web/js/**`

| Step | Symbol | Now | Action | Target |
|---|---|---|---|---|
| C1 | `watcher.check_once` | 124 LOC CC35 cog82 class 269 | Split by decision: `_collect_queue_snapshot`, `_should_dispatch`, `_pick_dispatch_target`, `_announce_overlay`, `check_once` ≤20 LOC; move overlay helpers to `watcher_overlay.py` | 0 fails, cov 27→80% |
| C2 | `cdp_client.py` | 647 LOC class 469/22 methods 15 fails, `_connect_inner` CC27, `fetch_tabs_sync` 36 LOC nest5 | Package split: `cdp/transport.py` (socket+lock I-22), `cdp/connect.py`, `cdp/tabs.py`, `cdp/probe.py`, `cdp_client.py` ≤150 facade | 15→0 fails, cov 9→80% |
| C3 | `cdp_arena.py` | class 371/30 3 fails, `highlight_selector` CC13 | Split: `cdp_arena_highlight.py`, `attach.py`, `submit.py`, root ≤150 composition | 3→0 fails, cov 29→80% |
| C4 | `verification.validate_downloaded_file` | 42 LOC CC14 nest5 | Guard clauses + `is_html_response`, `has_valid_image_dimensions`, `is_nonempty` → ≤15 LOC orchestrator, `ValidationResult` dataclass | 3→0 fails, cov 38→90% |
| C5 | `core/` | `reconcile_with_filesystem` 101 LOC CC21, `scan_folder` 66 LOC CC13, `undo` 38 LOC CC12, `normalize_grid_tree` cog21, `get_output_path` 6 params | Predicate table, dispatch table per undo kind, `OutputSpec`/`ImageSpec` param objects, data/behaviour split for `action_blocks` | 5→0 fails, each ≥80% |
| C6 | `output_wait`/`dom_highlight`/`preset_store`/`main_window` | `wait_for_new_output_loop` 5 params CC16, `build_highlight_rect_js` 7 params, `preset_store` 22 methods, `main_window.__init__` 31 LOC | `WaitSpec` + `_poll_once` ≤20, `HighlightSpec` dataclass, split `preset_store_read/write`, `_build_services`+`_build_ui` | 7→0 fails |
| C7 | JS panels | `action-blocks.js` 838 anon 169 LOC CC90, `arena-app.js` `setupBridgeListeners` 164 LOC CC66, etc. | Extract `block-store.js`, `block-config.js`, `block-render.js`, listener registry table, row-state helpers, status rendering; each pure func gets `tests/js/*.mjs` test (Tier A `node --test`) | funcs>30 48→≤10, nest>4 24→0, files>300 8→≤3 |
| C8 | JS dup | `cdp.js`↔`url-list.js` 17-line clone | Move to `core/ui-helpers.js`, add `c8` instrumentation | dup gone, JS cov number exists |

**RULE 19 inside each step:** flatten nesting first (early return), then dispatch table vs if/elif, then name predicates, then size. Payload-equality test asserts rendered JS string (normalised whitespace).

---

## Area D — Verification & evidence (parallel with C, D1 immediate)

**Owns:** `tests/**`, `tools/**`, `captcha_recording/**`, `captcha_recordings_bridge.py`

| Step | Action | Priority | Metric |
|---|---|---|---|
| D1 | Fix silent loss `network.py`: replace check-then-get with lock-protected deque or `call_soon_threadsafe`, add `dropped_events` counter, worker-thread regression test hammers `on_event` while `drain` | P0 live bug | `network.py` cov ≥90%, bug density 0.79→0.74 |
| D2 | Persist bounded milestones (F-B): task-created offset+id, poll count, token-ready offset, page/challenge identity detect vs token, response-field count/scope pre/post, callback source+result, continue result, page-error offset, dialog-clear offset, acceptance-candidate offset, final job result joined by eid. No raw tokens (I-29/I-32 assert) | P1 | Golden test synthetic session, size bounds asserted |
| D3 | Independent labels (F-C): `result_label: unknown\|passed\|failed` next to actor, allow `mixed`, history timestamps, viewer wording fix (actor≠outcome), exclude unknown/mixed from cohort stats | P1 | Model/store tests, snapshot test |
| D4 | Coverage ramp ratchet by uncovered lines: D4.1 `single_job_runner`, `batch_orchestrator`, `multi_page_dispatcher`, `watcher` →55%; D4.2 `cdp_client`, `cdp_arena`, `output_wait`, `dom_highlight`, `visual_click` →63%; D4.3 `bridge.py` slot contracts post-A5 →70%; D4.4 `core/**`, `persistence/**`, `captcha*` fail-closed invariants I-11,I-13,I-17,I-22 →80%/75%; D4.5 JS `c8` + jsdom → JS number ≥70% | P0 | Line 43→80, branch 32→75, test:code 1:0.38→1:0.8 min 1:1 goal, RULE 8 each test fails if target deleted |
| D5 | Mutation: install runner `mutmut` or `cosmic-ray`, scope `services/**`+`core/**`+`browser/cdp*`, triage survivors (missing assertion / equivalent / dead code) | P1 | Mutation ≥70% (Old App 99.4% baseline) |
| D6 | Close gate hole: baseline ratchet per-metric maxima per file, JS gate acorn, lanes in `pre_push_check.sh` (fast pytest, coverage, JS tests, vulture @90, jscpd delta), changed-file detection via merge-base `origin/main` | P0 | Negative tests: adding 31-LOC func to bridge fails, 40-LOC JS fails, dropping coverage fails |
| D7 | Round recheck: final RULE 16 + RULE 18 audit, `metrics-report-2026-09-2X.md` Before→After, update `SYSTEM_OF_RECORD.md` §9 quality gates | P2 | Report in Old-App format |

**Anti-gaming:** Coverage chasing (assert nothing) → RULE 8 review + mutation anti-gaming. Denominator shrinking by deletion → report absolute covered stmts + %.

---

## Expected deltas (from README)

```
Round 0 (measure+enforce)
 └─ B (dead code) fails 121→105, LOC −1,239, stmts −661 (550 uncovered), cov 43.4→45.0%
      └─ A (run pipeline) fails 105→52, bridge 5,127→≤300, MI 0.00→≥60, cov +12 pts
           ├─ C (hotspots) fails 52→≤5 documented overrides, JS >30 48→≤10
           └─ D (verification) cov 43/32→80/75, mutation ≥70%, gate no hole
                   └─ final recheck: RULE 16 report v2 + RULE 18 audit
```

End-state: max func ≤30, max class ≤150, 0 fails, MI floor ≥40 mean ≥65, cov ≥80/75, dup ≤1%, dead 0, JS gated.
