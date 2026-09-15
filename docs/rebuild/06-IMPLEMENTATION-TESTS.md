# 06 — Implementation roadmap, tests and approval gate

> Target-design record. Current progress and executed tests are maintained in [implementation status](../IMPLEMENTATION-STATUS.md); the roadmap now authorizes and implements Step 1.

## Phased plan (no code in this change)

| Phase | Future work | Exit criterion |
|---|---|---|
| P0: review | Review this packet; record confirmed Chrome/visual-runner reuse; resolve OS/permission/remaining UX questions; obtain missing page captures | Owner approves scope/removal/architecture; site evidence sufficient or adapter stays blocked |
| P1: clean foundation | Isolated new package, schemas, headless domain, typed errors, retained dark Qt/WebEngine workspace, layout/undo/preset extraction, root tests/gates/ignore rules | Fresh install + smoke test on chosen OS, no imports back into the old directory after extraction, no DB |
| P2: local-only queue | Picker, scan/reconcile, thumbnails, selection/bulk controls, full preset/variable libraries and import/export, global undo/redo, JSON checkpoints and safe output writer | Deterministic scanning/naming/persistence/crash tests; no network side effects |
| P3: browser and dry-run | Retained CDP discovery/connection to user-opened Chrome, per-URL exact target/readiness checks, retained visual runner, sanitized fixture suite | Correct composer scoped; hidden CAPTCHA not false blocker; unknown pages unready; no Send in dry-run |
| P4: sequential engine | Baseline, upload/prompt verification, intent-before-click, single submit, waits/checkpoints, control semantics | Local mock exercises every transition including duplicate-risk and manual-action checkpoints |
| P5: verified result | Message ownership, fresh completed output, original download, validation, safe publication and recovery | Stale/ambiguous outputs rejected; crash after publish recoverable without resubmit |
| P6: cleanup and controlled pilot | Approved old-code/doc/evidence deletion, fresh current docs, small authorized live batch | All acceptance criteria demonstrated; manual checklist documented; no unsafe legacy dependency remains |
| P7: release | OS packaging, privacy/license/dependency review, maintenance guidance, actual limitations | Fresh-machine install and restart tested, no private artifacts shipped |

Local-only components can be built only after design approval; P3's concrete site adapter additionally needs the missing evidence. Do not advertise end-to-end completion because the queue UI or a synthetic mock works. Deletions should be a distinct reviewable change; do not wait until release to discover new app still imports old modules.

## Acceptance-to-test map

Future test names are planned modules, not existing/running tests.

| ID / requirement | Automated evidence | Manual evidence |
|---|---|---|
| A01 exact multiple URLs/readiness | `test_urls`, `test_readiness`: preserve text; whitespace invalid; credentials/schemes rejected; redirects; duplicate rows; scoped controls; stale readiness reset | Two authorized exact conversations, login and unavailable page; wrong Agent Mode stays unsupported |
| A02 recursive scan | `test_scanner`: nested/mixed-case types, `_AI`/numbered suffix exclusions, additions/removals/renames/changes, symlink loop/root escape, same metadata edge | Native chosen folder and real thumbnail/relative paths |
| A03 selection/manual decisions | `test_queue`: bulk scopes, deselect before submit, persisted exclusion, reset confirmation, clear-completed retains fingerprint | Restart after selection changes, inspect all displayed fields |
| A04 loading/duplicate prevention | `test_workflow`: delayed DOM, stale target, intent fsync failure, crash before/after click, lost acknowledgement, backoff bounds, round-robin | Slow real generation, Stop after current, manual page navigation |
| A05 correct attachment | `test_attachment`: correct fresh preview, old message input rejected, wrong filename, multiple previews, upload failure | Add/upload sequence on target site; wrong-file guard |
| A06 exact prompt/ID | `test_prompt`: Unicode/newlines/quotes, unchanged text, unique per-attempt IDs, readback mismatch and partial fill | Verify marker and prompt in actual submitted user message |
| A07 new correlated result | `test_correlation`: baseline image, renewed signed URL, input image, response before prompt, foreign prompt, same asset reused, current response, pending load | Existing old result followed by new job; ownership/order visible |
| A08 uncertainty | `test_correlation`, `test_recovery`: missing roles, ambiguous multi-output, replaced DOM/navigation, timeout after send all review | Inspect needs-review UI; confirm no false completed save |
| A09 valid safe `_AI` output | `test_output`: PNG/JPEG/WebP actual format, HTML MIME spoof, corrupt/truncated/oversized bytes, bomb limits, collisions/races, source alias, disk-full/permissions, atomic publish crash | Open saved output beside unchanged source; highest-quality permitted download |
| A10 persistence/restart | `test_persistence`: schema, round-trip, corruption/backup, future versions, single-instance lock, revisions, interrupted attempts, orphan partial and published output recovery | Kill app at key checkpoints and restart; never blind resubmit |
| A11 manual CAPTCHA | `test_security`: hidden badge negative, active blocker pause, no interaction/token APIs, user-confirmed safe resume | Human completes real challenge if encountered; app brings browser forward |
| A12 actionable failures/history | `test_diagnostics`: error codes/actions, IDs/steps/attempts, sensitive URL/header/token redaction, consent/retention | Inspect readable history and review/skip/retry options |
| A13 configurable rectangle | `test_visual_action`: same target, duration/cleanup, pointer-events none, detach/scroll/resize, no challenge interaction | Observe rectangle several seconds at configured duration and correct element |
| A14 every parameter persisted | `test_presets`, `test_ui_settings`: schema field inventory equals editable-widget fields; all round-trip; invalid import unchanged; no auto-start | Export preset, modify settings, import and verify prompt/URLs/folder/visual/layout settings |

Also test startup/shutdown worker cleanup, locked source/output folder, URL edit while active, pause during generation, cancel before/after submit, retry limits across restart, and no user data exported into diagnostics. Pure negative tests must assert **zero submit calls** and **zero completed records** when any prerequisite fails.

## Safe integration test design

Create small sanitized fixtures from approved evidence, plus explicitly synthetic page states for delays/errors not safely reproducible live. A local mock page exposes attachment filename, marked messages, stable response roles, busy/complete state and controlled image bytes. Scenarios include two composers, old outputs, changing signed query strings, reloads, missing controls, security overlay, failed download and delayed file preview. Count submission events on the mock side, not merely client click calls. No external uploads or real account automation in test suite.

Synthetic stable attributes must never be presented as selectors observed on Arena. Test adapter parsing with real sanitized DOM fixtures separately from generic workflow tests against a mock adapter. Failure snapshots and test fixtures are screened for email, conversation content, tokens, full signed links and account images.

## Manual release checklist

- [ ] Fresh supported-OS install; start responsive UI, no legacy DB/files required.
- [ ] User-opened debug Chrome attaches without relaunch; login remains in its profile; no credentials in config/export/logs.
- [ ] Test exact URLs, expected redirects, unavailable/unsupported/login/error states; inspect final destination.
- [ ] Choose nested source folder; deselect, skip, rescan changes; restart preserves decisions.
- [ ] Watch rectangle; verify correct preview and exact marked prompt before one submission.
- [ ] Generate after an old result; prove current message/response ownership, wait for complete original asset.
- [ ] Validate output dimensions/format and `_AI` collision handling; source unchanged.
- [ ] Pause/resume, stop after current, cancel before/after send; inspect remote-cancellation warning.
- [ ] Resolve encountered CAPTCHA manually; no bypass; resume from safe checkpoint.
- [ ] Expire session/disconnect/load delay; errors actionable; uncertain submission never repeated automatically.
- [ ] Kill app after submit, during partial write, after publish; recover safely with metadata/confirmation.
- [ ] Corrupt a copied test state; last good state recoverable; no empty-history auto-run.
- [ ] Export/import every setting and UI parameter; history and secrets absent from preset.
- [ ] Limited consented diagnostics redact private data; default diagnostics off.
- [ ] Review/failed/skipped/completed totals and history remain correct across restart.

## Principal risks and decisions

| Risk | Required mitigation / release constraint |
|---|---|
| Site automation not permitted or account restrictions | Owner confirms permission/terms for specific workflow; no anti-bot bypass; do not automate if prohibited |
| Incomplete page evidence | Adapter blocked; request captures in research doc; unknown controls fail closed |
| Multiple composers / changing DOM | Unique form/flow scope, ordered evidence-backed fallbacks, versioned fixtures; unsupported instead of guess-click |
| Exactly-once not available remotely | Durable intent, one click, conservative review; clear paid/rate-limited duplicate warning |
| User uses same conversation concurrently | Recommend no manual messages during run; detect foreign messages/navigation and pause/review |
| No original download or trustworthy message ownership | Do not substitute thumbnail/old image and claim success; remain review/unsupported until permitted mechanism exists |
| JSON corruption/power loss/multi-instance | Lock, revisions, backup, atomic writes, fsync where supported, recovery gates; qualify network-drive durability |
| File-format/site-size mismatch | Start with observed PNG/JPEG/WebP; confirm max upload/download bytes and pixels; reject unsupported/animated inputs explicitly |
| Captures and presets contain private data | Minimize/restrict/redact; no credentials/logged signed URLs; approved evidence retention |
| Lightweight expectation vs Qt/browser footprint | Retain requested dark WebEngine workspace; remove unrelated features/dependencies; measure package/startup size instead of promising it |

## Questions for owner approval before implementation

1. **Operating systems:** Windows, macOS, Linux—what is the first supported/tested OS? Keeping the existing dark windows/panels and drag/drop is confirmed; this does not settle OS support.
2. **Browser — confirmed:** reuse old CDP system to connect to already-open Chrome started by the user with remote debugging (default loopback port 9222). Per-URL target and connection verification are required; no Playwright replacement.
3. **Session:** approve manual browser login with browser-managed persistent profile outside repo/presets? Any shared-machine/encryption/retention constraints?
4. **Formats/limits:** approve PNG/JPEG/WebP initially? Maximum source/download size and decoded dimensions? Animated formats excluded initially?
5. **Scheduling:** approve strictly sequential global jobs, round-robin ready URL rows? No parallelism in MVP.
6. **Permission:** are these exact accounts/pages authorized and is this automation permitted by target policy? No capability to bypass site restrictions is planned.
7. **Evidence:** can you supply same-conversation idle, preview, prompt, generation, completed-original/download, and security/error captures listed in doc 01?
8. **DOM drift:** approve stopping as unsupported/needs review with opt-in sanitized diagnostics, never auto-guessing selectors?
9. **Output:** approve beside-source only for MVP, actual output format, unique suffix default, explicit generated-only overwrite setting?
10. **Approval:** per-image review before Send or run-level approval and stop only on errors? Proposed initial default: per-image review; switchable and persisted.
11. **Selection:** approve new files pending but deselected by default, with Select pending bulk control? Reset/retry after possible submission requires duplicate-risk confirmation.
12. **Presets/undo/variables:** retaining the full existing systems is confirmed. Review doc 07 compatibility mappings, template semantics and JSON global-undo persistence. No database or chat-data migration.

## Definition of ready to build / known limits

Ready only after recorded owner approval of docs 01–08 and resolved critical assumptions; adapter additionally requires reviewed missing evidence. Currently there is **no new runnable app, no verified live adapter, no new passing test suite, and no confirmed authorized end-to-end download**. Static research does not establish them. Deferred: concurrency, watch-folder, per-image template overrides (shared templates/variables are in MVP), CSV reports, notifications, source/result comparison, alternate output folder and additional sites. Selector maintenance requires new sanitized before/after fixtures and dry-run checks before enabling a changed adapter.

## Retained-system regression gate (owner revision)

P1–P2 must preserve dark workspace, global undo/redo, drag/drop layout/stack interactions, named layout libraries and all preset/template/variable saving before deleting their old modules. Run the eight additional acceptance gates in [doc 07](07-RETAINED-WORKSPACE.md), including cross-surface undo after restart, failed-write atomicity, layout compatibility across screens, legacy import preview and complete variable round-trip. Add real JS DOM harness and Qt/WebChannel integration tests, not only Python mock-widget tests. Manual release must demonstrate all these retained interactions.

## Existing Chrome and visual-runner acceptance gate

P1 protects the existing CDP and visual-click implementation/test families; P3 adapts exact per-URL target matching and live connection checks, not browser replacement. Execute all regression/manual cases in [doc 08](08-CHROME-CONNECTION.md). Test refusal to fall back to another same-host conversation, no automatic tab/browser creation, truthful previously-checked versus currently-attached states, no command replay after reconnect, and no closure of user-owned Chrome on exit.
