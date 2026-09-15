# 07 — Retain dark workspace, undo/redo and all preset/variable systems

> Target-design record. Current progress and executed tests are maintained in [implementation status](../IMPLEMENTATION-STATUS.md); the roadmap now authorizes and implements Step 1.

**Owner revision:** retain these existing systems. This is a documentation-only scope correction, not implemented restoration. Existing source was never deleted. This document supersedes the initial recommendation to remove the workspace, global undo or stack/template libraries. No database remains the agreed constraint.

## Reuse boundary

Keep the current dark Qt WebEngine/WebChannel HTML/JS workspace and modern window/panel interactions. Keep sash-tree nesting, split direction, relative sizes, drag/drop placement, resize, window state, built-in and user-named layouts, last-session restoration and layout preview. Do not substitute a simpler static/light UI. Map the new URL list, folder/queue, prompt/template editor, workflow stack, settings, activity and job inspector into this workspace.

Keep stack drag/drop, named stack presets, custom block libraries and parameter editors. Replace chat/person/collector execution with image-safe actions. A preset is configuration, not permission to execute arbitrary uploaded JavaScript or bypass the fixed verification gates. Unsupported imported chat blocks remain preserved and clearly disabled in preview; never silently drop them or run them. Unknown required steps block execution.

Keep all preset capabilities: named save/save-as/load/update/delete, library listings/chips, JSON export/import, preview/validation, folder reveal and immediate UI refresh. Preserve each family's existing behavior where available; verify source/tests instead of assuming every historical design was implemented. Keep prompt template editing, variable catalogue, insertion, saved values, preview and persistence. Retire bot connections, remote providers, chat transcripts and DB-backed variable sources—not the editor or saving system.

## Source protection map

Before deletion, extract and test these families with their dependencies:

- `ui/index.html`, shared dark CSS, `ui/js/sash-*`, `window-presets-*`, `stack-*`, `presets-ui-*` and shared UI core.
- `services/layout_*`, `window_preset_*`, `named_section.py`, `preset_io.py`; layout, stack and preset bridge slots.
- `services/undo_service.py`, `undo_timeline.py`, `undo_apply*`, `undo_support.py`, and relevant UI undo/history integration. Remove only DB/people/archive-specific delegates after replacing their references.
- `stores/undo_store.py`, `window_preset_store.py`, `preset_store.py`, `block_store.py`, settings/session stores and atomic JSON foundations.
- `ui/js/bot-prompt*`, reusable variable/template UI; `services/bot_variables.py`, `bot_prompts.py`, `bot_presets.py` for catalogue/rendering/preset contracts. Remove unrelated bot runtime dependencies, not useful editor behavior.
- Existing Python and Node/DOM harness tests for retained features. Port real contracts before changing ownership/import paths.

Relevant evidence: old `WINDOW_PRESET_SAVE_EXPORT_DESIGN_2026-09-10.md`, `STACK_PRESET_EXPORT_IMPORT_DESIGN_2026-09-10.md`, current rules 3/10/12/13, `stores/undo_store.py`, `services/preset_io.py` and `services/bot_variables.py`. Preserve these relevant designs until their contracts are carried into current workspace/configuration documentation; unrelated chat/DB archives can retire.

## Global undo/redo — preserve behavior, remove database dependency

Retain one chronological timeline for every editable workspace surface, not separate panel histories. Each entry has command kind, target IDs, before/after payloads and label. Preserve cursor, redo-tail truncation after a new edit, bounded history (legacy app-level store caps at 100), coalesced drag/resize gestures and one-entry preset application. Persist across restart; apply/read back/validate before declaring Undo or Redo successful. Failed persistence must not advance the visible cursor or silently lose the prior state.

Undoable: layout/window changes, stack/block configuration, URL row edits/enabled state, prompt/template/variable edits, settings, preset-library operations and manual queue inclusion/skip decisions where safe. Native text editing can retain editor behavior while focused; document shortcut routing so a single keypress never executes both text-local and workspace undo. Global UI buttons expose the next action label.

Not undoable: remote upload/submission/generation, downloaded file bytes, immutable job attempts, completion evidence, automatic filesystem reconciliation or automatic engine transitions. Undo of a prior selection does not reset a completed job to pending. Reprocessing still requires an explicit new-attempt confirmation. For active job configuration, defer/disable conflicting undo or apply to future jobs only; frozen attempt inputs never change retroactively.

Old global history spans app JSON and DB-world records. Preserve its **user-facing single-timeline contract**, not its SQL storage. New `state.json` owns editable workspace, user decisions, libraries, undo entries/cursor and job history in one atomic snapshot, under a single writer/revision. User commands commit changed editable state plus timeline together. Runtime transitions update job history without adding undo entries. `config.json` and family export files are projections, never independently replayed authorities after crash. Startup reconciles revision and restores the authoritative workspace; corrupt state requires recovery rather than empty defaults.

## Full presets and saved variables

Maintain separate named libraries for window/layout presets, stack/workflow presets, custom blocks, prompt templates, variable sets and complete workspace/configuration bundles. Every editable parameter survives save/load/restart and family-appropriate export/import. Full workspace export includes all editable settings and libraries; ordinary layout export remains layout-only, preserving its old separation from job/content data. History, session cookies and credentials never enter portable presets.

Layout imports validate tree version, split directions, percentage sums, unique/known window IDs and window-state metadata. Use relative sizes across screens; saved absolute bounds are preview/diagnostic metadata. Supply an explicit old-panel-to-new-panel mapping preview. If a layout references removed chat windows, do not silently substitute or discard them. Preserve original import; require user-approved mapping or report incompatible.

Stack/block imports preserve names, parameters, ordering, enabled state and custom-block library. Validate supported types before apply; unsupported steps warn and block running. Updating any preset is reversible local editing. Exporting a file is not undone by deleting that file when the user presses Undo.

Template modes:

- **Literal (default):** preserve the exact entered text; braces are not automatically expanded.
- **Template (explicit):** save raw template plus selected variable set; preview and freeze resolved text and values per attempt. Then prepend the app-owned unique JOB-ID header. The user can inspect the exact submitted prompt.
- Proposed image context variables: source filename, relative path, source stem and attempt number; enumerate final names/types before coding. User-defined values are plain data, not expressions, code, environment lookups or secret access. Reserved app variables cannot be overwritten.
- Preserve unknown placeholders visibly and warn; never silently replace the user's whole template with a default. Require correction or explicit acceptance of unresolved literal text before submission.
- Existing chat aliases/placeholders remain intact on import but unavailable without their old data source. Do not synthesize chat history or restore a database to resolve them. Provide a mapping/replace preview instead.

Compatibility is lossless preservation plus explicit mapping, not a promise that old chat workflows run in the image app. Back up original JSON; preview migrations; reject future versions without rewriting; retain unknown fields in preserved original documents. Private saved configurations are never shipped as defaults.

## Additional acceptance gates

1. Existing dark UI styling and window interactions remain recognizable; drag/drop, split/resize and session restore work.
2. Nested layouts survive save/restart and named JSON round-trip, including different screen sizes and invalid/missing window IDs.
3. Mixed edits across layout, stack, variables, prompt and queue undo/redo in global chronological order; new edit truncates redo correctly; history cap/cursor survive restart.
4. Fault injection proves workspace and undo cursor cannot commit separately; active-job conflicts cannot alter frozen input or erase completion evidence.
5. Each preset family retains CRUD, preview, import/export, refresh and existing folder-reveal behavior; malformed import leaves current state unchanged.
6. Every editable field and saved variable value round-trips; template preview equals submitted rendered text; unknown variables never destroy a template.
7. Legacy layouts/presets preview compatibility mappings and preserve original data; removed chat steps never silently disappear or execute.
8. Restored stack UI cannot reorder away mandatory verification, submit twice, import executable code or bypass CAPTCHA.

## Documentation to retain/update

Add current `docs/WORKSPACE.md` covering dark windows, drag/drop, layout persistence, global undo and shortcuts. Expand `docs/CONFIGURATION.md` with every preset family, variables, compatibility and examples. Keep relevant old workspace/preset design records until migrated, not the entire unrelated archive. Architecture and test docs must cover both Python services and actual JavaScript workspace behavior.

## Additional owner-confirmed reuse

Keep the old CDP client/discovery/connection UI to attach to already-open user-selected debug Chrome pages, and keep the actual tested visual-click/highlight implementation. Do not replace either with a new browser framework or independent rectangle runner. The detailed contracts, source observations and regression requirements are in [doc 08](08-CHROME-CONNECTION.md). Existing undo, dark drag/drop workspace, layout storage and all preset/variable requirements above remain unchanged.
