# S10 consolidation — final audit

2026-09-20 · base `0debf77` (S9). Only S10 remains in S0…S10; the request
for the next two steps is handled as (1) executable audit/closure and (2)
current-doc consolidation, full verification and push, not an invented S11.

## Before edits: findings and scope

- Several S6 tests import a function then `assert True`/`pass`; S7 includes
  source-string checks and an undo test that never calls undo. These are not
  historical RED evidence. Replace with real model/bridge/loop and jsdom tests;
  passing replacements are equivalence, not retroactively claimed RED.
- S10's documentation acceptance is currently RED: I-50 is absent, CDP row 11
  still promises JS 15-second scanning, the pipeline table names deleted
  `batch_orchestrator.run_batch`, README says plans-only. Add executable checks.
- L-7 explicit trial: title-fit **10 pass**; saved-page captcha **4 skipped**,
  because `arena webpages/` is private ignored runtime research (B13). Adopt
  title-fit; retain an explicit opt-in saved-page command with the limitation
  in current QUALITY_RECHECK. Do not commit private HTML or claim those skips pass.
- Baseline decision before work: retain existing `tools/quality_baseline.json`.
  No need to grant headroom or record new maxima for documentation/test closure.
  Use base `0debf77` for this step and S0 `2bbf9ab` for the whole chain.
- Test audit may expose actual integration regressions. Record failing cases
  before minimal repairs; no feature expansion, no new slots/signals, no frozen
  JS growth or changes to goldens/pinned tests. Do not double the tested seam.
- Initial code inspection suggests the live reconciler passes UrlRow objects
  into the dictionary-based `auto_connect.plan_auto_connect` and then swallows
  the shape error. A real row/claim test must establish this before any repair.
  A serialization boundary (dataclass -> dict) is the proposed correction,
  retaining planner ownership and decisions. Also check that dedupe-only changes
  persist. Reconcile budget: file224, maxfunc32/CC11 existing overrides, new
  functions <=20 LOC/CC<=10. No increased overrides or dummy helper extraction.

Final results, stage ledger and manual limitations follow after verification.

## Audit RED and bounded repair amendment

Before production edits: docs/runner checks **4 failed**; real reconcile tests
**6 failed / 5 passed**. Four run-state parameter cases and the manual slot fail
on the swallowed UrlRow/dict mismatch; dedupe removes a row in memory without
committing it. Receiver tests expose a third integration defect: `pooled_ids`
means *all registered ids*, not *connected ids*, so disconnected pages still
advertise themselves as receivers. Do not change `pooled_ids` (cooldown restore
needs its existing meaning). Add a read-only connected-id projection in the
receiver-policy owner and use it in both `_mark` and `commit_urls`' recompute.
Tests also pin the reconcile caller; this is a bounded correctness repair to
existing S6/S7 contracts, not an S10 feature. Thus strict "no production changes"
is amended based on reproduced failures, not used to wave through broken code.

Budget before repair: `url_policy` file150/maxfunc23/CC20/cognitive22 (existing
S6 decision-table overrides), `url_queue` file255/maxfunc14/CC6. New connected-id
projection target <=10 LOC/CC<=5/1 parameter, no new package or override. The
planner receives standard dataclass serialization; no duplicated planner rule.
Dedupe's removed count contributes to the existing commit condition. No other
planner/receiver decisions change. Remaining replacement tests: **22 Python and
7 real jsdom equivalence passes**, not claimed as new-feature RED.

## Repair and equivalence results (before full gate)

RED `1682da6`: 4 documentation/runner failures; 7 real reconcile failures and
1 receiver-commit failure, plus 27 Python and 7 jsdom equivalence passes. The
reconcile disconnect fixture now sets `is_connected=False` **after** add_page
(the real pool marks new additions connected); the commit-path RED already
set it after addition. This fixture correction is not a new production defect.

Minimal repairs: `asdict` serialization at the existing planner boundary;
`len(dropped)` in the existing commit condition; one `connected_tab_ids(pool)`
projection shared by both receiver writers. `pooled_ids` is unchanged. Targeted
real bridge/policy/cadence/boundary suite: **44 passed**. No JS production changes.

Current docs fix I-50 and rows 8/11/21, preserve existing S2–S5/S8–S9 contracts,
and name the actual supervisor/pass bodies and 135-slot surface. Long historical
quality snapshots moved verbatim to `quality-history-before-s10.md`; current
QUALITY_RECHECK is a concise summary with a pointer, per RULE 18.4. The original
design/tdd/quality-budget documents are unchanged historical records (RULE 17).
