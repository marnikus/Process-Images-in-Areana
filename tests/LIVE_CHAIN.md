# S0–S10 tests: one unit definition per function

This is the function-owned layout requested after S10. **One definition** does
not mean one input or one assertion: parametrized cases cover normal, boundary,
error, OFF/ON and cancellation paths. Integration tests deliberately retain
multiple scenario definitions because they exercise collaborating components.

## Unit owners

| Area | Canonical unit file | Ownership |
|---|---|---|
| S2/S3 captcha policy | `test_captcha_policy.py` | Scope/key/reason/cap helpers and WaitDeadline methods |
| S3 pause arithmetic | `test_pause_clock.py` | One test per PauseClock method |
| S3 browser adapters | `test_cdp_output_settle.py` | Timed settle and timeout text |
| S4 event bus | `test_live_bus.py` | LiveBus methods and accessor |
| S4 queue | `test_live_feed.py` | Eligibility, commit, recovery, assignment clearing |
| S6/S7/S10 URL policy | `test_url_policy.py` | Removal/misses/dedupe/memory/receiver functions |
| S6/S9 projections | `test_live_debug_functions.py` | Interval/clamp/cadence/head/count/live view |
| S8 catalog | `test_window_catalog_functions.py` | Default tree builder |
| S6/S7 JS | `js/test_functions_interval.mjs` | Every UrlInterval method + rowHtml |
| S9 JS | `js/test_functions_debug_{store,render,actions}.mjs` | Every debug store/render/actions/facade method |

Each Python unit definition has exactly one `@pytest.mark.target("module:qualname")`.
Each JS unit registration is named exactly `Object.method`. A constructor is a
method; lambdas/callbacks and dataclass-generated methods are not separate owners.

## Integration and contract lane

`test_integration_*.py` and `js/test_integration_*.mjs` keep the real Bridge,
persistence/undo, scheduler, live-loop, captcha flow, full-page boot/signals,
window migration, and documentation/registry checks. Pure duplicate unit cases
were rebuilt above, **not** renamed as integration to evade the one-owner rule.
S0's equivalence suite, the existing characterization files, pinned bridge-slot /
metaobject / cooldown tests, and separate L-9 tests are unchanged.

`live_chain_manifest.json` accounts for all 130 original Python test definitions
and all three original chain JS suites. For each removed unit definition it lists
its canonical replacement(s); retained integration bodies are checked against
S10 by AST. No old tests are hidden behind scenario callbacks or disabled.
There are 46 Python owners and 32 JS owners; this is the scoped unit layer, not
an assertion that every private function in the whole application has a unit.

## Run and maintain

```sh
python -m pytest -m target
python -m pytest tests/test_live_chain_structure.py
python -m pytest tests/test_integration_*.py
npm run test:js:functions
npm run test:js
```

The default full test commands include both lanes. Add cases to the existing
owner rather than adding another unit test for that function. For a new owner,
update the manifest and the uniqueness guard. Keep integration additions in the
integration lane; changes to the preserved historical bodies require explicit
review/update of their ledger, not silently dropping the comparison.

Fixtures may prepare state using real collaborators; mocks belong at external
boundaries. Never stub the function under test. No production code, quality
baseline or golden is changed by this restructuring.
