# Area D — Verification & evidence (coverage, mutation, gate hardening, captcha recordings)

**Problem fixed:** P5 (High), P6 (High), plus the tooling gaps in §7 of the audit.
**Branch (recommended):** `arena/quality-d-verification` — runs in parallel with Area C; **D1 can start immediately**.
**Owns (writes):** `tests/**` (new files; existing files only when this area created them),
`tools/**`, `app/services/captcha_recording/**`, `app/ui/services/captcha_recordings_bridge.py`.
**Must not touch:** `app/ui/bridge.py` (Area A owns the slots it calls),
`app/ui/web/js/panels/captcha-recordings*.js` (Area C owns JS),
`app/services/job_runner.py` (deleted by Area B).

## Why

* **Coverage is the gate that decides whether the refactor is safe.** Line 43.4%,
  branch 32.0% against 80%/75%; test∶code 1∶0.38; mutation unmeasured. 78% of
  uncovered lines sit in 8 files — 6 of them are being refactored in Areas A/B/C,
  so this area's work is the safety net for all of them.
* **The gate has a hole.** `tools/verify_quality.py --allow-legacy` downgrades
  *every* breach in a file listed in `tools/quality_baseline.json` to a warning,
  so new oversized code inside `bridge.py` or `cdp_client.py` passes the pre-push
  hook. `coverage.json` is not produced by the hook, and vulture/duplication/JS
  are never run at all.
* **One live correctness bug (report P9).** The recording pipeline's thread
  handoff can kill the recorder worker and silently drop the evidence the last
  six report rounds depended on. Reports F-B/F-C additionally need milestones
  and independent outcome labels before any bot failure can be attributed.

## Steps

### D1 — Fix the silent evidence loss (report P9) — live bug, do first

`app/services/captcha_recording/network.py`: `on_event` runs on the websocket
receive thread, `drain()` runs on the bridge loop, and
`while not empty(): get_nowait()` can raise `QueueEmpty` when a put lands between
the check and the get → the recorder task dies, the session loses its network
evidence, and nothing is surfaced.

Fix: replace the check-then-get loop with one of
(a) a `threading.Lock`-protected `collections.deque` with a `popleft()` in a
`try/except IndexError`, or (b) `loop.call_soon_threadsafe(...)` scheduling onto
the recorder loop. Add a `dropped_events` counter to the manifest (replacing
silent loss with a visible number) and a worker-thread regression test that
hammers `on_event` while `drain` runs (fails on the current code).

* Verify: the new regression test fails before, passes after; recorder/reading
  tests green; `manifest.dropped_events == 0` in the normal path test.
* Metric: `network.py` and `recorder.py` coverage ≥90%; one documented defect
  closed (bug density proxy 0.79 → 0.74 / 1,000 LOC).

### D2 — Persist bounded semantic milestones (report F-B, P6)

Write the token-free milestone set from `SolveOutcome` (already produced by
round-10 `CAPTCHA_SOLVE`) into the recording: task-created offset + task id,
poll count, token-ready offset, page/challenge identity at detect vs. token,
response-field count/scope pre/post injection, callback source + result, continue
result, first page-error offset, dialog-clear offset, acceptance-candidate
offset, final job result joined by `eid`. Bounded sizes, no raw tokens
(I-29/I-32 stay intact — add an assertion test that no token string can be written).

* Verify: golden test on a synthetic session; reader/viewer surfaces the
  milestones (`captcha_recording/reader.py`); size bounds asserted.
* Why it matters: this is the change that turns RC-1…RC-4 from "candidate" into
  "proven or refuted" from a user's own recording.

### D3 — Independent ground-truth labels (report F-C, P7)

Add `result_label: unknown|passed|failed` next to the actor label, allow `mixed`,
store label history with timestamps, correct the viewer wording (actor ≠ outcome),
and exclude unknown/mixed from pure cohort statistics.

* Verify: model/store tests; viewer wording snapshot test; cohort builder test
  with mixed/unknown rows.

### D4 — Coverage ramp with a ratchet

Order the work by uncovered lines per file (the audit's §4 table):

| Wave | Files | New tests | Expected line coverage |
|---|---|---|---:|
| D4.1 | `app/services/single_job_runner.py`, `batch_orchestrator.py` (from A), `multi_page_dispatcher.py`, `watcher.py` | handler/decision tests on fakes | 46% → 55% |
| D4.2 | `app/browser/cdp_client.py`, `cdp_arena.py`, `output_wait.py`, `dom_highlight.py`, `visual_click.py` | fake-CDP unit tests (extend `tests/fakes/fake_cdp.py`) | → 63% |
| D4.3 | `app/ui/bridge.py` slot contracts (post-A5) | one test per slot group: happy path + guard; signal emission asserted | → 70% |
| D4.4 | `app/core/**`, `app/persistence/**`, `app/services/captcha*` | negative matrices for the fail-closed invariants (I-11, I-13, I-17, I-22) | → 80% line / ≥75% branch |
| D4.5 | JS lane | `c8` instrumentation + jsdom harness for panels | JS number exists, ≥70% start |

Rule (RULE 8): every new test executes the real function, not a re-implementation;
every extracted helper in Areas A/B/C gets a test that fails if the helper is
deleted. Test∶code ratio target for the round: 1∶0.8 minimum, 1∶1 goal.

### D5 — Mutation testing on the critical core

Install and wire one runner (`mutmut` or `cosmic-ray`), scope it to
`app/services/**` + `app/core/**` + `app/browser/cdp*` (the correctness-critical
paths), record the score, triage survivors into (a) missing assertion,
(b) equivalent mutant, (c) dead code to delete. Target ≥70% (your threshold);
the Old App baseline was 99.4% on the modules it covered, so treat 70% as the
floor for the first round, not the goal.

* Verify: mutation score stored in the round's metrics report; survivor list
  with a disposition per mutant; runner documented in `tools/`.

### D6 — Close the gate hole (Round 0 hardening lives here)

1. **Baseline ratchet:** `tools/quality_baseline.json` gains per-metric maxima
   per file (func LOC, class LOC, methods, CC, cognitive, nesting, coverage,
   params). The gate fails when *any* metric increases for a touched file, even
   when the file is in the baseline; the `--allow-legacy` flag may only suppress
   pre-existing values, never new growth.
2. **JS gate:** acorn-based checker with the RULE 16 fail lines (func ≤30 LOC,
   params ≤4, nesting ≤4, rough CC ≤10, file ≤300 lines preferred) and its own
   baseline entry set.
3. **Lanes in `tools/pre_push_check.sh`:** `pytest -m "not slow and not e2e"`
   (fast), `coverage run --branch` + `coverage.json`, `node --test tests/js/*`,
   `vulture app --min-confidence 90`, jscpd duplication delta vs. baseline.
4. **Changed-file detection** uses the merge-base with `origin/main` (not
   `origin/main...HEAD` only) so area worktrees are gated correctly.

* Verify: three negative tests — (i) adding a 31-LOC function to `bridge.py`
  fails; (ii) adding a 40-LOC JS function fails; (iii) removing a test that
  drops coverage below the recorded per-file value fails.

### D7 — Round recheck and report

Run the final RULE 16 + RULE 18 audit, produce
`metrics-report-2026-09-2X.md` in the same shape as
`metrics-baseline-2026-09-18.md` (with a Before → After column per metric), and
add the "quality gates" row updates to `docs/current/SYSTEM_OF_RECORD.md` §9.

## Acceptance criteria (area exit)

* [ ] line coverage ≥80%, branch ≥75%, recorded per file with no file below 60% except generated/`__main__`
* [ ] mutation score ≥70% on the scoped modules, survivors triaged
* [ ] test∶code ratio ≥1∶0.8 (Python), JS lane instrumented with a recorded number
* [ ] `tools/verify_quality.py` fails on: new oversized Python, new oversized JS, coverage regression, new vulture @90 finding, new duplication group
* [ ] P9 regression test exists and fails on the pre-fix code
* [ ] F-B milestones + F-C labels implemented with token-free assertions (I-29/I-32 intact)
* [ ] `bash tools/pre_push_check.sh` runs fast lane + JS lane + coverage + vulture + duplication in < 3 minutes locally

## Risks and rollback

| Risk | Mitigation |
|---|---|
| Coverage chasing (tests that assert nothing) | RULE 8 review: each test must fail when its target function is deleted; mutation score is the anti-gaming check |
| Coverage denominator shrinking by deletion looks like progress | report both absolute covered statements and percentage; Areas A/B report the delta they cause (recorded in this folder) |
| Corpus/large JSON in tests | use `tmp_path` fixtures (already the conftest pattern) and synthetic sessions; never commit recordings under `config/` (git-ignored) |
| Mutation run time on a big tree | scope to the correctness-critical modules and run it as a nightly/manual lane, not on every push |
| Overlap with Area A on `bridge.py` tests | bridge slot-contract tests land after A5; until then D covers services/browser only |
