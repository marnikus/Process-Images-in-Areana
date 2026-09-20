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

### Final RULE 12 review: interval history RED

The full gate passed, but checking the plan's claim that the new setting uses the
existing settings history found an omitted field: interval lives in session
config, while `push_settings_undo` only serializes AppState. Add a real first-edit
undo/redo test (starting from a nondefault 7000 ms value) plus history remember /
legacy-entry compatibility tests **before** repair. The proposed fix snapshots
the interval before/after its edit on the existing `settings` timeline, restores
it in existing remember/apply handlers, and shares clamp/persist/wake in the
reconciler's cadence owner. No new history kind, slot or JS writer. Old entries
without the field must leave it alone. Existing generic history semantics are
not rewritten in this bounded fix.

Pre-edit budgets: app_settings maxfunc17/CC7/class117/method10; undo_entries
maxfunc17/CC7/cognitive7. Shared setter target <=10 LOC/CC<=3/2 parameters;
existing callers must not raise file maxima. No baseline or override change.

History RED `490fd43`: **2 failed / 7 passed**, before code changes. Shared
`reconcile.update_interval` now owns clamp/persist/wake/log; the control captures
its pre-edit settings snapshot and its existing post-edit snapshot includes the
interval. Remember/apply restore only if the field exists, preserving older
history entries. First edit from 7000→9000, undo→7000, redo→9000, progress pushes
and three wakes are asserted through the real Bridge. Focused suite **52 passed**.
This is the fourth bounded integration repair, not a new control or history kind.

## Stage ledger — quality-budget §8.0, audited rather than retroactively checked

Commit history was inspected with `git diff-tree --name-only` for every GREEN.
The final cumulative tests/gate are green; this does not assert that every
historical stage's original RED was valid or that its gates were replayed here.

| Stage | RED / delivered commit | Current-doc audit / present evidence |
|---|---|---|
| S0 | `2bbf9ab` | Bootstrap/equivalence recorded: 1614 Python passed / 11 skipped, 240 JS passed; cognitive baseline repair was explicitly justified there |
| S1 | `c96c4ff` / `0beec31` | SoR updated with code; real scheduling seam tests; L-1/L-6 closed |
| S2 | `cf467e0` / `f5c6f3a` | Rules + SoR with code; OFF counted with ON positive controls; I-48 |
| L-9 | `b599d25` / `8aef133` | Separate transport fail-fast correction; not silently assigned a numbered stage |
| S3 | `9fcffec` / `07d9404` | Rules + SoR with code; clock/wait-cap/output tests, I-52 |
| S4 | `f223484` / `89b90dc` | SoR with code; queue/bus/reset tests, I-49/I-54 |
| S5 | `32bcd6b` / `f171ba7` | SoR with code; supervisor/stop/writer tests + goldens, I-47 |
| S6 | `c412f87` / `e6ce8e0` | **Exception:** placeholders were not RED; no current-doc file changed in GREEN. S10 replaces checks, repairs planner/dedupe/interval-history integration and documents I-50 now |
| S7 | `237a055` / `a637bc2` | **Exception:** weak source/undo tests and no current-doc update in GREEN. S9 added I-53; S10 executes flag/commit/history conversion and real DOM, fixes disconnected receiver membership |
| S8 | `fa96aac` / `747e23c` | SoR with code; strengthened tests replayed against S7 per `s8-verification.md`; I-51, L-5/L-8 closed |
| S9 | `2adaa19`, `3487604` / `0debf77` | SoR/QUALITY/README with code; real signal/DOM/clock tests; timing and idle-publication amendments recorded in `s9-verification.md` |
| S10 | `1682da6`, `490fd43` / this series | Reproduced regression RED, equivalence tests clearly labeled, bounded repairs + docs + full fresh gates; no S11 created |

Every stage's final applicable slot/golden/frozen-JS contract is rechecked in the
cumulative gate. Historical RULE 17 noncompliance in S6/S7 is **not erasable**;
updating the current truth now is correction, not proof of on-time documentation.
The application was not launched against the user's real Chrome/desktop at every
stage here, so §8.0's manual shippability checkbox is not claimed.

## Final measurements — RULE 16 / RULE 18

Final full command:
`VERIFY_QUALITY_BASE=0debf77 bash tools/pre_push_check.sh` → **exit 0**.
Whole-chain command after the history repair:
`.venv/bin/python tools/verify_quality.py --changed --base 2bbf9ab --allow-legacy --coverage-ratchet`
→ **exit 0, 36 Python + 12 JS files, 0 failures / 0 warnings**.

- Plain pytest: **1775 passed / 4 skipped / 5 warnings**, 194.60 s.
- Fresh coverage pytest: **1775 passed / 4 skipped / 5 warnings**, 200.77 s.
- Default JS: **273 passed**, **51 suites**, 0 failed; **33 test files** listed.
  Includes title-fit's 10 cases (also explicitly exercised during the audit).
- Coverage: **88.621898% statements / 84.762492% branches**; stored S0 floors
  **86.91 / 83.24** unchanged. No uncovered new function.
- jscpd: **1.078641%**, **23 groups / 399 lines**, baseline **1.240%** unchanged.
- Syntax/hygiene pass. Optional pyflakes is absent, so that check is skipped.
  Four Vulture findings remain the same unused imports in bridge/browser_tabs;
  this is not described as a clean Vulture result. Pytest's 5 warnings remain
  the existing unawaited test-coroutine warnings.
- `npm run test:js:saved-page`: **0 passed, 4 skipped**. Missing private HTML
  fixtures are explained, not replaced by fake evidence or committed to Git.

| S10 edited Python file | File LOC | Max func LOC | Max gate CC | Combined coverage |
|---|---:|---:|---:|---:|
| live/reconcile.py | 231 | 32 (existing override) | 11 (existing override) | 84.26% |
| live/url_policy.py | 158 | 23 | 20 (existing override) | 97.16% |
| ui/panels/url_queue.py | 254 | 14 | 6 | 99.11% |
| ui/panels/app_settings.py | 373 | 17 | 7 | 76.43% |
| ui/services/undo_entries.py | 413 | 17 | 7 | 79.02% |

These legacy per-file coverage values satisfy their existing floors; do not
confuse them with the overall 80/75 requirement. New functions are only
`connected_tab_ids` (6 LOC, radon CC4, 1 parameter) and `update_interval`
(6 LOC, radon CC1, 2 parameters), both behavior-tested. No new class, override,
parameter bag, or helper that merely conceals a decision. The oversized settings
and undo files retain their named slot/kind responsibilities and existing
ideal-size explanations; shared cadence mutation lives with the loop owner.
Standalone radon still reports the existing `reconcile_once` CC12 and `_row_reason`
CC20; the gate's existing exceptions are retained, not newly waived in S10.

| Module, direct Python files including __init__ | S0 | Final | RULE 18 decision |
|---|---:|---:|---|
| core | 15 | 17 | Small clock and catalog have distinct domain ownership; S8 extraction rationale retained |
| services/live | 0 | 7 | Cohesive bus/feed/supervisor/reconcile/policy/view package |
| services/captcha | 6 | 7 | Scope/cap policy has one owner |
| browser | 24 | 24 | Existing CDP/controller split; no module growth in this chain |
| ui/panels | 16 | 16 | Frozen slot mixins retained |
| ui/services | 9 | 10 | S9 read-only serialization leaf, no dependency inversion |

### Frozen JS ledger, S0 → final (lines / functions)

| File | S0 | Final |
|---|---|---|
| arena-app.js | 176 / 28 | 176 / 28 |
| panels/cdp.js | 135 / 55 | 134 / 54 |
| url-list/render.js | 74 / 12 | 74 / 12 |
| sash-core/constants.js | 25 / 3 | 25 / 3 |
| sash-core/tree.js | 106 / 21 | 106 / 21 |
| sash-grid-windows/store.js | 122 / 19 | 122 / 19 |
| sash-grid.js | 123 / 10 | 114 / 10 |

The remaining frozen URL files, settings.js and arena-app/listeners.js are
byte-identical; listeners is **194 / 54**, not the stale plan's 168 / 51.
S10 changes no production JS. S9's planned expansion of the S8 debug shell is
an explicit stage interface, not an unrecorded frozen-predecessor edit.

## Final acceptance — quality-budget §8.1 disposition

- [x] Bootstrap evidence, current default JS lane and fresh Python coverage run.
- [x] Both actual diff bases gated (not fallback/empty); global/per-file floors held.
- [x] Existing 135-slot surface and **24 signal declarations** unchanged from S0.
- [x] Frozen bridge/metaobject/cooldown test files, PagePool, settings JS, listeners
  and all **12 golden JSON files** byte-identical (19 files checked).
- [x] Output wait loop AST unchanged; its containing module changed intentionally
  in S3 for WaitSpec's pause field (not claimed byte-identical as a whole).
- [x] 16-window contract, migration and title fit; real index/DOM boot in S8/S9 tests.
- [x] Pause/cap/OFF positive-control tests and supervisor goldens in full pytest.
- [x] No baseline re-record since the justified S0 tooling repair; no new override.
- [x] L-7 adopted-or-explained: title-fit default; private-page suite explicitly
  opt-in and skipped here, with the reason in current QUALITY_RECHECK.
- [x] RULE 16/18 reread; measured budgets, scope amendments and current docs in
  the corresponding S10 implementation commits; original plans retained verbatim.
- [!] Historical same-stage docs and RED honesty were deficient in S6/S7; this
  ledger records the exception rather than checking their old boxes as passed.
- [ ] Real-Chrome manual acceptance **not run**: interval change without restart;
  Watcher ON captcha clears and timeout pause; ON without key honest wait; OFF
  ordinary timeout; unsolved captcha cap/failure/cooldown; Reset All uptake;
  real worker/tab add/remove; live receiver icon. No authorized logged-in session
  or desktop Qt display was used. Automated seam tests do not stand in for this.

Baseline decision: **keep it**. All final changes pass the existing ratchets;
recording new/lower maxima is optional future maintenance, not a prerequisite
or a way to create feature headroom. No credential/runtime data or generated
coverage/log/metric artifact is added to Git.
