# Quality re-check — 2026-09-20, S0–S10 consolidation

Current verification summary for Dynamic URLs & Worker Debug. Detailed evidence:
`docs/archive/2026-09-20-dynamic-urls-and-worker-debug/s10-verification.md`.
Prior snapshots retained verbatim (including their historical baseline decisions):
`docs/archive/2026-09-20-dynamic-urls-and-worker-debug/quality-history-before-s10.md`.

## Delivered and audited

- S1 pool join schedules through the real seam; S2 Watcher OFF is zero activity.
- S3 generation pause and captcha wait share the existing bounded cap.
- S4 queue funnel/wake/eligibility and resets that re-queue; S5 always-live run.
- S6 Python-owned URL reconciliation and one interval writer in the URL List;
  S7 stored receiver flag; S8 catalog/grid v6 and rescued pool markup.
- S9 worker/queue detail, read-only cadence and labeled last-settled pause evidence.
- S10 replaces S6/S7 placeholder checks with executable tests and repairs four
  reproduced integration defects: model/dict planner boundary, dedupe-only commit,
  connected (not merely registered) receiver ids, and interval settings history. This bounded production
  repair is documented as an amendment to the consolidation-only plan.

## Final results

| Lane | Result |
|---|---|
| Full pytest, plain + fresh coverage | **1775 passed, 4 skipped, 5 warnings** in each run |
| Default JS suite | **273 passed**, 51 suites, no failures (33 test files) |
| S10 changed gate, base S9 | **5 Python files**, 0 failures / 0 warnings |
| Whole-chain gate, base S0 | **36 Python + 12 JS files**, 0 failures / 0 warnings |
| Fresh coverage | **88.62% statements / 84.76% branches** |
| Duplication | **1.079%**, 23 groups / 399 lines; no baseline change |
| Private saved-page suite | **0 passed / 4 skipped**; not verification |

## Gate commands and contracts

```sh
VERIFY_QUALITY_BASE=0debf77 bash tools/pre_push_check.sh
.venv/bin/python tools/verify_quality.py --changed --base 2bbf9ab --allow-legacy --coverage-ratchet
npm run test:js
node --test tests/js/test_title_fit.mjs
```

The first base is S9, the second is S0 (whole chain). Fresh coverage is required;
no stale-coverage or empty changed-diff pass counts as verification. Final results
are recorded with these exact commands in the S10 evidence.

- 135 bridge slots, no new signals; frozen bridge/metaobject/cooldown tests unchanged.
- 16 windows; v5 layouts migrate to v6 and all four JS layouts preserve the panel.
- 12 golden JSONs remain unchanged; OFF silence has armed positive controls.
- Baseline **not re-recorded**: no headroom required for S10. Existing S0 floors
  remain **86.91% statements / 83.24% branches**, duplication <=1.240%.
- No new overrides. Existing S6 decision-table/reconcile overrides are recorded
  exceptions, not evidence that every existing symbol meets the new-code limits.
- Four pre-existing Vulture import findings remain in bridge/browser_tabs.
  Real Qt metaobject checks may skip without PySide6; report skips separately.

## L-7 test adoption and unavailable evidence

`test_title_fit.mjs` passed explicitly and is now part of `npm run test:js`.
`test_captcha_saved_page.mjs` is **not** treated as a green evidence suite here:
its four tests skip without private HTML fixtures under ignored `arena webpages/`.
Those dumps can contain account information and are not restored to Git.
Run it deliberately where the authorized local captures exist:

```sh
npm run test:js:saved-page
```

This explicit command and explanation close the orphan-discovery issue; they do
not close saved-page verification. Existing synthetic/real-DOM captcha tests
still run in the normal suite. A skip must never be reported as a passing probe.

## Acceptance limitations and historical exceptions

No authorized logged-in Chrome session or desktop Qt display was exercised here.
The plan's eight manual acceptance scenarios remain **not run**, including a real
captcha pause/clear/cap, live interval edit, reset uptake, tab add/remove and ⊘.
Automated loop/model/jsdom tests cover their software seams, not real-site success.

S6/S7 originally included placeholders and omitted their current-doc updates.
S10 repairs tests/docs now; it cannot retroactively make those stages valid TDD
or satisfy their original same-commit RULE 17 requirement. See the stage ledger.

RULE 16/18 decisions: new connected-id projection is a small policy leaf; module
counts and maxima are measured in the archive. No scope-padding, no dummy wrappers,
no baseline relaxation. Current quality context is short; historical detail stays
in the archive. Re-run all gates before a later push.
