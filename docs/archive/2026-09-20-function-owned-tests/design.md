# S0–S10 function-owned test rebuild

2026-09-20 · base `19a96c9` · user chose **exactly one unit-test definition
per production function/method**, with parameterized scenarios. Integration,
contract and golden regressions remain separate; they must not be deleted merely
to make unit counts match.

## Plan before edits (RULE 16/18)

- Scope: the chain-owned Python suites and its three JS suites, plus dedicated
  function units for the JS interval/debug modules. Pre-existing unrelated suites,
  pinned slot/metaobject/cooldown tests, L-9 transport tests and golden files stay
  unchanged. S0 is bootstrap/equivalence, not a new production-function suite.
- Keep one canonical Python test marked with its `module:qualified_function`
  target; use pytest parametrization, not a wrapper dispatching to renamed old
  test functions. One JS top-level registration per object method, with scenario
  subtests. Setup may use other real functions; assertions own one primary target.
- Unit scope covers the policy/value/projection/control functions; real Bridge,
  persistence, scheduler/loop, UI boot/signal and multi-module tests live in
  explicitly named integration files. Do NOT relabel pure duplicate unit tests
  as integration to evade uniqueness. Rebuild those cases under their owner.
- Record the old-to-new file/case map in a machine-readable manifest. Guard target
  uniqueness, actual production-symbol existence, collected unit definitions,
  integration registration and legacy case disposition. Retained integration
  test bodies must be identical; pure unit scenarios may be expanded.
- Production behavior and production files are frozen for this refactor. No
  quality-baseline recording, golden update, new bridge contract or API is needed.
  Thus production maxima are unchanged by construction; test/harness files are
  outside the size gate, but split by subject rather than enormous dispatcher.
- RED: structure guard rejects the old layout. GREEN: rebuild unit cases and
  separate integration files, repair current-doc/test-runner pointers, full pytest,
  npm, fresh branch coverage and whole-chain quality gate. Compare coverage to S10
  (88.621898% statements / 84.762492% branches), not just the older stored floors.

Workspace restored its Git index to the already-pushed session HEAD using a mixed
reset only after fetching that exact branch; no working files were overwritten.
The working tree matched `19a96c9` afterward. No branch switch or user edits lost.
