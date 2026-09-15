# Image Queue — coding and testing rules

Read `docs/rebuild/README.md`, the relevant design and `docs/rebuild/09-FOUR-HOUR-STEPS.md` before changing code. Owner authorized Steps 1–6 and pushing this session branch; later stages remain separately reviewable. Missing Arena evidence still blocks the site adapter.

- Retain the old dark workspace, drag/drop, layouts, global undo, presets/variables, CDP and visual click runner. Do not delete or silently replace them. Old source remains under `Process Images in Areana/Old App/` until safely extracted with tests.
- New runtime code lives in `src/image_queue/`; no import of the legacy tree, SQL, Qt or browser from `domain/`. Never import/execute the old app merely to check the foundation.
- One editable state/undo authority; immutable jobs and external side effects are not user undo. No automatic submit/re-submit on startup or transport reconnect.
- Preserve exact URL and prompt text. No fuzzy destination selection, credentials in logs or automatic CAPTCHA handling. CDP is local; user owns debug Chrome.
- One shared retained visual-click runner. New-site selectors require reviewed evidence, unique scope and effect verification.
- One schema/default source; reject invalid imports without silent data loss. Settings round-trip; corruption is not empty state.
- Each production change requires behavioral and negative tests, formatting/lint/types, coverage and complexity gates. Tests must execute real behavior, not only inspect strings. Tool/collection failures are failures, not successful/skipped checks.
- Hard new-Python limits: function 30 physical AST lines, class 150, ≤4 parameters excluding self/cls, ≤15 direct methods; CC ≤10, cognitive ≤15, nesting ≤4. Prefer shorter cohesive units. Never game metrics with trivial forwarding helpers or hidden branches.
- Fix nesting → CC → cognitive → size. Any exception needs a specific reviewed constraint, not convenience.
- Independent domain/workspace/persistence/browser/scanning coverage floors: statements ≥90%, branches ≥85%; test individual critical invariants regardless of percentage. Targeted mutation tests for safety rules as they land.
- Run `npm ci --ignore-scripts` and `python tools/check.py` using the installed development environment. The separate native `python tools/desktop_smoke.py` requires actual Qt/WebEngine and system libraries, never fake imports. This runs actual selected legacy JS/visual suites too; Node 22+ is required. No live account access in automated tests.
- Update current setup/status docs with measured results. Never claim GUI/live-browser/image generation based on headless tests. Keep runtime state, profiles, downloads, caches and diagnostics outside Git.

Detailed provenance/retained-rule mappings: `docs/rebuild/05-ENGINEERING-RULES.md`. New runtime baseline starts here; legacy size/debt exemptions do not apply to new code.
