# Area B — Dead legacy stack, duplication, selector centralisation

**Problem fixed:** P3 (High), P4 (High), P9 (Low-Medium, the Python part).
**Branch (recommended):** `arena/quality-b-dead-code` — **runs first**, it shrinks the map for Area A.
**Owns (writes):** `app/browser/controller.py`, `app/services/job_runner.py`,
`app/browser/output_detector.py`, `app/services/job_state_machine.py`,
`app/browser/site_adapter.py`, `tests/unit/test_output_detector.py`,
`tests/unit/test_job_state_machine.py`, `docs/current/DOM_SELECTORS.md`,
`app/persistence/{config_manager,preset_store,undo_store}.py` (step B5 only).
**Must not touch:** `app/ui/bridge.py`, `app/services/single_job_runner.py` (Area A), `tests/js/**`.

## Why this area is the cheapest win in the round

| Module | LOC | Coverage | Evidence it is dead | Fails |
|---|---:|---:|---|---:|
| `app/browser/controller.py` | 643 | **0.0%** | only importer is `job_runner.py`, which is itself unimported | 11 |
| `app/services/job_runner.py` | 332 | **0.0%** | zero importers in `app/`, `tests/`, `tools/` | 5 |
| `app/browser/output_detector.py` | 155 | 71.0% | imported **only** by `tests/unit/test_output_detector.py` — no production importer | 0 |
| `app/services/job_state_machine.py` | 109 | 100% | imported **only** by `tests/unit/test_job_state_machine.py` — no production importer | 0 |
| **Total** | **1,239** | — | 6.5% of the Python tree; 661 statements, 550 uncovered | **16** |

Deleting them: −16 fails (120 → 104), −661 statements in the coverage
denominator (of which 550 uncovered; the 111 covered ones leave with the two
test files), line coverage 43.4% → **45.0%** with no new test — and the
"two job runners" confusion disappears before Area A refactors the third one.
The MI floor itself stays at 0.00 because that is `bridge.py` (Area A removes it).

## Steps — biggest problem first

### B1 — Prove deadness with three independent detectors (no writes yet)

1. **Static import graph** over `app/` + `tests/` + `tools/` (script in appendix §A.6):
   zero importers.
2. **Symbol reference scan**: `JobRunner`, `BrowserController`, `can_job_transition`,
   `next_job_status_on_success`, `decide_ready`, `is_job_id_match` — no reference
   outside their own files and their tests.
3. **Runtime evidence**: coverage 0.0% after the full 444-test suite; no
   `importlib`/string import of these module paths anywhere (grep for
   `"controller"`, `"job_runner"`, `"output_detector"` in `app/`, especially
   `bridge.py` string imports).

Output: a table in the PR description listing module → detector → result.
Any module failing one of the three stays and is re-scoped to Area C.

### B2 — Delete the dead modules and their tests (one commit)

Delete `controller.py`, `job_runner.py`, `output_detector.py`,
`job_state_machine.py` and their two test files. Two exceptions, decided *in*
this step by the rule "port only what the live pipeline needs, then delete":

* if `output_detector.decide_ready` / `flatten_diagnostics_pure` carry logic the
  live wait loop (`output_wait.py`, `output_state.py`) should share — port the
  predicate into `output_wait.py` **in the same commit**, with its test moved
  too (test ownership moves with the logic);
* `job_state_machine.can_job_transition` / `next_job_status_on_success`: keep
  only if Area A's `batch_orchestrator` will use them; otherwise delete with the
  test. `app/core/state_machine.py` (still imported, covered) stays.

* Verify: `pytest -q` still 444-ish green (with −2 test files the count drops;
  record the new expected count in the PR), gate `--changed` 0 fails,
  `python -c "import app.ui.bridge"` imports clean.
* Metric delta: fails 120 → 104; app LOC −1,239; statements −661; coverage 43.4% → 45.0% line.

### B3 — Restore RULE 21: one selector source for the live path

Today `site_adapter.py` (316 LOC, primary + fallbacks, `tests/test_selector.py`)
has exactly one importer — the dead `controller.py` — while the live probes
(`cdp_arena.py`, `dom_highlight.py`, `output_probes.py`) hardcode selector
literals inside JavaScript payload strings. Choose **one**:

* **(preferred) Generate probe selectors from `site_adapter`**: probes receive
  their selector list as JSON/parameter instead of embedding literals; add
  `tests/test_selector_single_source.py` that parses the probe JS builders and
  fails if a selector string appears that is not declared in `site_adapter`.
* **(fallback) Delete `site_adapter.py`** and make `docs/current/DOM_SELECTORS.md`
  the reference, with a lint test that every literal selector is listed there.

Decision rule: if the generator can be done in ≤150 LOC without changing the
in-page contract, take it; otherwise take the fallback. Either way the outcome
is enforced by a test, not by convention.

* Verify: selector tests green; a probe called with a *changed* selector list
  propagates the change (test proves the single source).
* Metric delta: removes `site_adapter.py`'s 1 fail if the fallback is chosen;
  prevents the most frequent class of production change (selector drift) from
  needing edits in three JS strings.

### B4 — Unused imports and triaged vulture findings

Delete the 2 unused imports (`build_order_check_text` in `cdp_arena.py:19`,
`_is_cooling` in `page_status.py:10`). Triage the 30 vulture @60% candidates in
a table (keep/delete, with one-line evidence each — several are dynamically
reachable: `clear_highlights`, `take_screenshot` may be called from JS payloads,
so they need a payload grep before deletion). Delete only what a grep across
`app/`, `tests/`, `app/ui/web/**` cannot find.

* Verify: `vulture app --min-confidence 60` output shrinks to only the
  documented keep-list; no test regression.

### B5 — Duplication removal (Python)

| Clone | Action |
|---|---|
| `persistence/config_manager.py:34` ↔ `preset_store.py:15` ↔ `undo_store.py:11` (27 lines ×2) | extract `app/persistence/json_store.py` (`load_json(path, default)`, `save_json_atomic(path, data)`) and use it from all three |
| `browser/output_probes.py` internal pairs (339/354, 686/743) | extract the repeated probe-body builder; parameters instead of copies |
| `ui/bridge.py:3167–3544` (undo clusters ×10) | **deferred to Area A5/A7** — that region is owned by A |

* Verify: jscpd re-run shows those groups gone; persistence tests green;
  `json_store.py` ≥90% covered.
* Metric delta: duplication 1.51% → ≈1.25% (the bridge clusters are counted in
  Area A's number).

### B6 — Baseline and docs

Regenerate `tools/quality_baseline.json` (integrator, single writer); remove the
deleted modules from `docs/current/SYSTEM_OF_RECORD.md` §7 (key modules) and
`docs/current/DOM_SELECTORS.md` if the fallback was chosen; add the archive
pointer for this round to `docs/README.md` (RULE 17).

## Acceptance criteria (area exit)

* [ ] the four dead modules are gone; `grep -rn "BrowserController\|JobRunner" app tests` returns nothing
* [ ] gate `--changed` 0 fails; global fails 120 → **104**
* [ ] app LOC −1,239; statements −661 (550 uncovered); line coverage ≥45%
* [ ] 0 unused imports (vulture @90%); every @60% candidate has a keep/delete line in the PR
* [ ] exactly one selector source on the live path, enforced by a test
* [ ] persistence duplication group gone; `json_store.py` ≥90% covered
* [ ] `docs/current/*` and `docs/README.md` consistent with the deletions

## Risks and rollback

| Risk | Mitigation |
|---|---|
| Something *is* reachable at runtime (string import, Qt dynamic call, JS payload) | three-detector rule in B1; the payload grep in B2/B4; coverage 0% across 444 tests |
| Deleting a test that also covered live code | check the test file's imports before deleting; move any assertion that covers a live module into that module's test file |
| `site_adapter` decision blocks later selector work | timebox B3 to one session; fallback option keeps the round moving |
| Rollback | one commit per module group; `git revert` restores the files with no data migration needed |
