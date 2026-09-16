# Free-page dispatch verification — 2026-09-15

## Result
Implemented active desktop/CDP multi-page dispatch, with dedicated page sockets, exact target matching, deduplication, live admission and independent workers. The legacy Playwright JobRunner is not the desktop execution path and remains unchanged.

93 tests pass. No live authorized Chrome/browser session is available in this sandbox; live acceptance below remains required. This is not a claim that all RULE 16 gates pass: the repository-wide coverage gate is still red.

## Behavior exercised
- Actual legacy Bridge stack characterized before changing its call contract.
- Two page workers begin while both first jobs are blocked; the faster page takes subsequent images with unique claims.
- A completed/failed job is not admission authority: external browser generation still blocks reuse.
- Steady requires two consecutive observations, restarting confirmation after a busy observation.
- CAPTCHA, external generation and not-ready pages wait independently; a blocked unused page does not hold a finished queue open.
- Missing/error/invalid probes quarantine the page; another worker continues.
- Exact matching preserves case-sensitive conversation paths/queries; duplicate target IDs get one worker; missing and failed matches are explicit unavailable states.
- Pause prevents new claims; resume observes readiness again; stop leaves unassigned queue items untouched; cancel joins workers and leaves page status unchecked rather than falsely steady.
- Interrupted in-progress images become failed with the cancellation/error reason rather than remaining stuck processing; completed images are preserved.
- Cleanup occurs on normal, empty, discovery-failure and cancellation exits; one failed disconnect does not prevent other connections closing.
- Real Bridge HIGHLIGHT and SUBMIT paths use the reserved client's CDP, not the globally selected tab; worker completion does not change global run state.
- Restart is rejected for running/paused/stopping; idle cancellation is a no-op; active cancellation remains stopping until coordinator cleanup.
- Production JavaScript executes under Node with a DOM port, covering hidden file inputs, empty-composer disabled Send, missing composer, disabled prompt, visible/hidden loading output images, generation indicators and CAPTCHA precedence.

## RULE 16 / RULE 18 review
New modules checked directly with tools.verify_quality.check_file (no baseline exclusions): zero findings. New function max LOC 22, class max LOC 76, CC max 8, cognitive max 12, nesting max 2. No new function exceeds four parameters or class exceeds 15 methods. Only coordinator exceeds the 20-line ideal, with a resource-lifetime reason. Small leaf modules are allowed by RULE 18. No new Bridge methods; the existing method retains its identity to make the legacy ratchet auditable.

Legacy Bridge._do_run_batch: LOC 1222 → 1188, radon CC 359 → 351, cognitive 1189 → 1173, nesting unchanged at 23. Its large action-block implementation remains a pre-existing hotspot, not compliant new code disguised by relocation. No quality baseline changes or new threshold overrides.

Vulture (90% confidence) reports no findings in the new modules. Exact function-body AST clone audit (six-line minimum) finds no new duplicate groups. New functions all execute in behavior-asserting tests.

Coverage by new module:

| Module | Line | Branch |
|---|---:|---:|
| app/services/page_dispatch.py | 96.6% | 88.5% |
| app/services/page_sessions.py | 100% | 100% |
| app/browser/page_availability.py | 100% | 100% |

Whole app line coverage improves from 10.17% to 23.58%; branch from 5.42% to 10.04%. Still below required 80% / 75%. The supplied gate labels coverage.py's combined line+branch percentage as “line” and reports 20.5% / 10.0%; neither interpretation passes. No attempt was made to lower thresholds or exclude unrelated code to manufacture a passing result.

## Commands / environment
Dependencies installed into ignored `.venv`: pytest, pytest-asyncio (required by existing tests), Pillow, playwright, aiohttp, websockets, radon, cognitive-complexity, coverage, vulture. Node 22 runs the JavaScript harness. Qt has the repository's headless fallback in this environment.

- `.venv/bin/python -m compileall -q app` — passed.
- `.venv/bin/python -m pytest tests -q` — 93 passed.
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m coverage run --branch --source=app -m pytest tests -q` — 93 passed.
- `.venv/bin/python -m coverage json -o coverage.json` — produced local ignored report.
- `.venv/bin/radon cc -s app/services/page_dispatch.py app/services/page_sessions.py app/browser/page_availability.py` — all A/B, no C+.
- `PATH="$PWD/.venv/bin:$PATH" bash tools/pre_push_check.sh` — fails on existing overall coverage deficit (2 failures), with 142 legacy warnings. Because origin/main has no merge base with this session, the supplied changed-file tool falls back to all app files. Direct new-file checks were also run so untracked files could not escape review.

No push performed; no gate bypassed.

## Live manual acceptance (not performed here)
1. Start Chrome debug mode, open two distinct authorized conversation URLs, log in, add both exact URLs to the app and connect Chrome.
2. Select four source images and a valid action stack/prompt. Start; verify two URL rows become busy and two different tabs receive different images.
3. Keep tab A generating longer than B. Confirm B receives the next queued image while A receives no duplicate attachment or prompt.
4. With a tab already generating externally, start another batch; only the other steady tab should receive work. Finish the external generation and verify the waiting tab becomes eligible after confirmation.
5. Repeat with CAPTCHA, disconnected tab and a duplicate configured target. Confirm no upload to those blocked/duplicate workers.
6. Pause, resume, Stop, and Cancel while both tabs are active. Confirm no extra assignment after Stop, immediate cancellable waits, and no restart until cleanup. A new run must re-probe any browser generation left active by Cancel.
7. Check that each saved *_AI result corresponds to the source and JOB-ID on its assigned page, with existing verification/naming gates retained.
