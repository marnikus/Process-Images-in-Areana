# Testing and quality gates

Activate the root development environment from README. Required: Python 3.11+, installed `.[dev,desktop]`, Node.js 22+, and `npm ci --ignore-scripts`. Current checks require real QtCore/QWebChannel, but no graphics display, database, Chrome or user account.

```sh
python tools/check.py
```

The same runner is referenced by the inactive CI template (`tools/ci/quality.yml`) and optional pre-commit hook. GitHub workflow-write permission is required to enable CI; it has not run. It fails if tooling or required retained files are absent; it never silently skips a broken suite. It runs:

1. Ruff lint/import checks and formatting on new `src/`, `tests/`, `tools/`.
2. Strict mypy on the new production package.
3. ESLint/Prettier for new UI JavaScript and the controlled visual fixture peer, sixteen DOM integration tests using the real Python backend, and the root pytest suite with actual statement/branch coverage; old pytest/conftest is deliberately not collected by the new suite.
4. Rule 16 AST size, parameters, methods, nesting; Radon CC; cognitive complexity; independent domain statement (90%) and branch (85%) floors; pure-domain import guard. Workspace, persistence, browser, scanning and automation have independent coverage floors too. Fresh coverage report required. Tests inject violations to test these gates too.
5. Fifteen targeted safety mutation experiments in temporary source copies. A passing isolated baseline is required; only test failures count as killed mutations. Surviving mutations, collection failures or changed experiment targets fail the gate. This is **not** a full-project mutation score.
6. Twelve selected old JS regression scripts (actual shipped modules with small DOM/bridge doubles), plus 20 selected old visual-probe tests that execute generated JavaScript through Node.

Generated coverage lives in ignored `coverage/`. Tools/tests are not production-size gated; production Python is. No broad new-code metric exceptions exist. Retained old runtime has not been relabeled as new-code-compliant. The selected old URL-toolbar tests document its current behavior, not authorization policy for the new exact URL matcher.

## Individual checks

```sh
python -m pytest
python -m ruff check src tests tools
python -m ruff format --check src tests tools
python -m mypy
python tools/mutation_smoke.py
```

`tools/quality.py` expects the coverage output from a full run. To install the optional pre-commit hook, install `pre-commit` separately and run `pre-commit install`; activate the same development environment before committing. Root `.pre-commit-config.yaml` invokes the full check runner. No hook installation or remote CI result is claimed here.

## Retained baseline scope and repairs

`tools/check.py` lists the exact old suites. Includes layout model, drag, resize, window controls, persistence/close autosave, window presets, preset import/export, stack migration, URL toolbar, FIND/CLICK highlighting/effect and result interpretation.

Initial baseline exposed stale loaders following earlier JS splits. `Old App/tests/js_family.js` now mirrors the already-shipped `ui/index.html` order for sash drag, stack drag, window presets and general presets. Two old UI tests now load these real families rather than only their facade. Window export's bridge double now answers the existing `load_window_preset` prerequisite; a separate missing-preset test asserts export is not called. No production behavior was patched to make tests pass. Root loader tests check actual script-order alignment.

The old `TestBlockConfig` class loads the full Qt/action registry; that dependency is outside Step 1's headless baseline. The full old visual runner, CDP, Qt shell and undo/DB integration suites have **not** been declared passing. Port and run the appropriate real tests when those systems are extracted (Steps 2–5/7), without permissive mock imports hiding missing dependencies. No paid/live integration in CI.

## Future release tests

The [acceptance map](rebuild/06-IMPLEMENTATION-TESTS.md), [retained workspace cases](rebuild/07-RETAINED-WORKSPACE.md), and [Chrome/rectangle cases](rebuild/08-CHROME-CONNECTION.md) remain mandatory as their code lands. Test atomic JSON + undo, filesystem/output publication, interruption, submit-once, output correlation, manual CAPTCHA and actual supported-OS UI separately; Step 1 coverage does not establish these features.

## Current native boundary

The full gate includes a real QtCore/QWebChannel transport test crossing a QThread;
no fake Qt modules substitute for it. Headless coverage includes `desktop/bridge.py`,
and excludes only native `app.py`, `window.py` and `dialogs.py`.

`python tools/desktop_smoke.py` is a separate real WebEngine rendering, recovery,
restart and close smoke. It has **not run successfully** here because system graphics
libraries are missing. The inactive CI template includes that smoke and combined/native
coverage floors, but these are unmeasured until an authorized native run completes.
See [current measured results](IMPLEMENTATION-STATUS.md).

## Steps 4–6 test boundary

The gate now includes all-family library CRUD/compatibility/invalid-import/undo,
real retained stack-pointer and typed-field DOM interactions, loopback HTTP/WebSocket
CDP framing/liveness/duplicate-choice/navigation/disconnect/lease tests, and synthetic
filesystem image scanning/fingerprint/thumbnail/selection/reconciliation tests.
Only the protocol peer is simulated; the actual aiohttp/websockets transport executes.
No account, live Chrome, browser launch or external website is needed by the gate.

Optional dependency audit (network access): install `pip-audit`, then run
`python -m pip_audit --local`; run `npm audit` for UI tooling. These supplement, rather
than replace, behavior tests and native/Windows acceptance. Keep reports out of Git.
Patched Python pins were verified with the full gate; native Qt/Chromium security and
supported-OS release review remain separate.

The four added mutation cases test fingerprint-bound selection, reviewed-import digest
binding, CDP target identity, and JSON boolean/number distinction. Each selected suite
must pass an isolated baseline before a mutant can count as killed.

## Offline Steps 7–9 evidence

The root suite includes 33 execution tests and 10 actual retained-probe tests, including
a real child-process crash after durable Send intent and synthetic Send, a disk-intent
check before the actual controlled DOM click, explicit restart recovery, cancellation,
manual blockers and ownership changes. New mutations remove Send intent, recovery
and unique-target barriers. Probe provenance is independently checked against original
AST fragments, without importing the old application. See [scope and limits](STEPS-7-9.md).
These tests do not establish live upload, native rendering or saved output.

## Output and release checks

23 output tests exercise actual file decoding, format-derived extensions, collision/link
protection, write faults, immutable save evidence, actual child-process death after
publication, explicit recovery and a two-source lifecycle through save/restart/undo.
Seven wheel-audit tests reject missing/changed/unexpected/duplicate files. The new
DOM test checks saved/review state counts and text escaping. See [release handoff](STEPS-10-12.md)
for measured wheel/dependency audits and the still-pending Windows/live checklist.
