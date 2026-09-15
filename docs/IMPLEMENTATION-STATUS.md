# Implementation status

## Current: offline Steps 1–12 implementation and push handoff

**2026-09-15:** The owner authorized the final steps and push. Offline correlated
original-byte validation, durable no-clobber save/recovery, truthful history/output
panels, source-repeat protection and release auditing are implemented. The earlier
Steps 7–9 work is included in this delivery. Full live/native acceptance is **not**
complete: no production adapter, live downloader, operator execution controls,
authorized site pilot or Windows installer/graphics acceptance is claimed.

See [Steps 10–12 / release checklist](STEPS-10-12.md). Legacy sources were retained,
not deleted while extraction evidence is incomplete. CI is still inactive.

Latest complete local gate: **348 Python tests**, **16 workspace DOM tests**, selected
retained suites, Ruff, strict mypy (**54 files**), JS lint/format and all quality gates
pass. **15 targeted safety mutations killed**, not a full mutation score.

| Package | Statements | Branches |
|---|---:|---:|
| Domain | 100% | 100% |
| Workspace | 99.85% | 99.68% |
| Persistence | 99.21% | 96.43% |
| Browser | 100% | 98.89% |
| Scanning | 99.32% | 94.23% |
| Automation | 99.53% | 98.25% |

Combined headless coverage: **98.66%**. The wheel's **98 members** match the source/
metadata allowlist. Fresh installation outside the checkout passes CLI, packaged
assets, JSON storage and real local image publication/verification. Python and npm
audits report no known vulnerabilities in audited dependencies; this is not a native
GUI, live-site or embedded-Chromium security guarantee. Runtime version remains 0.1.0.

---

The following checkpoints are historical and superseded by the current status above.

## Current: Steps 7–9 offline portions implemented; live gates blocked

**2026-09-15:** Owner chose offline-first work. Actual retained visual probes,
fixture-only sequential preparation and durable intent/evidence/recovery are now
implemented. No production adapter or desktop upload/Send command is enabled.
See [Steps 7–9 contracts and limitations](STEPS-7-9.md). Steps 10–12 remain pending.

`python tools/check.py`: **PASS**, **318 Python tests**, **15 workspace DOM tests**,
all selected retained suites, strict mypy (**52 files**), Ruff, JS lint/format,
size/complexity gates and **13 targeted mutations killed** (not a full mutation score).
Combined headless coverage: **98.59%**. Independent statements/branches:

| Package | Statements | Branches |
|---|---:|---:|
| Domain | 100% | 100% |
| Workspace | 99.85% | 99.67% |
| Persistence | 99.21% | 96.43% |
| Browser | 100% | 98.89% |
| Scanning | 99.32% | 94.23% |
| Automation | 99.38% | 97.78% |

Current wheel built and installed in a fresh environment; outside-checkout CLI,
offline-engine import and packaged visual/provenance assets pass. No native GUI
or live site action is claimed. Dependencies are unchanged from the prior audit.
Native WebEngine/Windows Chrome checks, reviewed live page evidence and CI activation
remain outstanding. Output observation is not image download/save/completion.

---

The following are historical checkpoints, superseded by the current status above.

## Steps 4–6 — code implemented; manual exit gates still open

**Date:** 2026-09-15. Owner authorized the next three roadmap steps and push.

- **4:** Seven named preset families, full JSON-field round-trips, explicit CRUD,
  preview/hash-bound import and portable backup export; lossless supported legacy
  mappings. Actual retained chips, stack drag and typed form row builders wired to
  global undo. Literal/default and explicit single-pass template modes with visible
  unknowns; no imported script/action execution.
- **5:** Adapted retained aiohttp/websockets CDP framing, discovery/service and lease.
  Exact user-opened target choices, independent discovery/liveness/readiness, bounded
  identity/page round-trip, runtime invalidation, no navigation/browser launch/replay.
- **6:** Explicit recursive scan, supported image decoding, metadata-free thumbnails,
  SHA-256 and stable-read checks, link/generated/output exclusions, fingerprint-bound
  row/bulk selection, changed/missing reconciliation and durable restart state.

### Latest measured verification

`python tools/check.py`: **PASS** — **275 Python tests**, **15 extracted DOM tests**,
all selected retained JS/visual suites, Ruff, strict mypy (42 production Python files),
ESLint/Prettier, size/complexity/import/coverage gates and ten targeted mutation checks.
Mutations remain a targeted smoke, not a full-project mutation score.

| Independent package | Statements | Branches |
|---|---:|---:|
| Domain | 100% | 100% |
| Workspace | 99.82% | 99.60% |
| Persistence | 99.21% | 96.43% |
| Browser | 100% | 98.89% |
| Scanning | 99.32% | 94.23% |

Combined headless coverage rounds to **98%**. Native app/window/dialogs remain excluded
from this measurement; the real Qt bridge/channel test is included. Actual HTTP and
WebSocket traffic is tested against a scripted loopback CDP peer, **not live Chrome**.
Filesystem tests use synthetic images, real hashes/decodes/locks/writes and injected
failure paths. DOM tests execute the retained pointer drag and typed form builders
against the real Python service/store, including safe imported text and CRLF retention.

Current wheel was built and installed into a separate clean environment; offline CLI,
packaged UI assets, library backup round-trip, disconnected CDP initialization and a
real synthetic image scan pass outside the checkout. This is not a native GUI run.

Dependency audit prompted patched pins for aiohttp, Pillow, filelock and pytest,
plus an updated build-tool floor. The audited local Python environment reports **no
known vulnerabilities**; the unpublished local package is not auditable through PyPI.
The npm tooling audit also reports zero known vulnerabilities. Neither audit is a
security guarantee or an audit of Qt's embedded Chromium/system libraries.

### Outstanding gates / deliberate boundaries

- **Native WebEngine rendering/dialogs and manual Windows debug-Chrome checks have
  not passed here.** The sandbox still lacks graphics dependencies. Steps 2–6 are
  not declared fully accepted on a supported desktop OS.
- CI remains **inactive** at `tools/ci/quality.yml` because the GitHub integration
  lacks workflow-write permission. No GitHub Actions run is claimed.
- Browser readiness remains `adapter_not_verified`. Step 7's concrete adapter is
  still blocked by missing reviewed image-page evidence. No user-account/site access,
  upload, Send or image generation was performed.
- Stored scan records/selections are historical after restart; rescan and reverify
  bytes before any future job preparation. Selection is not permission to submit.
- Legacy libraries/parameters are preserved; unsupported SQLite data is never opened.
  Old window bounds and provider-specific connection fields are retained for review,
  not silently applied to an incompatible screen/Chrome schema.

Operation, limits and extraction provenance: [Steps 4–6](STEPS-4-6.md).
Next planned implementation: Step 7, with native/Windows and evidence gates outstanding.

---

The following are historical checkpoints, superseded by the current status above.

## Historical Steps 2–3 checkpoint — native rendering pending

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
