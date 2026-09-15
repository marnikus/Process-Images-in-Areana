# Implementation steps — approximately four hours each

Owner has authorized Steps 1–6 and pushing the session branch. Estimates are planning timeboxes, not claims of elapsed work or fixed deadlines. Each is about 3–5 engineering hours including tests/review; external evidence, OS setup and site changes can extend them. Do not rush safety gates to fit a timebox. Overall initial budget: **12 × ~4 hours = ~48 hours**, excluding waiting for evidence and unforeseen compatibility work.

**Progress:** Steps 1–6 code implemented; local headless/DOM, real Qt channel and loopback CDP transport gates pass. Native WebEngine rendering/manual Windows Chrome remain unverified and CI is inactive pending workflow permission. See [status and measured checks](../IMPLEMENTATION-STATUS.md). Steps 7–12 are not yet implemented.

## Protected scope

Retain/adapt existing dark WebEngine workspace, drag/drop panels and stacks, saved layouts, global undo/redo, complete preset/template/variable systems, existing Chrome/CDP connection and old rectangle/click runner. JSON only; no chat database. No bulk deletion before retained code and tests have been ported. Site-specific execution remains blocked by missing reviewed page states in doc 01. Step 1 has no site side effects and does not require those selectors.

| Step | ~4-hour work package | Deliverable and exit gate |
|---|---|---|
| **1** | **Isolated foundation + enforceable quality gates** | Installable headless package; strict local CDP/highlight/URL-row configuration contracts and versioned connection preset codec; exact existing-tab matching with missing/ambiguous outcomes; offline validation CLI; real tests and CI. Protect/run a selected existing workspace/visual regression baseline without modifying old app. No new GUI or live connection claimed. |
| 2 | Extract dark workspace shell and layout core | Reuse actual HTML/CSS/JS and Qt/WebChannel lifecycle; replace old panel registration with explicit reviewed mapping; drag/drop/sash resize and named layout controls retained. Real Node + Qt smoke tests. No legacy folder runtime imports after extraction. |
| 3 | JSON workspace + global undo/redo | Authoritative atomic snapshot of editable state and timeline/cursor; revision, backup, instance lock, recovery; coalesced gestures and cross-panel undo. Crash/write-failure tests; no undo of remote effects or completion evidence. |
| 4 | Full presets, templates and variables | Extract existing libraries/UI; all-family CRUD/import/export/preview; lossless backup/compatibility mapping; literal vs rendered prompt mode. All editable fields round-trip, invalid imports leave state unchanged. |
| 5 | Existing Chrome connection integration | Reuse CDP transport/service/bridge and connect user-opened targets by exact URL. Per-row discovery/liveness/readiness separation, duplicate-tab chooser, single-client lease, safe reconnect. Mock transport + manual Windows debug-Chrome check. |
| 6 | Folder scanner and image queue | Recursive scan, thumbnails, source fingerprints, generated-file exclusion, selection/bulk/manual decisions and reconciliation. Temp-filesystem tests for changes, aliases/symlinks and restart behavior. |
| 7 | Retained visual runner + adapter dry run | Port actual red FIND/orange CLICK runner and tests; all timing fields persisted. Reviewed image-page readiness/attachment/prompt selectors only; diagnostic consent/redaction. **Blocked for live adapter until required captures reviewed.** |
| 8 | Sequential job preparation and upload | Round-robin ready rows, immutable attempt inputs, IDs/baseline, verified preview and exact prompt readback; pause/cancel before submit. Safe mock interactions; no guessed upload flow. |
| 9 | Submit-once and safe wait/recovery | Durable intent before one Send; confirmed marked message; timeout/security/auth checkpoints; stop/resume/interruption semantics. Crash/disconnect tests prove no automatic duplicate submission. |
| 10 | Correlated output and safe save | Prove new response ownership; permitted original download; image validation, hashes, actual extension, `_AI` collision/no-clobber publication and recovery. **Requires reviewed completion/download evidence.** |
| 11 | End-to-end UI and regression pass | Connect all panels/settings/actions, truthful progress, structured privacy-safe diagnostics; combined undo/preset/queue/restart tests; authorized manual tiny-batch pilot. Mock success is not live-site acceptance. |
| 12 | Approved cleanup and release | Delete only obsolete feature families/docs after extraction checks; root dependency/import audit; Windows packaging/install/manual checklist, maintenance docs and limits. Preserve relevant fixture/source history; no user profiles/secrets/media shipped. |

## Step 1 scope boundary

The initial connection preset covers only the implemented URL rows, loopback endpoint and inherited highlight parameters. It is explicitly **not** a replacement for full window/stack/template/variable libraries (Step 4). It stores no live connection state, profile contents or jobs. The CLI is an offline foundation check, not the desktop app. Exact matching is implemented independently of old fuzzy chat policy; the old connection transport will consume it in Step 5.

Tests in Step 1 must reject protocol/path/query/fragment differences, duplicate tab matches, embedded credentials, unsupported schemes and invalid setting types/ranges. A single exact match is a discovery candidate, **never ready/connected**. No external requests, uploads, browser launches or selector guesses in this step.

For every subsequent step: inspect retained code → smallest cohesive implementation → behavior/negative/failure tests → quality/coverage gates → update actual status. Do not mark a milestone complete without its exit evidence. Retained legacy regression suites establish a baseline, not new functionality acceptance.
