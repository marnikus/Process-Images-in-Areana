# Free-page dispatch design — 2026-09-15

## Research / defect
The active UI calls Bridge._do_run_batch, not services/job_runner.py (the older Playwright runner). Its round-robin assignment changes image metadata only: every action uses self.cdp. One global sequential loop prevents overlap. CDPClient already supports independent instances and fetching tab IDs/websocket addresses. URL status is serialized and displayed verbatim by the URL panel.

Rules read: docs/current/AGENT_RULES.md, docs/current/SYSTEM_OF_RECORD.md, docs/current/CODE_VERIFICATION.md. Existing watcher is global and must not auto-pause/resume a multi-page batch based on one tab. Existing output probes provide readiness, generation and security observations; missing/error observations must fail closed.

## Implementation sequence
1. Baseline: existing 45 tests pass with pytest-asyncio installed. Capture branch coverage before edits. Characterize the actual Bridge action stack before adapting it.
2. Add a page-session owner in services: exact configured URL matching (no fuzzy cross-conversation fallback), unique target IDs, dedicated CDP clients, cleanup in finally. Unmatched and failed connections are explicit unavailable states.
3. Add a small cooperative dispatcher: one worker per physical page, shared deque popped without awaits, fresh checks before each claim. Mark busy before executing; never release solely because job returned or timed out. Observe generation/security/readiness again, requiring two consecutive idle observations before steady. Broken probes quarantine that worker rather than imply idle.
4. Worker waits remain cancellable; user pause prevents new claims, stop drains active jobs without claiming more, cancel cancels and awaits all workers before connections close. No connection or task leaks. No available pages is an explicit warning, not successful completion. Empty queue is distinct.
5. Adapt existing Bridge._do_run_batch to execute one assigned image on its supplied controller; remove global scheduling and run-state ownership. All direct CDP block operations use that controller's client. Batch lifecycle belongs to service coordinator. Prevent restart while cancelling/paused/stopping; disable global watcher interference during batch.
6. Test concurrency with blocked first jobs; faster page gets next image, duplicate target exclusion, external generation, CAPTCHA, probe failure, stop/pause/cancel, status transitions, connection cleanup, actual Bridge actions on assigned clients.
7. Update current behavior docs and run syntax, radon/cognitive/size checks, pytest, branch coverage, vulture, full pre-push workflow. Report pre-existing gate failures rather than weaken limits.

## Structure / metrics
Baseline radon Bridge._do_run_batch CC 359; Bridge.start_run CC 8. Bridge is already over class LOC/method limits. Preserve existing method identity and reduce it (legacy ratchet), add no Bridge methods. New service classes <=150 lines/15 methods, methods <=30 lines/4 parameters, CC <=10, cognitive <=15, nesting <=4; aim 4–20 lines. Small leaf data/session modules may be <150 lines (RULE 18). Existing action-block body remains legacy, not relabeled as compliant new code.

Rejected: asyncio.gather on the shared self.cdp, busy=False in unconditional finally, fuzzy same-host URL matches, copying the giant action stack, part1/part2 extraction, deleting safety branches to lower metrics. No changes to quality baselines or overrides to excuse missing tests.

## Boundaries
No live authorized Chrome exists in this sandbox; deterministic fake-CDP integration is required, with live two-tab manual acceptance still needed. Browser activity can begin externally between observation and action; app reservations prevent app-originated collisions, not user races. Persisted steady is never trusted on a new run. Existing unrelated action-block verification shortcomings are not redesigned here.
