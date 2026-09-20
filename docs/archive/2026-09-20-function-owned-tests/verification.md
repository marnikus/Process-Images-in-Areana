# Function-owned test rebuild — verification

2026-09-20 · behavior baseline `19a96c9` · ownership RED `91d82b1`.

## Delivered structure

- **46 Python function/method owners**, 8 unit modules, **161 parameter cases**.
  Each definition declares exactly one real production AST symbol with
  `pytest.mark.target`; duplicate/missing owners and hidden definitions fail.
- **32 JavaScript method owners**, 4 unit modules. All interval and live-debug
  store/render/actions/facade methods, plus the URL row renderer, have an explicit
  `test('Object.method', ...)`. Data-driven subtests are not old-body dispatchers.
  The focused JS command reports **113 passes**: 32 owners, 79 scenario subtests,
  and 2 structural contracts. Node includes parents in its total.
- `tests/live_chain_manifest.json` accounts for **130 original Python definitions**:
  **37 rebuilt** under canonical owners; **93 retained unchanged by function AST**
  in 17 integration/contract modules. The 3 original JS suites retain identical
  module ASTs. Structural tests also verify default npm registration.
- Integration classification was audited: actual Bridge/persistence/undo,
  scheduler/loop, signal/boot/DOM and cross-module contracts remain there. Simple
  policy/clock/value cases were rebuilt, not relabeled to evade uniqueness.
- Original root paths for canonical units are retained where possible. Integration
  files use a prefix family at the same depth so `parents[1]` root resolution is
  unchanged. Unused split helpers/imports and stale budget headers were removed.
- Legacy unrelated suites, S0 equivalence, pinned tests and separate L-9 transport
  tests are unchanged. See `tests/LIVE_CHAIN.md` for scope and maintenance commands.

## RED and regression honesty

The committed RED failed because the old layout had no ownership/legacy-case
manifest. It demonstrates the missing structure, **not a new production behavior
failure**. The rebuilt behavior scenarios are equivalence tests. No production
repair was needed, and no historical S6/S7 RED exception is retroactively erased.

Manual case review retained active-provider reads, OFF/ON scope and positive
controls, busy-row precedence, miss progression/reappearance, clock advancement,
disconnected-vs-registered tab ids, queue recovery, failure and cancellation.
The async settle table also covers error/cancel without charging completed pause
seconds. No target function is mocked by its own unit test.

## Executed checks

| Check | Result |
|---|---|
| Focused Python owners | **161 passed** |
| Focused retained Python integrations | **101 passed** |
| Final ownership + S10 documentation contracts | **6 passed** |
| Focused JS owners + structural contracts | **113 passed**, 0 failed |
| Full pytest, plain | **1890 passed, 4 skipped, 5 warnings**, 197.63 s |
| Full pytest, fresh branch coverage | **1890 passed, 4 skipped, 5 warnings**, 198.36 s |
| Default npm lane | **386 passed**, 51 suites, 0 failed |
| Full pre-push workflow, `VERIFY_QUALITY_BASE=2bbf9ab` | Exit 0; syntax/undefined names, both suites, fresh coverage, quality, duplication and metrics ran |
| Actual S0–S10 production diff quality gate | **36 Python + 12 JS files; 0 metric failures, 0 metric warnings** |
| Follow-up gate vs S10 (`19a96c9`) | No app diff, so tool loudly falls back to all **162 Python files; 0 metric failures/warnings**; this is not claimed as a changed-production lane |
| Final strengthened ownership guards | Python **1 passed**, focused JS **113 passed** after full workflow |
| `git diff --check` | Clean |

Coverage comparison uses statement and branch numerators, not coverage.py's
combined line+branch `percent_covered` field:

| Metric | S10 | Rebuilt tests | Change (percentage points) |
|---|---:|---:|---:|
| Statements | 88.6218980190% | **88.6719588071%** (12399 / 13983) | +0.0500607881 |
| Branches | 84.7624922887% | **84.8241826033%** (2750 / 3242) | +0.0616903146 |

Stored floors remain unchanged. No `--record-baseline` was used.
Duplication remains **1.0786407504528128%**, 23 groups / 399 lines.

## RULE 16 / RULE 18 final review

All rules were reread, including 16 and 18. This is test/config/documentation-only:
there are **zero changed production symbols**, so production LOC, CC, cognitive,
nesting, parameter, class/method and module-size budgets cannot grow. The real
whole-chain gate was nevertheless rerun, not replaced with an empty diff claim.
Tests are exempt from production size caps; the canonical files are split by
subject, not by quota or a monolithic callback dispatcher. The machine-readable
ledger is deliberately exhaustive; detail lives here rather than in current docs.
No new override, compatibility wrapper, bridge slot, signal or runtime dependency.

Byte comparison against S10 checked **287 frozen files**: **269 application files**,
**12 golden JSON files**, the 3 pinned bridge-slot/metaobject/cooldown test files,
both quality/duplication baselines and the npm lockfile. All are identical.

Known limitations are unchanged: five existing unawaited-coroutine warnings and
four existing Vulture unused-import findings (the pre-push script reports those
as a warning, not a clean Vulture result). Four pytest skips remain. Real Chrome
manual acceptance and the private saved-page captcha lane were not rerun or
claimed as passing; this test-only rebuild does not resolve those limitations.
