# Essential Rules — DEPRECATED, use docs/current/AGENT_RULES.md

> **This file is kept as legacy pointer.** The authoritative detailed rules are now in [`current/AGENT_RULES.md`](current/AGENT_RULES.md) (adapted from Old App's 730-line detailed version with 19 rules + 4 new, preserving thresholds, override format, remediation order).
> See also [`current/SYSTEM_OF_RECORD.md`](current/SYSTEM_OF_RECORD.md) and [`current/DOM_SELECTORS.md`](current/DOM_SELECTORS.md).
> Doc map: [`README.md`](README.md)

## Summary of Essential Rules for Code Creating and Testing (Kept from Old Project) — Full version in current/AGENT_RULES.md

## Core Principles
1. **Correctness, Traceability, User Control** prioritized over speed.
2. **Never report success** based only on click, timeout, or presence of any image. Every completed job must have evidence: correct attachment -> exact prompt -> one confirmed submission -> new correlated output -> valid download -> safe _AI save -> persisted completed state.
3. **Observe -> Execute -> Verify -> Persist -> Advance** — core execution rule. A successful click is never sufficient.
4. **No silent normalization** of user URLs that changes destination.
5. **No DB** — JSON persistence only, atomic writes.
6. **Site adapter replaceable** — selectors centralized, fallback strategies, diagnostic evidence on failure.
7. **Security:** Never bypass, defeat, outsource, or automatically solve CAPTCHA. Pause for manual user action. Respect ToS, rate limits.
8. **No secrets in logs** — credentials, session data, full signed URLs out of logs.
9. **Never overwrite source image** — output always with _AI suffix, unique name if exists.
10. **Ignore generated outputs** by default (_AI suffix) to avoid loops.
11. **Bounded retries** with backoff, logged. Never auto-retry submission that could create duplicate paid work.
12. **Manual controls** — user can include, exclude, retry, reset any image. Never process deselected image.
13. **State persistence** — progress survives restart. Interrupted jobs not blindly resubmitted.
14. **Uncertain correlation** => Needs Review, not false success.

## Code Structure Rules
- Keep responsibilities separate: UI, persistence, scanner, browser controller, site adapter, workflow/state machine, verification, logging.
- Avoid business logic in UI event handlers.
- Use dataclasses, enums, type hints.
- Centralize selectors, support multiple fallbacks.
- Structured logs with timestamp, job ID, URL ID, image path, state, attempt, result.

## Testing Rules
- Automated tests for deterministic logic: scanning, naming, persistence, state transitions, correlation rules.
- Safe integration tests or mocks for page interactions.
- Manual test checklist for auth, uploads, generation, CAPTCHA pause/resume, download, restart recovery, common failures.
- Tests must pass before push.
- Keep tests deterministic, no real browser in unit tests.

## Documentation Rules
- Research before implementation — inspect saved pages, document selectors, risks.
- Selector object required for every element: primary, fallbacks, scope, visibility, enabled, expectedCount, text condition, verification, evidence, lastVerified.
- If no selector matches, capture diagnostics and stop step, never guess-click.

## Completion Rule
No image is completed until program proves: correct attachment -> exact prompt -> one confirmed submission -> new correlated output -> valid download -> safe _AI save -> persisted completed state.
