# Image Queue — documentation-first rebuild proposal

**Research date:** 2026-09-15. **Current status:** owner authorized the first implementation step; the offline foundation is complete. The concrete site adapter remains blocked on missing evidence. See [actual implementation status](../IMPLEMENTATION-STATUS.md) and [four-hour roadmap](09-FOUR-HOUR-STEPS.md).

This is a new image-processing application built on the existing dark desktop workspace, drag/drop layout, global undo/redo and preset foundations. The unrelated chat domain is retired, not the workspace interaction systems. The original research phase was documentation-only. Implementation now follows the linked roadmap; these target-design documents are not proof that the full app works. No legacy production code or saved evidence has been deleted; Step 1 includes narrow legacy test-harness repairs.

## Read and review in this order

1. [Research and evidence](01-RESEARCH.md): what the repository actually contains, observed page states, selector map, and missing captures.
2. [Removal and retention map](02-CLEANUP.md): exactly which old responsibilities leave, which principles survive, and when deletion becomes safe.
3. [Product and workflow](03-PRODUCT-WORKFLOW.md): the retained dark drag/drop workspace, verified state machine, scheduling, and controls.
4. [Architecture and JSON persistence](04-ARCHITECTURE.md): modules, data ownership, crash safety, presets, and click rectangles.
5. [Essential engineering rules](05-ENGINEERING-RULES.md): adapted legacy rules and test/code-quality standards.
6. [Implementation and acceptance plan](06-IMPLEMENTATION-TESTS.md): milestones, automated tests, manual checklist, risks, and approval questions.

7. [Retained workspace, undo and presets](07-RETAINED-WORKSPACE.md): owner-requested reuse contracts, variable saving, compatibility and regression tests.

8. [Existing Chrome connection and visual clicks](08-CHROME-CONNECTION.md): retain the old CDP connection and rectangle systems; connect each exact URL to an already-open tab.

9. [Four-hour implementation steps](09-FOUR-HOUR-STEPS.md): estimates, dependencies and Step 1 scope.

## Proposed product boundary

- Existing dark-mode multi-panel/window workspace with drag/drop and saved layouts; multiple exact URL rows; one active image job globally.
- Native folder picker; recursive image queue; manual inclusion and status controls.
- Attach through the existing CDP system to user-opened debug Chrome; per-URL open-tab and live connection checks; replaceable evidence-backed site adapter.
- Exact prompt plus per-attempt job marker; verified attachment, submission, and new output.
- Validated images saved beside sources as `_AI`, unique names by default.
- **No database:** versioned local JSON state and presets; JSONL diagnostic events only.
- Configurable rectangle around the element about to be clicked; all editable UI parameters persist. Retain global undo/redo, window/layout presets, stack/block presets, prompt templates and variable saving.
- No people database, chat harvesting or outreach bot. Retain the window-grid editor and drag/drop stack authoring with image-safe blocks; presets cannot bypass the verified execution state machine.

Owner clarification: **keep the existing modern dark UI windows, drag/drop, layout storage, undo system, and full preset/variable-saving system**. This supersedes the initial light-UI/removal recommendation. Supported operating systems are still unconfirmed.

## Review gate

The owner authorized Step 1 after revising the retained-system and Chrome requirements. Further implementation follows the scoped roadmap; unresolved decisions and deletion mappings still require review. A review by the author of these notes is not owner approval. The site adapter remains blocked until the missing idle/upload/result/download/security states are supplied and reviewed.

The most important research finding: the saved image page contains `button[aria-label="Add files"]` and a supported-image input inside the image composer, but it also contains a different Agent Mode composer. The available image state is generating, not a complete successful job. A globally matched Send button is not sufficient evidence of image-page readiness.

## Documentation lifecycle

The design packet and scheduling document are not runtime setup instructions. The root README now documents the implemented offline foundation; full desktop setup guides will be updated as those steps land. Do not copy old instructions or claim a runnable app before it exists. Keep this reviewed proposal as a dated design record; current docs will own implemented behavior.
