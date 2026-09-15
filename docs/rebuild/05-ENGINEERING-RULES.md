# 05 — Essential code-creation and testing rules

Proposed new-app rules, extracted from `Process Images in Areana/Old App/docs/current/AGENT_RULES.md`. These do not retroactively change the old app's rule numbering or assert that its gates run at repository root. Preserve the useful contracts, not the old domain-specific implementation.

## Legacy-to-new mapping

| Legacy rules | New disposition |
|---|---|
| 1: shared visual click | Keep: one same-target highlight/action runner; configurable, preset-storable rectangle and delay |
| 2, 4, 5: reporting, empty vs broken, incremental progress | Keep: typed structured events; failed/empty/skipped/review are distinct; responsive queue and logs |
| 3: block attributes/config serialization | Replace block mechanics with typed settings schema; every UI parameter round-trips; no mirrored divergent defaults |
| 6: rejected entities must not persist | **Do not port literally**: deselected images MUST remain persisted so manual exclusions survive |
| 7: stop in all loops | Keep cooperative cancellation/deadlines; cancelled is not generic failure; propagate cancellation correctly |
| 8: tests execute real thing | Keep actual parser/verifier/probe behavior; not generated-string assertions or fake success signals |
| 9: guard must not stall, fail-open | Keep explicit no-op outcomes only; **reject fail-open for readiness, upload, submission, output or persistence** |
| 10: one control per decision | Keep one visible source of truth; no conflicting hidden retry/output settings |
| 11: chat seek/scroll behavior | Retire; unrelated to image jobs |
| 12: one global undo history | KEEP global workspace undo/redo and persisted cursor; replace DB-world delegates with JSON-backed local commands; never undo external submissions or immutable attempts |
| 13: never persist unreadable state | Keep validation, schema round-trip, safe import and failure visibility |
| 14: archive is not queue | Adapt: immutable attempt history is separate from current eligibility; clearing completed view must not enable duplicates |
| 15: archive two-step gate | Retire chat gate; replace with full attachment→prompt→submit→correlation→file→durability completion gate |
| 16: quality gates | Keep measurable limits/test integrity; retarget paths and tools, discard legacy exceptions/debt baselines |
| 17: current docs vs dated designs | Keep single current owner per topic and review record; remove unrelated documentation from active tree |
| 18, 19: cohesion/size and complexity-first remediation | Keep; do not create dozens of trivial forwarding modules or metric-gaming helpers |

## Required new-app invariants

1. No production implementation before owner design review; no site-adapter guesses where required evidence is absent.
2. Domain logic independent of Qt/browser/disk. UI sends commands; state machine owns decisions.
3. All side effects have observed prerequisites, explicit effect verification, durable checkpoint and typed failure/recovery.
4. Submission intent precedes click. No automatic retry after possible submission; each authorized new attempt gets a fresh ID.
5. Output ownership is an explicit evidence verdict. Needs review is a normal safety outcome, never disguised as completed.
6. No DB or chat-data migration; preserve validated workspace/preset compatibility. No secret-bearing presets, saved-page script execution or background target substitution.
7. Never bypass CAPTCHA; manual action and explicit safe continuation. Never log credentials, cookies, signed download queries or raw private HTML.
8. Settings, history and source files must survive failures without silent replacement; atomic state/output and crash tests required.
9. Every selector is scoped/versioned/evidence-linked; ambiguity fails closed. Every click uses shared visual runner.
10. Every loop/wait has a deadline and cancellation; UI and worker lifecycle tests include shutdown mid-job.
11. Full prompts/exact URLs belong in access-restricted local attempt history as required, **not ordinary logs**. Diagnostics default off, opt-in and redacted.
12. Update implemented docs and relevant behavioral tests in the same change. Do not claim test success from a collection/import failure or an unrun checklist.

## Quality limits to preserve

For new production Python, carry forward legacy hard thresholds unless the owner explicitly approves a documented adjustment:

| Metric | Target | Hard limit |
|---|---:|---:|
| Function/method physical AST span | ≤20 lines | 30 |
| Class physical AST span | ≤120 lines | 150 |
| Parameters excluding self/cls (including keyword-only, variadic) | ≤3 | 4 |
| Direct methods/class | ≤10 | 15 |
| Cyclomatic complexity | Low | 10 |
| Cognitive complexity | Low | 15 |
| Nesting | Shallow | 4 |

Files ideally 150–300 lines, smaller cohesive leaves welcome. Review second responsibilities before growth. Pure data models or one indivisible JS payload may need a narrowly justified reviewed exception, not mass waivers. Resolve nesting → cyclomatic complexity → cognitive complexity → size. No `part1/part2`, hidden branches in lambdas, catch-all kwargs to evade limits, dead code or duplicated logic. Adapt legacy gate implementation only after inspecting its assumptions; never copy old measured baselines.

## Test policy

- Fast headless domain tests must import/run without Qt, browser install, network or database. Filesystem tests use isolated temp directories.
- Browser integration executes actual adapter/probe code against sanitized offline fixtures or a controlled local mock site. Mark synthetic scenarios honestly; passing mocks does not verify live site selectors.
- UI tests exercise retained JavaScript workspace behavior, Qt/WebChannel integration, undo chronology, drag/drop, layout and preset/variable round-trip rather than giant permissive QObject stubs.
- Assert positive and negative behavior: deleted feature, reused output, wrong composer/file, missing durable intent and duplicate click should fail tests.
- Inject clock, ID generator and browser/IO interfaces for deterministic timeout/backoff/race/crash tests; avoid sleeps and real network in unit tests.
- Proposed new coverage floor: ≥90% statements and ≥85% branches in domain/workflow/persistence/verification; report uncovered paths and per-file coverage. Critical invariants each need explicit tests regardless of percentage. Establish real baseline; never inherit old percentages.
- Targeted mutation testing for correlation, submit guards, naming and transitions. Baseline must collect and pass first; import/tooling errors count as invalid run, not killed mutations. No claim of 100% without inspecting results.
- Root CI should run formatting/lint/types, pure+filesystem tests, coverage, complexity, offline browser tests and supported-OS Qt smoke tests in separate visible jobs. Tests cannot silently skip because dependencies are missing.
- Real paid generation/authenticated uploads are manual, opt-in only; CI never uses user accounts or solves challenges.
