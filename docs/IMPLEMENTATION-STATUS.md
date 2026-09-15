# Implementation status

## Steps 2–3 — implemented; native rendering verification pending

The retained dark sash workspace is extracted with drag/drop, resizing, dock/window
controls, named layouts and image-panel content. The Qt/WebChannel facade stays on
the UI thread; request/completion signals dispatch serialized commands to a worker
thread owning the JSON snapshot/global-undo service.

### Latest measured verification (2026-09-15)

`python tools/check.py` passes the full local gate:

- **198 Python tests** and **7 extracted DOM integration tests** against the real
  Python service/store, plus all selected retained JS/visual regression suites.
- A **real QtCore/QWebChannel/QThread transport test** verifies asynchronous command
  completion, persistence, cached reads, stale revisions and latched write faults.
- Headless package combined coverage **97%** (excludes native app/window/dialogs,
  but includes the real bridge). Domain and workspace statement/branch coverage
  **100%/100%**; persistence **99.15%/96.43%**.
- Current wheel builds and includes all extracted UI assets and desktop modules,
  without the legacy runtime tree. This is packaging verification, not a GUI run.
- Ruff, strict mypy, ESLint, Prettier, complexity/size/import gates and six targeted
  mutation checks pass. Mutations are not a whole-project mutation score.
- Layout/prompt/settings/history/redo restart, gesture coalescing, cross-panel undo,
  atomic failures, crash/lock, corruption/backup recovery and lost/malformed
  acknowledgements are exercised. Jobs/external effects are excluded from undo.

### Explicit limitations

- **Native WebEngine rendering/dialog/close smoke is not verified.** Missing system
  graphics libraries block the sandbox run. The real Qt channel and DOM tests do
  not establish native rendering or supported-OS acceptance. Windows is untested.
- GitHub rejected the workflow push because the integration lacks `workflows`
  permission. **`tools/ci/quality.yml` is an inactive template, not enabled or run.**
  An authorized maintainer must install it at `.github/workflows/quality.yml` (or
  grant the connection workflow permission). Its native coverage floors are
  configured targets, not measured results.
- Full preset/template/variable libraries remain Step 4; Chrome attachment is Step 5.
  No live browser connection, upload or image generation was performed.

See [workspace operation/storage contracts](WORKSPACE.md). Next implementation stage:
Step 4, with native graphical verification still outstanding for Steps 2–3.

---

The following is the historical Step 1 checkpoint; its scope and measurements are
superseded by the current Steps 2–3 status above.

## Step 1 complete — offline foundation

**Date:** 2026-09-15. Owner authorized a ~4-hour-per-step roadmap and implementation of the first step. Timeboxes are estimates, not a claim that four wall-clock hours elapsed. [Full twelve-step roadmap](rebuild/09-FOUR-HOUR-STEPS.md).

### Implemented

- Installable `src/image_queue` package with zero runtime dependencies for this foundation.
- Immutable validated URL rows, loopback-only Chrome endpoint and inherited visual-highlight timing contracts.
- Exact existing-tab candidate matching: preserves path/query/fragment/scheme spelling; no fuzzy fallback, auto-open/navigation or connection claims. Missing/disabled/ambiguous results and conflicting discovery IDs fail safely.
- Strict versioned connection-preset JSON codec and disabled sample preset. Every implemented field round-trips; invalid/unknown/duplicate/malformed/oversized data rejected without mutating existing objects. This is a codec, not a durable job/workspace store or full legacy preset replacement.
- Offline CLI for URL syntax and local connection-preset validation; no browser/network/write side effects.
- Root coding rules, packaging/development config, ignored artifacts, quality runner, CI definition, optional pre-commit hook and setup/test docs.
- Selected retained-system regression baseline. Repaired **three legacy test files only** to load shipped JS split families and model the existing export prerequisite; added a missing-preset negative test. No legacy runtime source, private state, UI layout, presets or captures deleted/rewritten.

### Measured locally

Command: `python tools/check.py` from the activated root development environment.

| Check | Result |
|---|---|
| New/root pytest | **140 passed** |
| Selected retained JS suites | **142 checks passed across 12 scripts** |
| Selected retained visual-probe tests | **20 passed** (real generated JS executed in Node) |
| Domain statement / branch coverage | **100% / 100%** |
| Whole new package statement coverage | **100%**; one unexecuted module-entry guard branch (combined coverage ~99.66%) |
| Ruff lint/format | Passed |
| Strict mypy | Passed, 9 production Python files |
| Rule 16 size/parameters/methods/nesting/CC/cognitive gates | Passed; no new-code exceptions |
| Targeted safety mutation experiments | **6/6 killed** after passing baseline; not a whole-project mutation score |
| Offline sample-preset CLI | Passed; file unchanged, no Chrome connection attempted |
| Wheel packaging | Built and installed into a separate clean virtual environment; version/offline URL commands passed outside repository; wheel contains new package + metadata only |

Environment: Linux, Python 3.11.2, Node 22.22.3. The original CI definition targeted Ubuntu and Windows Python 3.11; it is now an inactive template because workflow-write permission is unavailable. Remote CI and manual Windows desktop testing have not run here. Raw coverage/build outputs are ignored artifacts, not tracked baselines to inflate future scores.

### Explicitly not completed

New dark desktop shell extraction, actual Qt/WebChannel integration, new-app global undo/state persistence, complete preset/variable libraries, CDP liveness checks, recursive scan/queue, workflow, upload/Send, correlation, download/output writing and release packaging. These remain Steps 2–12. No paid/account/site requests were made.

The full old Qt/CDP/undo test suite has not been run. Two `TestBlockConfig` tests require the old Qt/action registry and are outside the selected headless baseline; they are not silently counted as passing. Details: [testing scope](TESTING.md).

## Historical next step at the Step 1 checkpoint

Reuse the actual dark WebEngine shell, sash tree and drag/drop modules; map retained panels to image-app responsibilities. Preserve layout/preset controls and shortcuts. Establish the real Qt bridge smoke test plus existing JS regression tests before wiring undo persistence in Step 3. No silent replacement with native/light widgets. Review unknown old-panel mappings instead of deleting saved layouts.

The concrete Arena adapter remains blocked until missing image-page states in [research](rebuild/01-RESEARCH.md) are supplied/reviewed. Those gaps do not block local workspace/undo/preset development.
