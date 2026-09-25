# Global Workspace Save — Phase 0 Design (APPROVAL PENDING)

**Status:** design gate — no production code written. On approval this file drives implementation phases W1…W10 (§11); after the feature lands it is archived to `docs/archive/<date>-global-workspace-save/` and its durable rows move into `SYSTEM_OF_RECORD.md` (RULE 17).
**Size note:** this doc intentionally exceeds the RULE 18.4 context-file ideal (60–200 lines) because the task mandates one self-contained gate deliverable with embedded inventory/maps/risks. Every table below is evidence-backed from the files cited in §A.

---

## A. Repository findings and discrepancies (verified against code)

All claims below were verified by reading the named files on this branch (`arena/01a0d99a-process-images-in-areana`, HEAD `f5cb06e`). Items marked **(uncertain)** could not be fully confirmed statically.

### A.1 The live persistence layer (verified)

| Store | File | Owner module | Write helper | Atomicity | Retry on sharing violation |
|---|---|---|---|---|---|
| Session (grid, window states/geometry, theme, watcher/cooldown/cdp settings, `firefox_auto`, `action_blocks`, `stack_presets`, `custom_blocks`, `url_reconcile_interval_ms`) | `config/session.json` | `app/persistence/config_manager.py::SessionStore` | `app/persistence/json_store.py::save_json_atomic` | temp+replace | **NO** |
| Window presets | `config/window_presets.json` | `config_manager.py::WindowPresetStore` | `json_store.save_json_atomic` | temp+replace | **NO** |
| Undo timeline | `config/undo.json` | `app/persistence/undo_store.py::UndoStore` (via `app/core/undo_service.py`) | `json_store.save_json_atomic` | temp+replace | **NO** (save returns `False`, swallowed) |
| Feature presets (url/prompt/settings/arena) | `config/arena_presets.json` | `app/persistence/preset_store.py::PresetStore` | `json_store.save_json_atomic` | temp+replace | **NO** |
| App state (urls, folder, prompt, settings, images, jobs, progress, run_state) | `config/app_state.json` | `app/core/models.py::AppState` + `app/core/persistence.py` | `persistence._atomic_json_write` → `_replace_with_retry` (5 tries, 0.02 s×2 backoff, `EACCES/EBUSY/EPERM`) | temp+replace | **YES** (B10/I-39) |
| Cooldowns (entries ≤25, stats, aliases ≤200) | `config/cooldowns.json` | `app/persistence/cooldown_store.py` | `json_store.save_json_atomic` | temp+replace | **NO** |
| Captcha solver keys | `config/captcha_solvers.json` (+legacy `2captcha.json` folded on save) | `app/services/captcha/key_store.py::CaptchaKeyStore` | own `mkstemp`+replace, 0600 best-effort | temp+replace | NO |
| Captcha stats | `config/captcha_stats.json` | `app/services/captcha/stats.py::CaptchaStats` | own write | atomic | NO |
| Job history | `config/job_history.json` | `app/services/job_history.py::JobHistoryStore` (RLock) | `json_store.save_json_atomic` | temp+replace | NO |
| Captcha recordings | `config/captcha_recordings/<session-id>/` (`session.json`, `events.jsonl`, gz checkpoints) | `app/services/recording/store.py::RecordingStore` | own `_atomic_write` | per-file temp+replace | NO |
| Outputs | `<source-dir>/*_AI[_n].ext` | `app/core/naming.py` + `app/services/single_job_runner.py` | `atomic_write_bytes` | temp+replace | — (RULE 23) |
| Logs | `logs/arena.log` | `app/utils/logging.py` | append | — | — |

### A.2 Discrepancies between the task's "known app context" and the code

1. **`config/arena.json` and `config/urls.json` do not exist in the current code.** The single live app-state file is **`config/app_state.json`** (`app/ui/main_window.py:58` default `state_path`), holding urls + folder + prompt + settings + images + jobs + progress + run_state. `arena.json`/`urls.json` survive only in stale docstrings (`app/core/action_blocks.py:19`, `app/ui/panels/url_queue.py:77`) and in `SYSTEM_OF_RECORD.md` §1/§6/row 20. The design below targets the **actual** files; the doc drift is item W10 (docs fix).
2. **Window presets are NOT in `session.json`.** `SYSTEM_OF_RECORD.md` rows 18/20 say `window_preset_store` lives in session.json; the code uses a separate **`config/window_presets.json`** (`ConfigManager.__init__`). Code wins.
3. **Undo is single-homed.** `SYSTEM_OF_RECORD.md` says undo persists in "session.json `undo_history` and config/undo.json". Today only **`config/undo.json`** is written (`UndoStore`); `session.json` has no `undo_history` writer — `app/ui/panels/layout_state.py::app_state_payload` only *reads* the undo service for the JS boot payload. `DEFAULT_SESSION` (config_manager.py) has no `undo_history` key.
4. **`undo.json` write failure is silently swallowed** — `UndoStore.save()` catches everything and returns `False`; callers ignore it. Silent-loss risk (violates the spirit of "no silent data loss"); the workspace layer must surface undo save failures. **(✓ 2026-09-25 W9: any store's capture failure — undo included — is reported per-domain with stage `capture` and blocks the save refusal; see §F.)**
5. **The retry-on-sharing-violation fix (B10) covers only `app_state.json`.** `json_store.save_json_atomic` — used by session/undo/presets/cooldowns/job_history — has **no retry**. The reported real-world Windows/cloud-sync access-denied on `cooldowns.json` is consistent with this: cooldowns.json is rewritten on *every pool status push* (`app/services/run_state.py::persist_cooldowns` ← `Bridge._emit_pool_status`), so it is the file most likely to be held open by a sync client. W3 extends `_replace_with_retry` into `json_store` (behavior-preserving hardening).
6. **Export paths are not atomic.** `app/ui/panels/layout_state.py::_write_preset_doc` writes window-preset exports with a plain `open(...,"w")` — a crash mid-write leaves a partial export file. Feature-level import/export should reuse provider validators (task rule: "existing feature-specific import/load commands must use the same provider validators/migrators where practical").
7. **`UndoService.VALID_KINDS` (8 kinds) omits `action_blocks`**, yet `app/ui/panels/blocks_stack.py:78` pushes kind `"action_blocks"` and `undo_entries.py` remembers/applies it. Works today (VALID_KINDS is only used for filtering), but the kind vocabulary is defined in two places (RULE 10 smell; noted, not fixed in W1–W10 unless trivial).
8. **Window geometry restore does not clamp to the desktop.** `_restore_window_geometry` (main_window.py) validates ints/positivity but applies saved x/y/w/h verbatim; the "keep at least 100px visible" comment is not implemented. A snapshot from a dual-monitor machine restored on a single monitor can land off-screen. The grid/window provider (W6) must clamp (task rule 10).
9. **Transient state that must not be trusted on restore (verified):** `AppState.run_state` (persisted; live writer is `live/supervisor.set_run_state`), `images[].status == processing` (`live/feed.recover_stale_processing` exists for the live path), `jobs[]` in-flight statuses (`core/persistence._handle_interrupted` maps them to `interrupted` during filesystem reconcile), `UrlRow.tab_id` / cooldown `entries` keyed by CDP tab id (session-scoped; `consume_entry_for` has a URL fallback), `PageInfo.worker_no/alias` (pool join order — rebuilt on join; alias numbers persist in `cooldowns.json.aliases`).
10. **`PageInfo.jobs_completed` is display-only** (I-28) — restoring per-URL job counters can never mis-route work; safe to include.
11. *(uncertain)* Whether `config/config.json` (legacy migration) still exists anywhere: referenced only in `SYSTEM_OF_RECORD.md` §6; **no code reads or writes it** on this branch. Treat as extinct; workspace v1 does not import it.
12. **Slot surface is frozen at 141** (`tests/test_bridge_slots.py` exact-match). The new UI must add its slots deliberately and grow that contract test in the same commit (I-51/RULE 10 discipline; 18 windows locked by `tests/test_window_catalog.py` + JS mirrors).

### A.3 Conventions this design must follow (from `docs/current/AGENT_RULES.md`)

- RULE 13 (never persist unreadable state — grid validation already refuses bad payloads at `save_grid_layout`), RULE 16 (gates: `tools/verify_quality.py`, baseline `tools/quality_baseline.json`, coverage floors line 84.46 %/branch 80.27 %), RULE 17 (dated archive; `docs/README.md` index), RULE 18 (file 150–300 LOC, module 5–15 files), RULE 20 (secrets hygiene), RULE 23 (atomic writes).
- Import direction: `ui → ui-services/browser → services → core/persistence → stdlib`. No Qt outside `app/ui/` (+`qt_compat` shim).

---

## B. State inventory and source-of-truth map

"Native" = the exact file/shape the feature already owns today (non-negotiable rule 1: the global system is an orchestrator, not a second schema).

| # | Domain ID | Display name | Owner | Current file/store | Native schema (version marker) | Save entry point(s) | Load entry point(s) | Dependencies | Sensitive? | Derived/live? | Migration status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `session_settings` | Session & Settings | `SessionStore` (ConfigManager) | `config/session.json` (keys **minus** grid keys) | ad-hoc dict, no version key → **add `schema_version` sidecar in manifest entry**, store file verbatim | `ConfigManager.set_state`, `SessionStore.save`, `closeEvent` | `SessionStore.__init__`/`load` | none | personal (local paths, `cdp_user_data_dir`) | no | tolerant loads everywhere; no explicit version |
| 2 | `grid_window` | Grid & Window Layout | `SessionStore` (same file) + `app/core/layout_service.py`, `app/core/window_catalog.py` | keys `grid_layout`, `window_states`, `window_geometry` **inside** `config/session.json` | grid payload `{"v": 8, "tree": …}` (`GRID_VERSION=8`), window_states `{closed[], minimized[]}` filtered to `WINDOW_IDS` | `save_grid_layout`, `save_window_states`, `_save_window_geometry`, `reset_grid_layout` | `get_grid_layout`/`read_grid_payload`, `get_window_states`, `_restore_window_geometry` | `session_settings` (same physical file — shared-file contract §C.4) | no | geometry yes (display-dependent) | `canonical_grid_payload` normalizes; `LEGACY_WINDOW_IDS` renames; missing leaves appended (v4→8) |
| 3 | `arena_state` | Queue, URLs, Folder, Prompt, Jobs | `AppState` (`app/core/models.py`) via `core/persistence.py` | `config/app_state.json` | `{"version": "1.0.0", …}` (`AppState.version`) | `layout_state.save_arena_state` ← `Bridge._save_arena` (33 call sites) ← `feed.commit_queue`, `commit_urls`, `save_settings`, scan, presets… | `persistence.load_state` at `Bridge.__init__` | none strict; optional: `cooldowns` | no (local FS paths) | `progress`, `run_state`, `jobs[].status` in-flight, `images[].status` processing | `from_dict` tolerant (unknown URL keys dropped); folder shape normalized (`_folder_from_saved`) |
| 4 | `undo` | Undo History | `UndoStore` | `config/undo.json` | `{"history": [...], "index": n}`, cap 100 | `UndoStore.push/set` ← every editable surface | `ConfigManager.__init__` → `bridge.undo_service` | none | no | index position | `_clamp` repairs caps/index |
| 5 | `window_presets` | Window Layout Presets | `WindowPresetStore` | `config/window_presets.json` | `{"window_presets": {name: doc}}`, doc validated at load/apply via `window_preset_service` | `save_window_preset`, `import_window_preset`, `delete_window_preset` | `load_window_preset` (pure getter → JS preview/confirm/apply) | none (each preset grid-validated individually at apply) | no | no | grid payload inside each preset migrates via `canonical_grid_payload` |
| 6 | `arena_presets` | Arena/Feature Presets | `PresetStore` | `config/arena_presets.json` | `{"url_presets": [], "prompt_presets": {}, "settings_presets": {}, "arena_presets": {}}` | preset save slots (`blocks_library`, `arena-presets` JS store, `app_settings.export_preset` writes `config/<name>.json`) | corresponding load slots; `import_preset` (app_settings) | none | no | no | additive dict sections |
| 7 | `cooldowns` | Cooldowns & Tab Aliases | `cooldown_store.py` | `config/cooldowns.json` | `{"version": 1, "entries", "stats", "aliases"}` | `run_state.persist_cooldowns` (every pool push), `save_aliases`, `closeEvent` | `load_entries/load_stats/load_aliases`, `consume_entry_for` (tab→URL fallback) | optional dep target of `arena_state` | personal (`aliases[].email`) | **timers** (wall-clock; expired dropped on load), worker numbers | expired-idle + malformed dropped on load; `_VERSION=1` |
| 8 | `captcha_keys` | Captcha Solver Keys | `CaptchaKeyStore` | `config/captcha_solvers.json` | `{"provider", "solve_timeout_sec", "providers.{id}.{enabled, api_key}"}` | `set_captcha_api_key` | `CaptchaKeyStore.load` (Watcher solver) | none | **SECRET — export redacted presence only; raw export forbidden (RULE 20/I-29)** | balance (in `captcha_stats`) | legacy `2captcha.json` folded on first save |
| 9 | `captcha_stats` | Captcha Statistics | `CaptchaStats` | `config/captcha_stats.json` | counters + `per_site` (≤49+`*`) + `last_balance` | `record/set_balance/set_last_error` | `_load` (corrupt → blank) | none | no | `last_balance` (recomputed on demand after restore) | corrupt→blank, partial kept |
| 10 | `job_history` | Job History | `JobHistoryStore` | `config/job_history.json` | `{"next_job_no", "entries[]"}` cap 500 | append at the two settle sites (`multi_page_dispatcher._handle_result`, `batch_orchestrator.finish_image`), Clear, limit | `get_job_history` slot; `job_history_updated` push | none | no | tab identity columns resolve through live pool at render | shape-validated on load; `next_job_no` never reused |
| 11 | `captcha_recordings` | Captcha Session Recordings | `RecordingStore` | `config/captcha_recordings/<id>/` | per-session manifest+events+checkpoints | recorder lifecycle | Records window, comparison | none | sanitized but page-derived → **excluded by default** (optional-inclusion policy §D.3) | sessions "active" are stale after restart (recovered as interrupted by design) | retention/512 MiB cap self-manages |

**Explicitly out of scope for capture:** `logs/`, `output/*_AI` files and source images (RULE 14: outputs are filesystem truth; the workspace stores the *references* already inside `arena_state`), `config/uivision/` runtime (re-provisioned per run), Qt WebEngine profile/local storage.

### B.1 Write-path map (every path that mutates persisted state)

| Trigger | Path | Files touched |
|---|---|---|
| Any queue/URL/prompt/settings/folder mutation (33 sites) | slot → `Bridge._save_arena` → `layout_state.save_arena_state` → `persistence.save_state` (retry) + always re-emit | `app_state.json` |
| Queue funnel | `live/feed.commit_queue` → recalc → `_save_arena` → undo seam | `app_state.json`, `undo.json` |
| URL row commit | `url_queue.commit_urls` / `commit_urls_system` → persist + emit (+undo for user edits) | `app_state.json`, `undo.json` |
| Grid save / reset | `save_grid_layout` / `reset_grid_layout` → `config.set_state(grid_layout=…)` → `SessionStore.save` + undo push | `session.json`, `undo.json` |
| Window states | `save_window_states` → `set_state` + undo push | `session.json`, `undo.json` |
| Main-window geometry | `closeEvent` → `_save_window_geometry` → `set_state` | `session.json` |
| Preset save/delete/import (window + arena + prompt + settings + stack + custom blocks) | respective `PresetStore`/`WindowPresetStore`/`set_state` writes | `window_presets.json`, `arena_presets.json`, `session.json` |
| Cooldown autosave | every pool push: `Bridge._emit_pool_status` → `persist_cooldowns` → `save_pool_snapshot`; alias saves on join (`tab_owner`/`page_pool`); `page_pool.reset_stuck_page`-era `save_entries(...)` | `cooldowns.json` |
| Captcha key save | `set_captcha_api_key` → `CaptchaKeyStore.save` (+fold legacy) | `captcha_solvers.json`, (del `2captcha.json`) |
| Captcha stats | `record/set_balance/set_last_error` | `captcha_stats.json` |
| Job history | `_handle_result` / `finish_image` → append → save | `job_history.json` |
| Shutdown | `MainWindow.closeEvent` → geometry → `session/window_presets/undo/presets.save()` → `persist_cooldowns` → JS `SashGrid.flushPersistence()` (async, fire-and-forget) | `session.json` (+all above) |
| Export (feature-level) | `export_window_preset` (plain write — A.2.6), `export_preset` (atomic via `save_preset`) | user-chosen file / `config/<name>.json` |
| Import (feature-level) | `import_window_preset` (grid-validated), `import_preset` (sections restored through state) | → live stores |
| Crash recovery | none on disk today beyond atomic files; `_handle_interrupted` runs inside `reconcile_with_filesystem` | read-only repair of in-memory state |

**Race note for the save side (save.capture_all):** writers run on the UI thread, the bg asyncio loop (job settle), and the pool-push path. The workspace save must capture under `bridge._state_lock` (`live/feed.state_lock`) for `arena_state` and call each store's `save()`/`data()` under it; `SessionStore.data()` already deep-copies. Capture is **pull-based from live in-memory objects** (not file reads) to avoid torn mid-replace reads; file bytes for checksums are produced from the captured doc, serialized deterministically (see §D.1).

### B.2 Restore dependency graph and topological order

Persisted domains today are **mutually independent** (no domain strictly needs another file to be applied). The graph therefore has no strict edges in v1; the strict/optional machinery is defined and exercised by tests anyway:

```
session_settings ──(same-file contract)── grid_window        [shared physical file; grid applied last, per-key]
arena_state ──optional──> cooldowns        (restoring timers+aliases alongside the queue is nicer, never required)
arena_state ──optional──> undo             (history entries snapshot other domains' values; applied only on user undo, re-validated per kind at apply time)
captcha_stats ──optional──> captcha_keys   (balance line reads better with provider present; never required)
(window_presets, arena_presets, job_history, captcha_recordings): isolated
```

**Restore topological order (v1, fixed table):** `captcha_keys`(redaction report only) → `captcha_stats` → `cooldowns` → `arena_state` → `session_settings` → `grid_window` → `undo` → `window_presets` → `arena_presets` → `job_history`. Rationale: shared-file domain applies once (`session_settings` then `grid_window` re-opens and commits its keys); UI-affecting grid last within the file group; history domains last so a failing grid apply can still let presets restore.

Reserved example for future strict edges (documented, tested with a fake provider): if URLs were ever re-split into a native `urls.json`, `arena_state` would declare `{"urls": "strict"}` and a failed urls restore would skip the queue apply.

### B.3 Conflict report — duplicate ownership

| Conflict | Sources | Resolution (one writer wins) |
|---|---|---|
| Undo history | `undo.json` (live) vs `session.json.undo_history` (doc only) | `undo.json` is the **only** persisted source; session key does not exist in code. Workspace exports `undo.json` only. SoR doc fix in W10. |
| Settings keys split across two files | `app_state.json.settings` (AppSettings dataclass) vs `session.json` (`highlight.duration_seconds`, `watcher_*`, `cdp_*`, `cooldown_*`, `url_reconcile_interval_ms`, `firefox_auto`, watcher switch) | Per-key home table (§B row 1/3) — **each key has exactly one owner file today** (`save_settings` writes both sides but disjoint keys, e.g. `apply_highlight_duration` writes state+config for *different* fields). Workspace preserves each key inside its owning domain; never merges. |
| `run_state` | `app_state.json.run_state` vs `bridge._run_state` (memory) | L-2 rule: `supervisor.set_run_state` is the only writer of both. On restore, a non-idle persisted `run_state` is **forced to `idle`** + reported (reconcile step; never resurrect a run). |
| In-flight jobs / processing images | `app_state.json.jobs[]/images[]` | Restored values pass the `_handle_interrupted`-equivalent mapping (jobs → `interrupted`, processing images without live tabs → `pending`+selected via existing `feed.recover_stale_processing` at next start). |
| Grid/window keys inside session.json | `session_settings` vs `grid_window` (both target `session.json`) | Shared-file contract §C.4: one file, per-domain key ownership, one commit per file with per-domain key rollback. |
| Job counters | `cooldowns.json.stats` vs `PageInfo.jobs_completed` | File is source of truth; pool re-reads on join (`restore_page_stats`). Display-only (I-28). |
| Tab identity | `UrlRow.tab_id` (app_state) + `cooldowns.entries[].tab_id` + `aliases` | CDP target ids are session-scoped: restore keeps them as *hints*; the reconciler + `consume_entry_for` URL fallback re-bind at runtime. Aliases (numbers/emails) survive by tab id, else by URL. |

---

## C. Design (orchestrator over native stores) — summary; full ADR: `docs/archive/2026-09-25-global-workspace-save/adr-0001-orchestration-versioning-partial-restore.md`

### C.1 Package layout (respecting RULE 18 sizes; import direction ui → services → persistence/core)

```
app/persistence/workspace/     # pure + FS primitives, no Qt, no bridge
    errors.py                  # FailureStage taxonomy + WorkspaceError
    integrity.py               # sha256/size/safe-relative-path checks
    manifest.py                # build/parse/validate manifest.json (workspace_format 1)
    fsio.py                    # temp folder, manifest-last, atomic publish, copy fallback
app/services/workspace/
    provider.py                # StateProvider protocol + CaptureResult/ApplyOutcome dataclasses
    registry.py                # the ONE provider table (domain ids, RESTORE_ORDER, restore_order)
    reports.py                 # save-report/restore-report builders (pure, deterministic)
    meta.py                    # snapshot identity/env: paths, UTC, ids, app_meta, compat, log
    save.py                    # the whole SAVE side: SaveRequest, selection, capture under the
                               #   feed lock, validation, temp build, manifest-last, publish, meta
    restore.py                 # PREVIEW only (read-only): per-domain status rows + remap notes
    apply.py                   # the whole MUTATING side: selection + strict expansion, recovery
                               #   backup, file gates, per-domain transactions, reconcile, report
    providers/                 # one small file per domain (§B table), each ≤300 LOC

(2026-09-25 refactor: the planned coordinator.py/reconcile.py pair became
meta/save/restore/apply — the audit in WORKSPACE_REFACTOR_AUDIT.md §4; boundaries
otherwise exactly as designed. Provider modules import nothing from services.)
app/ui/panels/workspace.py     # 19th window mixin: slots only (thin)
app/ui/web/js/panels/workspace.js + workspace/{store,render,actions}.js
```

**Architecture tests** (new `tests/test_workspace_architecture.py`): `app/persistence/workspace/**` imports nothing from `app/ui*`/`app/services`; `app/services/workspace/providers/**` never imports `app/ui*`; provider modules never import meta/save/restore/apply; the services never import Qt.

### C.2 Provider contract (conceptual; Python `typing.Protocol`)

```python
class StateProvider(Protocol):
    domain_id: str            # stable, e.g. "arena_state"
    display_name: str         # e.g. "Queue, URLs, Folder, Prompt, Jobs"
    native_rel_path: str      # "state/app_state.json" ("" for redaction-only domains)
    schema_version: str       # native schema version captured
    supported_migrations: tuple[str, ...]   # older versions migrate() accepts
    dependencies: dict[str, str]            # {"cooldowns": "optional"} ; strict|"optional"
    sensitivity: str          # "public" | "personal" | "secret"
    derived_fields: tuple[str, ...]         # recomputed after restore
    def capture(self, bridge) -> CaptureResult: ...      # coherent doc + meta (snapshot boundary)
    def validate(self, data, entry) -> list[Problem]: ... # checksum/schema/semantic checks
    def migrate(self, data, from_version) -> tuple[data, str]: ...
    def plan(self, bridge, data) -> RestorePlan: ...      # fields that will change (preview)
    def apply(self, bridge, data) -> ApplyResult: ...     # transactional inside the domain
    def rollback(self, bridge, backup): ...               # last-known-good for THIS domain
    def reconcile(self, bridge) -> list[str]: ...         # derived/live recompute notes
```

### C.3 Snapshot boundary and capture

- Save takes `bridge._state_lock` (the queue funnel's lock) for the duration of `capture()` of `arena_state`; other stores are captured via their deep-copying accessors. Long-lived in-memory docs only — no re-read of files being concurrently replaced.
- Docs serialize deterministically (`json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True)`) — checksums and reports stay byte-stable across saves of identical state (test requirement).
- Captured file bytes are the **canonical serialization**, not the on-disk bytes: checksums verify *content*, and restore accepts any byte layout that parses to the same validated doc.

### C.4 Shared-file contract (`session.json`)

`session_settings` and `grid_window` both own keys inside one physical file. Ownership table (in `providers/session.py`, one constant): grid_window owns exactly `grid_layout`, `window_states`, `window_geometry`; everything else in `DEFAULT_SESSION` belongs to `session_settings`. The workspace exports **one** `state/session.json`. On restore: stage merged doc (incoming values for owned keys only; keys a domain doesn't own keep current live values — unknown incoming keys are preserved, never dropped, reported as `unowned_keys_kept`); validate grid sub-domain first (`canonical_grid_payload` + §C.6); if grid keys fail → **apply session_settings keys only**, skip grid_window, keep current layout, report; else apply both in one atomic file commit, grid last. Rollback restores the pre-apply values of the union of both domains' owned keys (captured before apply).

### C.5 Save algorithm (maps task SAVE 1–8)

1. Resolve target = `<base>/<name>_<UTC yyyyMMdd-HHMMSS>/`; refuse existing target (never merge into an existing folder).
2. Create sibling temp dir `<target>.tmp-<pid>`; per provider: `capture()` → deterministic bytes → immediate `validate()` (schema/semantic) → size+sha256.
3. Write each file into `state/` (atomic per-file write inside temp is unnecessary — the whole folder is unpublished — but bytes are fsynced where the platform supports it).
4. Write `reports/save-report.json`; write `metadata/app-environment.json` (redacted); write `manifest.json` **last** (its presence = commit marker).
5. Publish: `os.rename(temp, target)` (atomic, same volume). On `EXDEV`/cross-volume: copy tree to `<target>.copy-<pid>`, fsync, rename. Target exists mid-publish (crash between rename attempts) → keep temp, report.
6. On any provider capture/validate failure: exclude the domain, mark `required`-and-failed → abort with the temp folder **removed only after** user-visible error (retain `<target>.tmp-<pid>` renamed to `<target>.failed-<ts>` when removal fails — never delete on the error path silently).
7. Locks/access-denied (cloud sync): bounded exponential backoff on folder ops (5 tries, 0.05 s×2 — mirrors `_replace_with_retry`), then actionable error naming the path; previous snapshots untouched.
8. Never claim success if a required domain failed; partial snapshots only after explicit user confirmation (`allow_partial=true` → manifest marks `snapshot_kind: "partial"` with per-domain `excluded_reason`).

### C.6 Restore algorithm (maps task RESTORE 1–10)

1. `preview_restore(path)`: read **manifest only** → compatibility (workspace_format, app build range, per-domain native versions vs `supported_migrations`), per-file presence/size pre-check, sensitive exclusions, path-remap needs (folder root missing on this machine), migrations pending. No mutation.
2. User picks **Restore All** or selects domains/files. Selection by native file resolves **through the manifest** (path→domain lookup; unknown file → reported, never guessed).
3. Strict dependencies expand automatically; optional deps are shown as "will also restore / will skip".
4. **Recovery backup**: copy every affected live file into `config/workspace_recovery/<UTC ts>/` + `recovery.json` (domain→file). This is the last-known-good; not deleted automatically (bounded: keep last 10, prune oldest with a log line).
5. Per domain in topological order: safe-path check (no `..`, no absolute, resolves inside the workspace) → size+sha256 → JSON parse → schema version → semantic validation (provider `validate`) → compatibility → migration (pure, to in-memory doc; source snapshot never rewritten).
6. Stage: build the new in-memory/live doc, keep old values for rollback, then **commit atomically per domain** (per file `save_json_atomic`-equivalent with retry; shared session file = one commit §C.4).
7. Failure → record (stage, cause, expected-vs-actual) → skip strict dependents → continue independents → **no rollback of already-committed domains**.
8. `reconcile()`: progress recalc, forced `run_state=idle` (if incoming ≠ idle, reported), processing images without live tabs left for `recover_stale_processing`, job statuses → `interrupted`, pool/tab ids left to the reconciler, captcha balance marked stale, grid applied via the same `canonical_grid_payload` path the live slot uses.
9. Stale runtime states are converted, never resurrected (no job is re-enqueued as running; `run_state` non-idle → `idle`).
10. One final result (`success` / `success_with_warnings` / `failed`) + `reports/restore-report.json` written **into the workspace folder** (created if the folder is read-only → write beside it as `<name>.restore-report.json` and say so).

### C.7 Grid & window semantic validation (beyond `canonical_grid_payload`)

Existing checks (reused, never re-implemented): version + tree shape + depth ≤12 + sizes normalized to 100 with MIN 4 % + exact known window set + legacy id rename + missing-leaf migration. Added for restore: unknown-panel policy (report + apply canonical rename map; truly unknown leaf → drop leaf, never whole layout — mirroring the migration-append philosophy, reported); finite non-negative sizes (NaN/Inf → invalid); every *visible* panel reachable and ≥ 4 % usable; divider semantics untouched (already adjacency-only in sash-core — restore changes only stored sizes, never live divider math); geometry: validate ints>0, then clamp into `QApplication.primaryScreen().availableGeometry()` (Qt call lives in the **panel layer** wrapper passed into the provider as a callable — services stay Qt-free); multi-monitor mismatch → clamp + report `geometry_clamped`.

---

## D. Workspace folder + manifest schemas

### D.1 Folder contract

```
<name>_<UTC yyyyMMdd-HHMMSS>/            # e.g. my-setup_20260925-181500/
  manifest.json                          # written LAST; presence = committed snapshot
  state/
    session.json                         # native (session_settings + grid_window keys)
    app_state.json                       # native
    undo.json
    window_presets.json
    arena_presets.json
    cooldowns.json
    captcha_stats.json
    job_history.json
  reports/
    save-report.json                     # written during save
    restore-report.json                  # created/updated by any restore attempt
  metadata/
    app-environment.json                 # redacted app/platform env; no secrets, no session data
```

- Name/extension: folder is the unit (researched: a trailing dot-suffix folder name breaks Windows "keep extension" habits and adds nothing; manifest identifies the folder). Manifest carries `"format": "arena-workspace"`, `"workspace_format": 1` — restore refuses non-matching roots with a precise message instead of guessing.
- Human-inspectable native filenames; every file independently restorable via manifest lookup.

### D.2 manifest.json example

```json
{
  "format": "arena-workspace",
  "workspace_format": 1,
  "snapshot_id": "ws_20260925T181500Z_a1b2c3d4",
  "parent_snapshot_id": null,
  "name": "my-setup",
  "description": "before the firefox experiment",
  "snapshot_kind": "full",
  "created_utc": "2026-09-25T18:15:00Z",
  "updated_utc": "2026-09-25T18:15:00Z",
  "app": {"version": "1.0.0", "build": "f5cb06e", "platform": "Windows-11", "python": "3.12.4"},
  "compat": {"min_workspace_format": 1, "grid_version": 8, "app_build_range": [">=f000000", "<=zzzzzzz"]},
  "domains": {
    "arena_state": {
      "display_name": "Queue, URLs, Folder, Prompt, Jobs",
      "path": "state/app_state.json",
      "schema_version": "1.0.0",
      "supported_migrations": ["1.0.0"],
      "bytes": 48211,
      "sha256": "9f2c…",
      "required": true,
      "dependencies": {"cooldowns": "optional"},
      "sensitivity": "personal",
      "capture": {"ok": true, "notes": []}
    },
    "session_settings": {
      "path": "state/session.json", "schema_version": "1", "bytes": 8123, "sha256": "…",
      "required": true, "dependencies": {}, "sensitivity": "personal",
      "owns_keys": ["theme", "watcher_enabled", "cdp_port", "…"],
      "capture": {"ok": true, "notes": []}
    },
    "grid_window": {
      "path": "state/session.json", "pointer": {"keys": ["grid_layout", "window_states", "window_geometry"]},
      "schema_version": "8", "bytes_shared_with": "session_settings",
      "required": false, "dependencies": {}, "sensitivity": "public",
      "capture": {"ok": true, "notes": []}
    },
    "captcha_keys": {
      "path": "", "sensitivity": "secret",
      "capture": {"ok": true, "excluded": true,
                  "excluded_reason": "secret: redacted presence metadata in metadata/app-environment.json (RULE 20)"},
      "redacted_reference": {"providers": {"2captcha": {"present": true, "masked": "abcd****7890"},
                                            "capmonster": {"present": false, "masked": null}},
                              "solve_timeout_sec": 120}
    },
    "captcha_recordings": {
      "path": "", "capture": {"ok": true, "excluded": true,
                              "excluded_reason": "default-excluded: large page-derived evidence; opt-in policy (docs §D.3)"}
    }
  },
  "inclusion_policy": {"logs": "excluded:runtime", "source_images": "excluded:filesystem-truth",
                        "outputs_AI": "excluded:filesystem-truth", "recordings": "excluded:default-opt-in"}
}
```

Every registered provider appears — included with full entry, excluded with a reason. Checksums cover file bytes as written; `grid_window`/`session_settings` share the file entry (no double checksum).

### D.3 Optional-inclusion policies (documented, all opt-in, none default)

| Resource | Default | Opt-in behavior |
|---|---|---|
| `config/captcha_recordings/` | excluded (large, page-derived) | future flag copies sanitized sessions; size estimate shown first |
| `config/captcha_solvers.json` keys | excluded forever in v1 (redacted presence only) | encrypted secret export = separate future ADR (opt-in, passphrase KDF) — explicitly out of scope here |
| source images / `*_AI` outputs | excluded (RULE 14: filesystem truth; manifest stores references) | never |
| `logs/`, `config/uivision/` | excluded (runtime) | never |

### D.4 Report schemas (deterministic)

`save-report.json`: `{"snapshot_id", "started_utc", "finished_utc", "result": "success|partial|failed", "domains": [{domain_id, ok, excluded, bytes, sha256, error?}], "errors": [WorkspaceError…], "published": true}`.
`restore-report.json`: `{"workspace": "<path>", "restored": [ids], "skipped": [{"domain_id", "stage", "cause", "expected", "actual", "dependents_blocked": [ids], "recommended_action"}], "migrated": [{"domain_id", "from", "to"}], "reconciled": [notes], "result": "success|success_with_warnings|failed", "backup": "config/workspace_recovery/<ts>/"}`.
Failure stage enum (one vocabulary, `persistence/workspace/errors.py`): `missing | unsafe_path | checksum | parse | schema | semantic | migration | dependency | apply | reconcile | rollback`.

---

## E. Sequence diagrams

### E.1 Save

```
UI(win "Global Saving System")   Coordinator(services)        Providers                FS
  │ save_workspace(name, desc,     │                            │                      │
  │       domains, allow_partial)  │                            │                      │
  ├───────────────►│  lock bridge._state_lock                  │                      │
  │                │──capture()───────────────►│ per domain    │                      │
  │                │◄──docs + meta─────────────│               │                      │
  │                │──validate each (schema/semantic)          │                      │
  │                │──mkdir <t>.tmp-<pid>─────────────────────────────────────────────►│
  │                │──write state/*, reports/save-report.json, metadata/*─────────────►│
  │                │──write manifest.json LAST────────────────────────────────────────►│
  │                │──rename tmp→final (retry backoff; copy fallback)─────────────────►│
  │◄──result + save summary────────│ unlock                    │                      │
```

Failure at any shaded step leaves any previous snapshot intact; temp is renamed `*.failed-<ts>` on removal failure and named in the error.

### E.2 Restore

```
UI            Coordinator                         Providers                         FS
│ preview(ws) │                                    │                                 │
├────────────►│ read manifest only ───────────────────────────────────────────────────►│
│◄─preview: app/date/domains/missing/migrations/exclusions/remap-needs                 │
│ selection   │                                    │                                 │
├────────────►│ expand strict deps; list effects   │                                 │
│             │ backup affected live files → config/workspace_recovery/<ts>/ + recovery.json
│             │ for domain in topo order:          │                                 │
│             │  safe-path→checksum→parse→schema→semantic→compat→migrate (pure)        │
│             │  plan() → stage → apply() atomically (one commit per domain/file)      │
│             │  on error: record(stage) → skip strict dependents → continue        │
│             │ reconcile(): progress, run_state→idle, stale jobs→interrupted,        │
│             │              grid via canonical path, geometry clamp                  │
│             │ write restore-report.json into workspace folder                       │
│◄─result: Restored/Skipped/Migrated/Failed counts + warnings (file, stage, cause,     │
│          recommended action, Open-folder / Copy-details)                              │
```

---

## F. Corruption / dependency behavior matrix

| Incoming defect (domain X) | Stage | X | strict dependents of X | optional dependents / independents | User sees |
|---|---|---|---|---|---|
| File absent from folder | `missing` | skipped | skipped (reported) | restored | "X: state/app_state.json missing — restore it from the snapshot or skip" |
| Path escapes workspace (`../x`) | `unsafe_path` | skipped | skipped | restored | security warning + Copy details |
| Byte size or SHA-256 mismatch | `checksum` | skipped | skipped | restored | expected vs actual sha prefix, path |
| Truncated / invalid JSON | `parse` | skipped | skipped | restored | parse error position |
| Unknown future schema version | `schema` | skipped | skipped | restored | "saved by newer app (schema 9 > supported 8) — update the app" |
| Valid JSON, invalid content (e.g. urls not a list) | `semantic` | skipped | skipped | restored | which invariant failed |
| Migration raises | `migration` | skipped | skipped | restored | from→to, exception class |
| Dependency failed (strict) | `dependency` | skipped (dependent) | — | restored | chain X←Y explained |
| Apply raises mid-write | `apply` | **rolled back** to backup (transactional) | skipped | restored (never rolled back) | error + "recovered previous values" |
| Reconcile raises | `reconcile` | restored + flagged | — | — | warning with note |
| Rollback itself fails | `rollback` | marked `damaged`, recovery backup path surfaced | — | — | "open recovery folder" (never silent) |
| Capture raises (saving) | `capture` | domain excluded from the snapshot (still reported) | — (save continues) | save refusal lists failed domains; partial save allowed by explicit flag |
| Grid invalid (any of the above inside session.json) | any | grid keys skipped; session_settings keys still applied; **current layout retained** | — | restored | "layout not restored — invalid grid (reason). Apply default layout?" (explicit opt-in, never silent) |
| Unknown file in `state/` | — | not applied | — | — | "unknown file — no domain owns it" (never inferred by filename) |

Default substitution never happens implicitly; "restore defaults for X" is a separate user-approved action.

---

## G. Migration and rollback plan

- **Versioning:** workspace_format starts at 1 (min 1). Each domain records its native `schema_version` at capture; providers declare `supported_migrations`. Future versions: restore refuses with precise message (no best-effort guess). Older supported versions: pure `migrate()` to current in-memory doc — **never rewrites the snapshot on disk**.
- **Unknown-field preservation:** provider `validate` flags unknown keys as `kept_unknown` (they ride through apply for `session_settings`/`arena_state` because their loaders are already tolerant); providers with strict dataclasses (`grid_window` keys) drop unknown keys **with a report line**, documented per provider.
- **Duplicate sources of truth:** per §B.3 — the per-key home table decides; nothing "loads whichever file is newest".
- **Rollback layers:** (1) domain-level: pre-apply values of owned keys/files, applied on `apply` failure; (2) snapshot-level: `config/workspace_recovery/<ts>/` full copies of every affected file, surfaced in the report and in the window's "last recovery" line; (3) app-level: every commit reuses the existing atomic writers, so a crash mid-commit leaves the previous valid file (temp discarded).
- **Stable IDs:** app-owned ids (`UrlRow.id`, image `id`/fingerprint, preset names, `snapshot_id`) persist verbatim; session-scoped ids (CDP `tab_id`, `worker_no`) restore as hints only and are reconciled by the existing join/reconcile machinery.

---

## H. Test and fault-injection plan (all on temporary dirs; none touch real `config/`)

Existing behavior locks to build on: `tests/test_persistence.py` (roundtrip, atomic-write, preset, reconcile, empty-state), `tests/unit/test_json_store.py`, `tests/unit/test_config_manager.py`, `tests/unit/test_undo_store.py`, `tests/unit/test_preset_store.py`, `tests/unit/test_cooldown_store_edges.py`, `tests/test_cooldown_store.py`, `tests/test_grid_layout.py`, `tests/test_layout_service_full.py`, `tests/test_layout_state.py`, `tests/test_window_catalog.py`, `tests/test_job_history.py`, `tests/test_captcha_key_store.py`, `tests/test_captcha_stats.py`, `tests/test_repo_hygiene.py`, `tests/js/test_window_presets.mjs`, `tests/js/test_sash_core.mjs`, `tests/characterization/` (batch goldens).

| New suite (file) | Covers |
|---|---|
| `tests/test_workspace_characterization.py` (W1) | golden round-trips of every current store as-is (capture→bytes→parse→semantic→plan→apply on a fake bridge reproduces identical docs) — characterization BEFORE any provider refactor |
| `tests/unit/workspace/test_manifest.py`, `test_integrity.py`, `test_fsio.py` (W2) | manifest build/parse/refusals; sha/size/safe-path; temp publish, rename fallback, crash-before-manifest (no folder), crash-after-manifest (valid snapshot) |
| `tests/test_workspace_save.py` (W3–W4) | full save round trip; deterministic bytes (two saves of unchanged state → identical sha); required-domain failure aborts; partial only with `allow_partial`; backoff on injected `PermissionError`/`OSError(EACCES)`; previous snapshot untouched on failure |
| `tests/test_workspace_restore.py` (W5) | preview correctness (no mutation assert); restore all; one-domain partial; multi-domain partial; corrupt-JSON-in-one-file while independents restore; checksum mismatch; missing file; unknown file; path traversal; unsupported future version; failed migration; failed apply → per-domain rollback + dependents skipped + independents kept; strict-dependency skip chain; interrupted save before/after manifest commit; recovery backup created and surfaced |
| `tests/test_workspace_grid.py` (W6) | malformed grid, missing panel id, GRID_VERSION older/newer, NaN/oversize sizes, monitor change (fake screen rect), adjacent-divider invariants untouched, invalid grid → current layout retained + explicit default offer |
| `tests/test_workspace_live.py` (W6) | stale `processing` job, stale `run_state` running, stale target id/tab_id, missing source folder, moved-folder remap report; balance marked stale |
| `tests/test_workspace_secrets.py` (W7) | no `api_key` material anywhere in exported tree (scan bytes); redacted metadata shape; recordings excluded by default; deterministic reports (byte-equal for same inputs) |
| `tests/test_workspace_architecture.py` (W3) | import-direction locks (§C.1) |
| `tests/js/test_workspace_panel.mjs` (W8) | window boots in `_PANEL_INITS` order; Save/Restore/Save As/quick-load buttons hit slots; preview → confirm → report rendering; checklist interactions; warnings show path+stage+Open-folder |
| fault-injection lanes | `monkeypatch`ed `os.replace`/`Path.rename` raising `EACCES` sequences; a fake strict-dependent provider exercises dependency skipping without touching real domains |

Cross-version fixtures: `tests/fixtures/workspace/v1/*.json` golden manifests (current + one synthetic older schema per versioned domain) — restore must accept or refuse with exact reasons.

---

## I. Phased implementation plan (independently committable; each step green under `bash tools/pre_push_check.sh`)

| Phase | Content | Gate |
|---|---|---|
| **W0** (this doc) | design + ADR + docs index; approval | review |
| **W1** | characterization tests for all 10 stores (behavior lock, zero production change) | new tests pass on untouched code |
| **W2** | `app/persistence/workspace/` errors/integrity/manifest/fsio + unit tests | pure, no wiring |
| **W3** | provider protocol + registry + first providers (`arena_state`, `undo`, `session_settings`, `grid_window`) capture-only; coordinator.save to temp; architecture tests | save-to-temp works headless |
| **W4** | atomic publish + backoff + save-report + interrupted-save semantics; retry hardening moved into `json_store.save_json_atomic` (behavior-preserving; unblocks cooldowns.json access-denied class) | existing suites unchanged-green |
| **W5** | restore: preview, validation pipeline, per-domain transaction, recovery backup, restore-report, partial restore by domain/file | fault matrix green |
| **W6** | grid/window provider semantic validation + geometry clamp seam; live-state reconcile suite | grid tests green |
| **W7** | remaining providers: `window_presets`, `arena_presets`, `cooldowns`, `captcha_stats`, `job_history`, `captcha_keys` (redaction-only), `captcha_recordings` (excluded-by-policy); secret-scan tests | full-domain matrix green |
| **W8** | UI: 19th window `workspace` ("Global Saving System") — GRID_VERSION 8→9, `window_catalog` row + JS mirrors, slots (save/restore/restore-selected/save-as/recent/last-good), preview & result screens; `test_bridge_slots` + `test_window_catalog` extended in same commit | python + JS suites green |
| **W9** | convergence: feature-level `import_preset` / window-preset import routed through provider validators/migrators; recent-snapshots quick-load buttons | behavior-equivalence tests |
| **W10** | fault-injection + cross-version fixture suite; SYSTEM_OF_RECORD rows (§2 row "Workspace save", storage map §6, invariants); docs index; archive this design per RULE 17 | full pre-push + coverage floors |

No behavior change lands in W1–W7 (additive only); W4's json_store retry and W8's window addition are the only user-visible deltas, each with its own tests.

---

## J. AGENT_RULES compliance checklist (this phase)

- [x] RULE 13 — grid validation reused (`canonical_grid_payload`), invalid restore keeps current layout, explicit default offer only.
- [x] RULE 16 — every phase lands with `verify_quality --changed --allow-legacy` + pytest + coverage ≥ baseline floors (line 84.46 %/branch 80.27 %); new modules sized to RULE 18 (files ≤300, functions ≤20, CC ≤10).
- [x] RULE 17 — ADR + post-approval archive plan; `docs/README.md` index updated (same commit); SoR rows updated only when behavior lands (W10).
- [x] RULE 18 — package split §C.1 (module = 2 dirs × ≤10 files; this doc's size deviation noted at top).
- [x] RULE 20 / I-29 — captcha keys never exported; redacted presence metadata only; encrypted export deferred to a separate opt-in ADR.
- [x] RULE 23 — all writes atomic; snapshot publish manifest-last + rename; interrupted saves keep previous snapshot usable.
- [x] RULE 10 — one provider table (`registry.py`), one manifest builder, one report vocabulary; no second window-id list (reuses `window_catalog`).
- [x] RULE 12 — undo restored through `UndoStore` unchanged; undo history remains one timeline (restore does not create parallel histories).
- [x] I-43 — workspace snapshots are user-chosen folders outside `config/`; `config/workspace_recovery/` joins the runtime-data family already covered by `config/*` git-ignore + `test_repo_hygiene.py`.
- [x] RULE 8 — every new function tested via real store objects + temp dirs; fault injection through real `OSError`s, not mocks of the code under test.

---

## K. Rejected alternatives (summary; full reasoning in the ADR)

1. **One giant `AppState`/one giant JSON** — violates orchestrator rule, couples every feature to one schema migration, reintroduces the god-service the repo spent Areas A–C removing.
2. **Zip archive instead of a folder** — kills per-file human inspection and single-file restore; worse diffability; no benefit at this scale.
3. **Copy-the-whole-config-dir** — would sweep secrets (`captcha_solvers.json`), runtime noise, recordings; no per-domain metadata; violates rules 3/6.
4. **SQLite/registry/central DB** — repo is deliberately JSON-only (SoR §6); a DB adds a second source of truth.
5. **Export secrets encrypted by default** — key management (where does the passphrase live?) outweighs v1 value; redacted-presence + separate opt-in ADR chosen.
6. **Filesystem watchers/continuous autosave of workspaces** — collides with the existing per-mutation autosave (write-path map §B.1); explicit snapshots + existing autosave cover recovery; avoid duplicate-write races (task integration phase 6).
7. **Restore-by-filename inference** — explicitly forbidden; manifest lookup only.

## L. Implementation addendum — post-restore LIVE refresh (2026-09-25, owner bug fix)

Owner report: "save checkpoint → change settings → Restore — nothing is
rewritten; all params stay the same". Root cause: restore correctly rewrote
the stores/files, but nothing pushed the restored state to the LIVE app —
every panel kept rendering pre-restore values, and the next Settings save
clobbered the restore right back. Three live consumers also kept stale data:
the watcher (its own config copy), the page pool (its own cooldown timers,
which it periodically re-persists over `cooldowns.json`), and the sash grid
(JS held its own tree). Fix, layered per the import-direction rules:

1. `panels/workspace.py` `_post_restore_refresh` — after a successful restore
   the bridge's OWN emitters re-push restored state: `arena_state_updated`
   (queue/urls/settings payload), `undo_state_changed`, `job_history_updated`,
   window/arena preset list signals. Failures become report notes, never silent.
2. Provider `reconcile` (services, Qt-free): `session_settings` re-applies the
   watcher keys into the live watcher via `update_config`; `cooldowns` re-applies
   restored timers/counters into the live pool via `restore_cooldown_entry` /
   `restore_page_stats` (never shortens a live timer; unpooled tabs pick the
   file up when they connect).
3. `panels/workspace.js` after the restore reply: fetches `get_arena_state` and
   re-renders UrlList/ImageQueue/Progress/**Settings**; re-applies the restored
   grid through `SashCore.deserialize` + the same render/persist path a window
   preset uses; reloads the cooldown/watcher config inputs; refreshes preset
   lists. Restore All/Selected with no pending preview now auto-loads the last
   snapshot, and with no snapshot at all shows a visible refusal — never a
   silent no-op.

Pinned by `tests/test_workspace_live_refresh.py` (the owner's exact scenario
through the real `save_settings` slot) and four node tests in
`tests/js/test_workspace_panel.mjs`.

## M. LIVE-SYNC RULE (owner directive 2026-09-25 → AGENT_RULES RULE 24)

Restore (and every other value mutation) must leave the UI current in the same
tick — "visible after restart" is a bug. Refresh points after a workspace
restore (`panels/workspace.js wsAfterRestore`):

| Restored domain | Live refresh |
|---|---|
| arena_state | `get_arena_state` → re-render UrlList, ImageQueue, Progress, **Settings**, **PromptEditor**, **FolderPicker**; `arena_state_updated` + `progress_updated` signals drive UrlInterval and the queue header |
| grid_window | `SashCore.deserialize` → live grid render/persist (validate/migrate, RULE 13) |
| session_settings | Watcher `loadConfig`, cooldown config reload, **CDP/browser config reload (`loadCDPConfig`)**, **Firefox-auto `load()`** |
| cooldowns | cooldown config reload + pool reconcile (§L) |
| undo / job_history | `undo_state_changed` / `job_history_updated` pushes (limit mirror rides the payload) |
| window_presets / arena_presets | list re-pull (`WindowPresets.refresh`, presets signal) |
| captcha_stats | Captcha window `refresh()` |

Anything added in the future that renders a persisted value MUST be added to
these refresh points (RULE 24). "Load" links in the recent-snapshots list go
through the same preview → Restore All/Selected flow as Browse…
