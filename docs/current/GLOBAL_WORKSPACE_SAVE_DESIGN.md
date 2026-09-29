# Global Workspace Save — as-built contract

**Status:** implemented. Full design history (§A–§O, inventory, ADR, rejected alternatives):
[`docs/archive/2026-09-25-global-workspace-save/design.md`](../archive/2026-09-25-global-workspace-save/design.md)
(archived as implemented, RULE 17). Audits: structure
[`audit.md`](../archive/2026-09-25-global-workspace-save/audit.md) (2026-09-25), failure edges
[`audit.md`](../archive/2026-09-28-workspace-refactor-2/audit.md) (2026-09-28, SoR I-77), whole-branch
[`audit.md`](../archive/2026-09-29-workspace-audit-3/audit.md) (2026-09-29). Durable rows:
`SYSTEM_OF_RECORD.md` I-67 / I-77 / I-81. Section ids below match the archived design, so in-code
citations (`design §C.5`, `§D.3`, …) resolve here.

**One rule:** the global system is an *orchestrator over the native stores*, never a second schema.
A provider captures/validates/migrates/applies ITS native file; the workspace folder holds those
native files verbatim plus a manifest.

## C. Design

### C.1 Package layout (RULE 18 sized; imports ui → services → persistence/core)

```
app/persistence/workspace/   errors (STAGES+WorkspaceError) · integrity (canonical bytes, sha256,
                             safe_rel_path) · manifest (workspace_format 1) · fsio (temp → manifest
                             last → atomic publish)          — stdlib only, architecture-locked
app/services/workspace/      provider (contract) · registry (ONE table + RESTORE_ORDER) · meta
                             (ids/UTC/app_meta/compat/log) · reports · save · snapshot_index ·
                             restore (preview only) · gates (file gates) · recover (backup) · apply
                             (mutating restore) · providers/ (one small file per domain)
app/ui/panels/workspace.py   6 frozen slots + RULE 24 refresh table + Qt geometry clamp
app/ui/web/js/panels/        workspace.js (window flow) + workspace-live-sync.js (RULE 24 refresh)
```

### C.2 Provider contract (`services/workspace/provider.py`)

`StateProvider` class attrs: `domain_id, display_name, native_rel_path ('' = file-less policy),
schema_version, supported_migrations (versions this build can READ), dependencies {"strict"|"optional"},
sensitivity (public|personal|secret), required, restore_advice`. Methods: `live_paths(bridge)`,
`capture(bridge) → CaptureResult`, `validate(doc) → str|None`, `migrate(doc, from_version) → (doc, note)`
(pure; snapshot never rewritten), `apply(bridge, doc) → ApplyOutcome` (idempotent — rollback IS
apply of the pre-apply capture), `reconcile(bridge) → [notes]`. One-file stores read live state with
`read_live_json`/`live_capture`: missing file = empty store; unreadable/corrupt/non-object = capture
failure (RULE 4 — never save `{}` over a broken store).

### C.3 Snapshot boundary and capture

Save captures `arena_state` under the queue funnel's `state_lock`; other stores via their
deep-copying accessors. Docs serialize canonically (`sort_keys, indent=2, ensure_ascii=False`) —
identical state ⇒ byte-identical snapshot and report (tested). Checksums verify content, not layout.

### C.4 Shared-file contract (`session.json`)

`session_settings` owns every `DEFAULT_SESSION` key except the grid trio; `grid_window` owns exactly
`grid_layout, window_states, window_geometry` (ownership table: `providers/session.py::GRID_KEYS`).
One exported `state/session.json`; each domain merges ITS keys and commits once per domain
atomically; invalid grid ⇒ grid_window skipped, current layout kept, reported (RULE 13).

### C.5 Save algorithm

resolve `<base>/<name>_<UTC yyyyMMdd-HHMMSS>/` (existing target refused) → per provider capture +
validate under the lock → abort on any capture failure unless `allow_partial` → write `state/` +
redacted `metadata/app-environment.json` into a sibling temp → **manifest last** (commit marker) →
atomic rename (EXDEV ⇒ copy+rename; bounded backoff) → index + `reports/save-report.json` into the
published folder (post-publish failures are `report_note`s, never crashes). Failed publish keeps the
temp as `<target>.failed-<ts>`; previous snapshots always untouched.

### C.6 Restore algorithm

1. `preview_restore` — manifest (+ safe queue-file read for the folder-root remap note), no mutation.
2. Selection by manifest ids (`selected=None` = all file-owning domains); unknown ids refused.
   Strict dependencies expand transitively (`registry.restore_order` fixes the order).
3. Recovery backup of every affected live file → `config/workspace_recovery/<UTC>/` (+`recovery.json`);
   an uncopyable existing file or unwritable folder **refuses the restore before any change**;
   `-02`, `-03`… on same-second collisions; prune keeps 10 (logged).
4. Per domain in `RESTORE_ORDER` (`captcha_keys` → `captcha_recordings` → `captcha_stats` →
   `cooldowns` → `arena_state` → `session_settings` → `grid_window` → `undo` → `window_presets` →
   `arena_presets` → `job_history`): dependency → schema → safe-path → size/sha → parse → migration
   (pure) → semantic (`validate`) → pre-apply capture → transactional `apply` with rollback to that
   capture. A provider crash is that domain's row (`migration`/`semantic`/`apply`); the run always
   ends in a report + `last_restore`. No cross-domain rollback (by design).
5. `reconcile()` per restored domain: in-flight jobs → `interrupted`, persisted `run_state` → `idle`
   (never revive a run), live watcher/pool re-applied, captcha balance marked stale. Failures are notes.
6. Result `success | success_with_warnings | failed` (`damaged` ⇒ `failed`) +
   `reports/restore-report.json` into the workspace folder (else beside it, and say so). The UI
   refresh follows what WAS restored, even in a failed run (RULE 24).

### C.7 Grid & window semantics

`canonical_grid_payload` is the validation/migration pipeline (version, tree shape, depth ≤12, sizes
≥4 %, known window set, legacy id rename, missing-leaf append). Restore adds: unknown leaf ⇒ drop
leaf + report (never the whole layout); NaN/Inf sizes invalid. Geometry: ints > 0, then clamped
Qt-side (`panels/workspace.clamp_restored_geometry`) with the note `window geometry clamped to this
screen` **only when clamped** (I-77 — a note reports what happened).

## D. Folder + manifest schemas (frozen: `workspace_format` 1)

### D.1 Folder contract

```
<name>_<UTC yyyyMMdd-HHMMSS>/
  manifest.json            # written LAST; presence = committed snapshot
  state/                   # native files: session.json, app_state.json, undo.json,
                           # window_presets.json, arena_presets.json, cooldowns.json,
                           # captcha_stats.json, job_history.json
  reports/                 # save-report.json (save), restore-report.json (any restore attempt)
  metadata/app-environment.json   # redacted env + inclusion_policy; no secrets, no user paths
```

### D.2 manifest.json (as emitted by `save.domain_entries`)

Per domain: `display_name, path, schema_version, supported_migrations, required, dependencies,
sensitivity, bytes, sha256` (the two session.json domains share one file entry) + a `capture` block
(`ok`/`excluded`/`excluded_reason`/`redacted_reference`/`notes`). Header: `format
"arena-workspace"`, `workspace_format`, `snapshot_id`, `parent_snapshot_id`, `name`, `description`,
`snapshot_kind` (`full`/`partial`), `created_utc`, `updated_utc`, `app`, `compat`, `inclusion_policy`.
Policy domains (`captcha_keys` secret, `captcha_recordings` default-excluded) appear with a reason,
never with data (`_policy_row` explains them on restore via `restore_advice`).

### D.3 Optional-inclusion policies (all opt-in, none default)

| Resource | Default | Opt-in |
|---|---|---|
| `config/captcha_recordings/` | excluded (page-derived, large) | future flag (documented) |
| `config/captcha_solvers.json` keys | excluded forever (redacted presence only, RULE 20) | encrypted export = separate future ADR |
| source images / `*_AI` outputs | excluded (RULE 14, filesystem truth) | never |
| `logs/`, `config/uivision/` | excluded (runtime) | never |

### D.4 Report vocabulary

Save: `{snapshot_id, started_utc, finished_utc, result, published, domains[], errors[],
failed_required[]}`. Restore: `{workspace, restored[], skipped[{domain_id,status,stage,cause,
expected?,actual?,rolled_back?,recommended_action}], migrated[], reconciled[], result, backup}`.
Failure stages (one vocabulary, `persistence/workspace/errors.py`): `missing | unsafe_path | checksum
| parse | schema | semantic | migration | dependency | capture | apply | reconcile | rollback`.

## M. LIVE-SYNC RULE (RULE 24) — restore refresh points

`panels/workspace.py::_REFRESH_TABLE` re-pushes `arena_state`, `undo`, `job_history`,
`window_presets`, `arena_presets` via the bridge's own emitters. `panels/workspace-live-sync.js`
re-renders UrlList/ImageQueue/Progress/Settings/PromptEditor/FolderPicker from `get_arena_state`,
re-applies the grid through `SashCore.deserialize`, and re-runs the config loaders
(`WS_CONFIG_RELOADERS`: cooldown, job-cycle, CDP, watcher, firefox-auto, action-blocks).
Anything added later that renders a persisted value MUST join these two tables.

## Open items (deliberate non-changes)

`restore.py` keeps its name although it is preview-only (audit #1 §4.3 decision); the Python/JS
refresh tables stay split across languages (audit #2 U2); policy skip rows are staged `apply`
(frozen report vocabulary).
