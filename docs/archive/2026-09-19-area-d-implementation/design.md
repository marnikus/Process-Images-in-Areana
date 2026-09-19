# Area D — Implementation Design (2026-09-19)

> **Integration note (2026-09-19, cycle R2).** Everything below was designed,
> implemented and measured on `arena/01a0b97a-process-images-in-areana` (A's tip
> + D1–D6). It was then integrated into the cycle branch per deliverable; the
> seams, the gate changes and the re-recorded baselines are recorded in
> `docs/archive/2026-09-19-refactor-cycle-integration/design.md` §8. Numbers in
> this file describe **D's branch**; the integrated tree's numbers are §8.4.
> `d5-results/branch-d/` keeps this branch's original mutation summaries now that
> the tooling has been re-run on the integrated tree (see `d5-mutation.md`).

**Plan source:** `docs/archive/2026-09-18-code-quality-round/plan-area-d-verification-and-evidence.md` (D1–D7).
**Branch:** `arena/01a0b97a-process-images-in-areana`. **Process:** RULE 16.6 (understand → design → tests first → measure → docs).

## Measured start (this round, before any D change)

* 590 tests green. Coverage (pytest, --branch --source=app): **line 59.2% (7196/11724), branch 50.3% (1469/2922)**.
* Gate: `tools/verify_quality.py` → 88 fails on full tree; `--allow-legacy` downgrades **every** breach in a
  baseline-listed file to a warning → new oversized code inside `cdp_client.py`/`cdp_arena.py` passes pre-push. **This is the D6 hole.**
* Baseline format v1: per-file `{max_func_loc, max_class_loc, func_count}` only — no params/methods/cc/cognitive/nesting, no per-symbol, no coverage.
* `pre_push_check.sh`: syntax + changed-gate + full pytest + totals coverage only. No JS lane, no vulture, no jscpd, no per-file coverage ratchet.
* D1 core (lock-protected deque in `network.py`) already merged; **missing:** `dropped_events` counter + manifest field + post-close counting.
* D2/D3 absent: no `milestone` events, no `result_label`, no cohort builder.
* Dead code still on tree (Area B leftover B2, verified dead 2026-09-19 by import graph + 0% coverage):
  `app/browser/controller.py` (297 stmts, 0% cov), `app/services/job_runner.py` (226 stmts, 0%),
  `app/browser/output_detector.py` + `app/services/job_state_machine.py` (imported only by their own tests).
  **Deleted as D4 prep** (B2's own scope: "Delete 4 modules + 2 tests"). Absolute-statement delta recorded in the metrics report (anti-gaming rule).

## D1 — dropped_events (complete the P9 fix)

`NetworkCollector` gains: `close()` (lock: set `closed`, count leftover deque items as dropped),
`on_event` counts appends-after-close as dropped, `dropped_events` property. `recorder.finish()`
closes the collector after its final drain (events landing between drain-end and listener detach were
the remaining silent-loss window). Manifest gains `dropped_events: int` (0 on normal path).
Tests: hammer test asserts `dropped_events == 0` and that post-close events are counted, not lost silently.

## D2 — bounded token-free milestones (F-B)

New `app/services/captcha_recording/milestones.py` (pure, no I/O):

* `build_milestone(phase, outcome, *, offset_ms) -> dict` — per-phase field whitelist over `SolveOutcome`;
  every string ≤200 chars (`redact_text`), every value JSON-scalar. Phases:
  `task_created, token_ready, injected, page_error, dialog_cleared, acceptance_candidate, auto_finished, final`.
* `assert_token_free(value)` — raises on any token-shaped string (reuses sanitize regexes via new public
  `sanitize.contains_tokenish`); recorder catches and **skips the milestone** (fail closed: nothing half-written).

`SolveOutcome` gains bounded evidence fields (additive defaults, RULE 16.5-safe):
`task_created_sec, dialog_cleared_sec, page_identity, challenge_identity, continue_result` — filled by the
solver from `SolvePlan` (identities already there) in `_failed`/`_solved`. Solver gains one instance-level
`milestone_hook(tab_id, phase, outcome)` (added as optional `__init__` arg → 4 params, under the cap),
fired at task-created / token-ready / dialog-cleared. `CaptchaService` wires it to `recordings.note`.
`recorder.note_outcome` now writes `kind="milestone"` events (replaces the thinner `state` payload).
`reader.details()` returns a `milestones` list (full scan, each row bounded).
Golden test: synthetic session task_created→token_ready→auto_finished→final; token-free assertion test
(100-char token smuggled into reason/inject/task_id never reaches events.jsonl); size-bounds asserted.

## D3 — independent ground-truth labels (F-C)

* `models.py`: `VALID_RESULT_LABELS = {unknown, passed, failed, mixed}` (actor labels unchanged).
* `store.py`: manifest gains `result_label` + `label_history` (timestamped entries per change);
  new `set_result_label()` (invalid label → ValueError). `_summary` carries `result_label`.
* New `app/services/captcha_recording/cohort.py`: `cohort(sessions) -> dict` — actor×result matrix;
  **pure** success-rate stats use only `result_label ∈ {passed, failed}` (unknown/mixed excluded);
  mixed counts separately. No token exposure: input is summaries only.
* Bridge slot `set_result_label`; viewer: "Ground truth" column split into **Actor** (who solved:
  Unknown/Bot/Manual) and **Result** (what happened: Unknown/Passed/Failed/Mixed) — wording fix actor≠outcome.
  Comparison pane heading shows `actor · result · method · outcome`.

## D4 — coverage ramp (ratchet, waves)

Order by uncovered lines (measured 2026-09-19). Each wave: tests first (RULE 8 — every test fails if its
target function is deleted), real code under test, fakes for CDP/Qt.

* D4.0 delete dead B2 leftovers (above) — denominator −523 uncovered stmts, reported absolutely.
* D4.1 services: `multi_page_dispatcher`, `watcher`, `single_job_runner`, `run_state`, `batch_orchestrator`,
  `cooldown_service`, `captcha/recovery|service` gaps.
* D4.2 browser: `cdp_client` (fake-WS connect/tabs/probe), `cdp_arena`, `output_wait`, `visual_click`,
  `dom_highlight`, `output_state`, `tab_matcher`, `cdp_events`.
* D4.3 core + persistence: fail-closed invariants I-11/I-13/I-17/I-22 negative matrices
  (`persistence`, `layout_service`, `undo_service`, `action_blocks`, `scanner`, `naming`, `models`, `state_machine`).
* D4.4 ui: panel slot contracts via qt_compat headless shim where importable without Qt.
* D4.5 JS lane: `c8` instrumentation over `node --test tests/js/*`, number recorded.

## D6 — close the gate hole

* **Ratchet (baseline v2):** per-symbol metrics (`functions: {name: {loc, params, cc, cognitive, nesting}}`,
  `classes: {name: {loc, methods}}`) + file maxima + per-file coverage %. Gate fails when any touched
  baseline file grows on any metric (symbol new-to-baseline with a hard-limit breach → fail; existing
  symbol worsening → fail; file coverage below baseline → fail). `--allow-legacy` suppresses only
  pre-existing values. `tools/baseline_update.py` regenerates v2 from a clean tree.
* **Changed files:** `git merge-base origin/main HEAD` → diff (worktree-safe).
* **JS gate:** acorn (node) — fail: func >30 LOC, >4 params, nesting >4, rough CC >10; warn: file >300 lines.
  Grandfathered via baseline `js` section (per-symbol).
* **Lanes in pre_push_check.sh** (<3 min): fast pytest `-m "not slow and not e2e"` under coverage,
  coverage.json + totals+per-file ratchet, `node --test tests/js/*`, vulture @90 (new findings only,
  `tools/vulture_whitelist.py`), jscpd dup-% vs baseline.
* **Negative tests** (`tests/test_quality_gate.py`, subprocess against `tmp_path` fixtures, `--root` flag):
  31-LOC func in baseline file fails; 40-LOC JS func fails; per-file coverage drop fails.

## D5 — mutation

`mutmut` scoped to `app/services/**` + `app/core/**` + `app/browser/cdp_*.py` (correctness-critical),
parallel, per-test time limit. Score + survivor triage (missing assertion / equivalent / dead) in the report.

## D7 — recheck

`metrics-report-2026-09-19.md` (Before→After per metric, absolute covered statements alongside %),
`SYSTEM_OF_RECORD.md` §7/§8/§9 updates, `docs/README.md` map, RULE 16 + RULE 18 audit of every touched file.

## Rejected dishonest reductions

* No `foo_part1`/`foo_part2` splits; helpers named by domain responsibility only (`build_milestone`,
  `_copy_evidence`, `cohort`, `close`).
* No `**kwargs` to dodge param caps (milestone builder takes `outcome` + `offset_ms` only).
* Deleting the 4 dead modules is recorded with absolute statement counts, not presented as coverage gain.
* Milestone whitelist **drops** identity/token data rather than trying to redact it in place — the
  whitelist itself is the I-29/I-32 guarantee, plus `assert_token_free` as backstop.

## Reconciliation onto the newer cycle tip (2026-09-19, R3)

D's branch was cut from **A's tip**, so the cycle branch had to be rebased onto the
user's newer work (`arena/01a0bab4` @ `1506813`, merge of `main`). Nothing of that
newer contract was reverted; the union was rebuilt deliverable by deliverable:

* **Labels.** `set_labels(session_id, actor, result)` (newer) is the one write path;
  the actor-only `set_label` stays on the manager for schema-v1 callers, D's
  `set_result_label` name is gone. The recordings *bridge* exposes only `set_labels`
  (its Python-only `set_label` alias was dropped to stay inside the methods ratchet)
  and the viewer's Actor/Result selects are wired to it — the newer panel rendered
  the two selects but never bound them, so labels were uneditable.
* **Comparison.** `RecordingManager.compare_sessions(left, right)` now exists
  (`RecordingComparison.compare` over `get_session` read models). Every branch's
  `compare_sessions` QWebChannel slot previously called a manager method that no
  branch defined, so the comparison pane could only ever return an error envelope.
* **Probes.** The captcha page agents stay with the package that owns their contract
  (`captcha_recording/probes.py` + `recording_js/{install,drain,snapshot,stop}.js`,
  drain → `{ok, changes, dropped, pending}`); `app/browser/recording_probes.py`
  (`{ok, mutations, requests}`) serves the newer `services/recording` package. The
  recorder keeps `.probes` — its drain contract is the one its manifests describe.
* **Dead-generation revival** landed in full on the union tree
  (`page_errors.match_dead_generation`, `cdp_arena/output.py`
  `_convert_dead_generation`/`_poll_diag_or_revive`/`_rebaseline_errors`,
  `OutputMixin._poll_output_diag`), matching
  `docs/archive/2026-09-18-dead-generation-toast-revival/design.md`.
* **Dead UI removed.** `app/ui/web/js/panels/recordings.js` (main's duplicate
  recordings panel: no script tag, none of its element ids exist in `index.html`)
  was deleted; window #15 ships `captcha-recordings.js` +
  `captcha-recording-comparison.js`. `SYSTEM_OF_RECORD.md` was updated for the
  `captcha_records` → `recordings` window rename and the independent label axes.

RULE 18 consolidation that came out of the rebase (all inside their baselines):

| File | Before → after |
|---|---|
| `captcha_recording/recorder.py` | class 152 → **115** LOC; internals as module functions |
| `ui/services/captcha_recordings_bridge.py` | class 84 → **60** LOC (`_reply` envelope, 10 slots) |
| `captcha_recording/manager.py` | 91 → **89** LOC, 15 methods; `compare_sessions` added, `_drop` → module helper |
| `browser/cdp_arena/output.py` | `wait_for_new_output` 26 → **10** LOC (`_prepare_wait`/`_run_wait`), file max CC/cognitive back to 4 |
| `services/captcha/recovery.py` | max func 17 → **15**, class 14 → **13**, CC 8 → **6** |
| `services/captcha/signals.py` | class 45 → **44**, max func 17 → **16** |

Lanes after the reconciliation: pytest **1404 passed / 4 skipped**,
`npm run test:js` **141/141**, gate `--allow-legacy --coverage-ratchet`
**0 fails / 0 warns**, coverage **line 85.08 / branch 85** (floor 84.46/80.27).
