# Global Save/Restore Refactor — Audit + Design

Date: 2026-09-29
Branch: `arena/01a0e9c1-process-images-in-areana` (base `origin/main`)
Scope: `app/services/workspace/` (11 files + 8 providers), `app/persistence/workspace/` (5 files), seam `app/ui/panels/workspace.py`
Out-of-scope: legacy unrelated changes in branch diff (action_blocks, naming, js panels, browser) — do not touch.

> Process: Understand → Research/Design (this doc) → TDD refactor per AGENT_RULES RULE 16/18/19. No implementation yet in this doc.

## 1. Code Map

### 1.1 Module responsibilities (as built)

```
app/persistence/workspace/
  errors.py        — WorkspaceError + STAGES vocabulary (12 stages) + recommended_action map
  integrity.py     — canonical_bytes, sha256, bytes_entry/doc_entry, safe_rel_path, file_sha, drive_like
  manifest.py      — build_manifest(header, app_meta, compat, domains), check_format, parse_manifest, read_manifest, entry_for
  fsio.py          — sanitize_name, snapshot_dir_name, new_temp_dir, write_bytes, write_report, copy_tree, publish (rename or copy+rename), _with_backoff, remove_tree
  __init__.py      — re-export

app/services/workspace/
  provider.py      — CaptureResult, ApplyOutcome, StateProvider base (class attrs = manifest metadata), config_dir(), read_live_json() -> (doc, cause), live_capture()
  registry.py      — RESTORE_ORDER tuple, _TABLE built at import, restore_order(ids), get(domain_id), all_providers()
  meta.py          — default_base, utc_now_iso, snapshot_id_for, app_meta, _build_sha (git), compat_block, log_message, live_run_error; META_FILE, DEFAULT_DIR_NAME, RECENT_CAP
  snapshot_index.py— _meta_path, _read_meta, _write_meta, record_snapshot, record_restore, recent_snapshots (with prune side-effect), last_snapshot, last_restore
  reports.py       — SAVE_RESULT_*, RESTORE_*, save_report(timing, domains, errors, published), restore_result(restored, skipped), restore_report(workspace, outcomes, backup), preview_report(root, manifest, domains, remap)
  recover.py       — _recovery_dir (local time), _copy_live_file, _affected_files, _copy_affected, _fill_backup, backup_live -> (path, refusal), prune_recovery
  gates.py         — load_files(root, manifest, providers) dedup by rel, load_one, _gated (safe→size→sha→parse), entry_owner
  restore.py       — preview only: _inside, _row_head, _file_status, _preview_row, preview_restore(root) -> manifest + domains + remap, _folder_root, _remap_notes
  save.py          — SaveRequest, Capture, selected_providers, capture_one, capture_all (state_lock), file_docs (merge shared file), _capture_block, domain_entries, _write_state_files, inclusion_policy, _write_env, _report_rows, save_workspace (capture→target→publish), _abort_result, _stage, _publish_save(run dict), _snapshot_manifest, _publish_failed
  apply.py         — mutating restore: _selected_ids, selection_providers, _strict_deps, expand_strict, _skip_row, _guarded, _version_row, _policy_row, _rollback, _apply_domain, _dependency_row, _migrated_doc, _checked_doc, _restore_one, _restore_row, _preflight, restore_workspace, _log_result, _finish, _reconcile_all
  providers/
    arena_state.py   — AppState.to_dict/from_dict, swap_state, semantic_error (_list, _images), ArenaStateProvider (required, personal)
    captcha_stats.py — stats_file, stats_error, CaptchaStatsProvider (JsonFileProvider pattern)
    cooldowns.py     — cooldown_file, sections_error, CooldownsProvider + reconcile re-apply into live pool
    job_history.py   — history_error, JobHistoryProvider
    policies.py      — CaptchaKeysProvider (secret, excluded), RecordingsProvider (excluded), INCLUSION_POLICY, KEYS_EXCLUDED, etc.
    preset_stores.py — _StoreProvider base, WindowPresetsProvider, ArenaPresetsProvider
    session.py       — _SessionDomainProvider base, SessionSettingsProvider, GridWindowProvider (shared file session.json, GRID_KEYS), settings_keys(), grid_error, filter_window_states
    undo.py          — UndoProvider

app/ui/panels/workspace.py — WorkspaceMixin slots: get_workspace_state, save_workspace, preview_workspace, restore_workspace, browse_workspace_folder, open_workspace_path; helpers _options, _state_payload, _do_save, _do_restore, _answer, _emit_refresh, _post_restore_refresh, _dialog_folder, clamp_to_screen, clamp_restored_geometry; REFRESH_TABLE
```

### 1.2 Dependency direction (pinned)

`persistence/workspace` = stdlib only
`services/workspace` → `persistence/workspace` + `app.core`, `app.persistence.json_store`, `app.services.*` (never `app.ui*` — pinned by `tests/test_workspace_architecture.py`)
`ui/panels/workspace.py` → `services/workspace` (thin delegation, no logic duplication)
Providers own native formats, never re-serialize into unified model (task rule).

### 1.3 File sizes (current)

- save.py 235 LOC, apply.py 276 LOC (largest), restore.py 101, meta.py 79, snapshot_index.py 69, reports.py 69, registry.py 51, gates.py 64, recover.py 102, provider.py 106, fsio.py 133, manifest.py 84, integrity.py 64, errors.py 63, workspace panel 185.
- providers: arena_state 108, captcha_stats 52, cooldowns 98, job_history 53, policies 76, preset_stores 76, session 198, undo 55.

Total ~1550 LOC for feature.

## 2. Code Smells — exact files/symbols/evidence

### S1 — Untyped `run` dict bundling in save.py (Primitive Obsession)

- **File:** `app/services/workspace/save.py`
- **Symbols:** `save_workspace` line ~113 builds `{"bridge": bridge, "request": request, "target": target, "started": started}` then `_publish_save(run: dict, captures)` and `_stage(run: dict, captures, temp)` and `_snapshot_manifest(run: dict, captures, report)`
- **Evidence:** `run["file_entries"] = _write_state_files(...)` mutates dict inside `_stage`; no type checker can catch missing key; tests must guess shape. Violates RULE 18 ideal function 4–20 lines with clear params — here 4 values hidden in one dict, param count gamed to 1 but complexity remains.
- **Impact:** Hard to test `_stage` in isolation, easy to miss key.

### S2 — Tuple (value, error) returns everywhere (no Result type)

- **Files:** `provider.py:read_live_json -> tuple`, `recover.py:backup_live -> tuple[str, str]`, `manifest.py:read_manifest -> tuple[dict|None, str|None]`, `apply.py:_guarded -> tuple[value, None|row]`, `apply.py:_checked_doc -> tuple[doc, note, None] or (None, "", problem)`, `apply.py:selection_providers -> tuple[providers, unknown]`
- **Evidence:** `doc, cause = read_live_json(path)` then `if cause:`; `backup, backup_refusal = backup_live(...)` then `if backup_refusal:`; `_checked_doc` returns 3-tuple positional, caller unpacks `doc, migrated_note, problem = _checked_doc(...)`. No dataclass, no named fields.
- **Impact:** Caller can swap order, miss check, silent bug. Violates RULE 16 complexity — cognitive load.

### S3 — Module-level side effects in registry.py

- **File:** `app/services/workspace/registry.py`
- **Symbols:** `_TABLE` built at import loop over `_cls in (CaptchaKeysProvider, ...)`, `RESTORE_ORDER` tuple separate from classes.
- **Evidence:** Adding new provider requires editing import list AND tuple; if import fails, registry silently incomplete. `all_providers()` rebuilds list via `get` each call.
- **Impact:** Drift risk, hard to test registry in isolation, import-time IO.

### S4 — Getter with write side-effect in snapshot_index.py

- **File:** `app/services/workspace/snapshot_index.py`
- **Symbols:** `recent_snapshots(bridge, limit)` reads meta, filters missing paths, then `_write_meta` if pruning needed.
- **Evidence:** Line ~48-51: `if len(kept) != len(meta.get(...)): meta["recent"]=kept; _write_meta(...)` inside a function named `recent_snapshots` (getter). Also `last_snapshot` reads without pruning, inconsistency.
- **Impact:** Unexpected IO during read, test must mock filesystem for getter, violates command-query separation.

### S5 — apply.py is a god-module (276 LOC, 16 helpers, mixed concerns)

- **File:** `app/services/workspace/apply.py`
- **Symbols:** `_selected_ids`, `selection_providers`, `_strict_deps`, `expand_strict`, `_skip_row`, `_guarded`, `_version_row`, `_policy_row`, `_rollback`, `_apply_domain`, `_dependency_row`, `_migrated_doc`, `_checked_doc`, `_restore_one`, `_restore_row`, `_preflight`, `restore_workspace`, `_log_result`, `_finish`, `_reconcile_all`
- **Evidence:** Single file owns selection, dependency expansion, file gates orchestration, per-domain transaction, rollback, reconcile, logging, report writing. `restore_workspace` does backup + load_files + loop + finish + log. CC of `_restore_one` ~6 but cognitive high due to 4 gates in sequence. Violates RULE 18 file ideal 150–300 (at upper bound) and module cohesion.
- **Impact:** Hard to reason about transaction boundaries, hard to unit test `_restore_one` without full manifest.

### S6 — Duplicated JsonFileProvider pattern across 5 providers

- **Files:** `providers/captcha_stats.py`, `cooldowns.py`, `job_history.py`, `preset_stores.py`, `undo.py`, `session.py`
- **Symbols:** Each implements `live_paths -> _one_file(path)`, `capture -> live_capture(path)` or `CaptureResult(ok=True, doc=store.all_data())`, `apply -> save_json_atomic(path, doc)`.
- **Evidence:** `captcha_stats.py` lines 30-40 vs `job_history.py` 27-38 identical structure; `preset_stores.py` `_StoreProvider` duplicates `session.py` `_SessionDomainProvider` but slightly different (one uses `bridge.config.*.path`, other uses `bridge.config.session`). Copy-paste risk.
- **Impact:** Maintenance burden, bug fix must be applied N times.

### S7 — Shared-file merge via dict spread without enforcement

- **File:** `app/services/workspace/save.py`
- **Symbols:** `file_docs(captures)` line ~58: `docs[rel] = {**docs.get(rel, {}), **doc} if isinstance(doc, dict) else doc`
- **Evidence:** `session_settings` and `grid_window` share `state/session.json`; merge uses spread, last writer wins. No check that keys are disjoint; if future provider adds overlapping key, silent overwrite. Comment says "shared file with session_settings (one state/session.json)" but not enforced.
- **Impact:** Data loss risk, hidden coupling.

### S8 — safe_rel_path inconsistency between preview and gates

- **Files:** `restore.py:_inside` and `gates.py:_gated` + `integrity.py:safe_rel_path`
- **Symbols:** `restore.py:_inside` checks `safe == rel` (exact match), `gates.py:_gated` checks `not safe or rel != safe`. `integrity.py:safe_rel_path` returns "" for unsafe, but callers treat "" vs None differently.
- **Evidence:** Preview uses `_inside` to decide `unsafe_path` status; gates uses same rule but also does size/sha checks. Duplicated logic, two places to fix if rule changes.
- **Impact:** Security: path traversal handling must be identical.

### S9 — provider.py mixes utilities + contract

- **File:** `app/services/workspace/provider.py`
- **Symbols:** `config_dir`, `read_live_json`, `live_capture` top-level functions plus `CaptureResult`, `ApplyOutcome`, `StateProvider`.
- **Evidence:** `config_dir` is filesystem path helper, not provider contract; `read_live_json` is IO helper used by 3 providers but lives in provider contract file. `StateProvider` uses `NotImplementedError` not ABC.
- **Impact:** Import direction: `meta.py` imports `config_dir` from `provider.py` with comment "re-exported: the one home is provider.py (providers may not import meta)" — confusing indirection, circular reasoning.

### S10 — Time handling inconsistency (UTC vs local)

- **Files:** `meta.py:utc_now_iso` uses `time.gmtime()`, `fsio.py:snapshot_dir_name` takes `utc_struct` param, `recover.py:_recovery_dir` uses `time.strftime("%Y%m%d-%H%M%S")` local time.
- **Evidence:** `recover.py` line 21 uses local time for recovery folder name, while save uses UTC. Sorting of recovery folders uses lexicographic local time, may misorder across DST.
- **Impact:** Minor but violates principle of one time source.

### S11 — Logging swallows exceptions, no structured logger

- **Files:** `meta.py:log_message`, `snapshot_index.py:_write_meta`, `fsio.py:write_report`
- **Symbols:** `log_message` try/except pass; `_write_meta` logs warning on OSError but continues; `write_report` returns note string on failure.
- **Evidence:** `log_message` catches Exception and passes silently; if bridge._log itself fails, no fallback. `write_report` tries in-place, then beside folder, then in-UI only — but returns string note that caller must remember to include in report.
- **Impact:** Silent failures, hard to debug.

### S12 — Naming confusion: restore.py is preview, apply.py is mutating restore

- **Files:** `restore.py` (preview only) and `apply.py` (mutating restore)
- **Evidence:** `restore.py` docstring says "manifest-only PREVIEW", `apply.py` says "whole MUTATING side". Public API: `ws_restore.preview_restore` and `ws_apply.restore_workspace` — caller must know which module to import. Tests import both.
- **Impact:** Discoverability, onboarding cost.

### S13 — `reports.py` returns plain dicts, no schema

- **File:** `app/services/workspace/reports.py`
- **Symbols:** `save_report`, `restore_report`, `preview_report` return dicts built via `{**timing, "result": ...}`.
- **Evidence:** No dataclass, no validation; `timing` dict must contain `snapshot_id/started_utc/finished_utc` but not enforced. `restore_result` has edge: `if (not restored and skipped) or any(damaged)` → failed; if both empty, returns success (should be failed?).
- **Impact:** Typos in keys not caught, report shape drift.

### S14 — `workspace.py` UI panel mixes pure and impure

- **File:** `app/ui/panels/workspace.py`
- **Symbols:** `_do_save` does `str(opts.get("name") or "workspace")` — if opts["name"] is 0, becomes "workspace"; `_do_restore` calls `clamp_restored_geometry` + `_post_restore_refresh` even when restore result is failed; `_emit_refresh` uses `lambda e=emit: e(bridge)` double lambda.
- **Evidence:** `_options` parses JSON with try/except returning {} on garbage — silent. `clamp_to_screen` pure but `clamp_restored_geometry` imports QApplication inside try. `REFRESH_TABLE` is tuple of lambdas closing over bridge.
- **Impact:** Hard to test UI logic without Qt.

### S15 — `fsio.py` publish race and sanitization

- **File:** `app/persistence/workspace/fsio.py`
- **Symbols:** `sanitize_name` allows spaces, `publish` raises FileExistsError if target exists but check-then-act race, `_publish_by_copy` uses pid in staged name but not unique enough for concurrent saves.
- **Evidence:** `if target.exists(): raise FileExistsError` then `_rename`; between exists check and rename, another process could create target. `sanitize_name` keeps spaces, which may be problematic on Windows.
- **Impact:** Low, but robustness.

## 3. Severity / Risk

| # | Smell | Severity | Risk if not fixed | Effort |
|---|-------|----------|-------------------|--------|
| S1 | run dict bundling | **High** | Silent key error, untestable | S |
| S2 | tuple returns | **High** | Wrong unpack, missed error check → data loss | M |
| S3 | registry import side-effects | **Medium** | Drift, incomplete registry | S |
| S4 | getter with write | **Medium** | Unexpected IO, test flakiness | S |
| S5 | apply.py god-module | **High** | Transaction boundary unclear, partial restore inconsistency | M |
| S6 | duplicated JsonFileProvider | **Medium** | Copy-paste bugs, maintenance | S |
| S7 | shared-file merge | **Medium** | Overwrite, data loss | S |
| S8 | safe_rel_path dup | **Medium** | Security inconsistency | S |
| S9 | provider.py mixing | **Low** | Import confusion | S |
| S10 | time inconsistency | **Low** | Sorting bug, DST | S |
| S11 | logging swallow | **Low** | Silent failure | S |
| S12 | naming confusion | **Low** | Onboarding | S |
| S13 | reports dict no schema | **Medium** | Shape drift, typo | M |
| S14 | UI panel mixing | **Low** | Testability | S |
| S15 | fsio race | **Low** | Race on concurrent save | S |

Overall risk if not refactored: medium-high for transaction correctness (S5, S1, S2), medium for maintainability (S6, S3).

## 4. Proposed Interfaces / Boundaries (only where reduces duplication/coupling)

### 4.1 Keep — do NOT introduce speculative abstractions

- Keep `StateProvider` as is (class attrs = manifest metadata) — it's the one home per task rule 1. No second schema.
- Keep `WorkspaceError` vocabulary — it's pinned by tests.
- Keep file format, manifest JSON shape, report JSON shape — compatibility must be preserved.
- Keep provider's native format ownership — no unified model.

### 4.2 New small abstractions (justified)

#### A — `JsonFileProvider` base (reduces S6)

```python
# app/services/workspace/providers/_base.py (new, <60 LOC)
class JsonFileProvider(StateProvider):
    file_name: str = ""  # override or override file_path()
    def file_path(self, bridge) -> Path: ...
    def live_paths(self, bridge) -> list[Path]: return self._one_file(self.file_path(bridge))
    def capture(self, bridge) -> CaptureResult: return live_capture(self.file_path(bridge))
    def apply(self, bridge, doc) -> ApplyOutcome:
        save_json_atomic(self.file_path(bridge), doc)
        return ApplyOutcome(ok=True)
```

Providers `captcha_stats`, `job_history`, `cooldowns` inherit this, only override `validate` and `file_path`. `preset_stores` and `session` keep their own base because they use ConfigManager stores, not raw file.

**Justification:** 3 providers identical, 2 more similar — extraction reduces duplication, not speculative (already exists as `_StoreProvider` and `_SessionDomainProvider`).

#### B — `SaveRunContext` + `RestoreRunContext` dataclasses (fixes S1, S2)

```python
@dataclass(frozen=True)
class SaveRunContext:
    bridge: Any
    request: SaveRequest
    target: Path
    started_utc: str
    file_entries: dict = field(default_factory=dict)  # populated during stage

@dataclass
class RestoreRunContext:
    bridge: Any
    manifest: dict
    files: dict  # rel -> doc | WorkspaceError
    failed: set[str] = field(default_factory=set)
```

Replace `run: dict` in save.py and `run: dict` in apply.py. Typed, testable.

#### C — Result dataclasses (fixes S2)

```python
@dataclass(frozen=True)
class BackupResult:
    path: str
    refusal: str = ""
    @property
    def ok(self) -> bool: return not self.refusal

@dataclass(frozen=True)
class ManifestRead:
    manifest: dict | None
    error: str | None
    @property
    def ok(self) -> bool: return self.error is None
```

Replace tuple returns in `backup_live`, `read_manifest`, `read_live_json` (keep backward compat wrapper returning tuple for 1 step, then migrate callers).

#### D — `SnapshotIndex` class (fixes S4)

```python
class SnapshotIndex:
    def __init__(self, bridge): self._bridge = bridge; self._path = config_dir(bridge)/META_FILE
    def read(self) -> dict: ...
    def write(self, meta: dict) -> None: ...
    def record_snapshot(self, path: str) -> None: ...
    def record_restore(self, root: str, result: str) -> None: ...
    def recent(self, limit: int) -> list[str]:  # pure read, no write
    def prune_missing(self) -> int: ...  # explicit command, called by UI or save
    def last_snapshot(self) -> str: ...
```

`recent_snapshots` becomes pure, `prune_missing` explicit. Existing module-level functions delegate to class for compatibility.

#### E — `RecoveryService` (fixes S10, S2)

```python
class RecoveryService:
    def __init__(self, bridge): ...
    def backup(self, providers: list) -> BackupResult: ...
    def prune(self) -> None: ...
    def _recovery_dir(self) -> Path:  # uses utc_now_iso, not local time
```

Unifies time handling, returns `BackupResult`.

#### F — Split `apply.py` (fixes S5)

```
app/services/workspace/
  selection.py  — _selected_ids, selection_providers, _strict_deps, expand_strict
  transaction.py— _skip_row, _guarded, _version_row, _policy_row, _rollback, _apply_domain, _dependency_row, _migrated_doc, _checked_doc, _restore_one, _restore_row
  restore_runner.py — _preflight, restore_workspace, _log_result, _finish, _reconcile_all
  apply.py      — facade re-exporting restore_workspace, selection_providers, expand_strict for backward compat
```

Each file <150 LOC, single responsibility. No behavior change, only move.

#### G — `Manifest` dataclass (fixes S13, optional — keep JSON shape)

```python
@dataclass(frozen=True)
class Manifest:
    format: str
    workspace_format: int
    snapshot_id: str
    name: str
    description: str
    snapshot_kind: str
    created_utc: str
    app: dict
    compat: dict
    domains: dict
    @classmethod
    def from_dict(cls, d: dict) -> Manifest: ...
    def to_dict(self) -> dict: ...  # same wire format as today
```

Used internally, file format unchanged. Builder `build_manifest` returns `Manifest` then `.to_dict()` for writing.

### 4.3 What NOT to introduce

- No generic `Result` monad, no `Either` — overkill, use explicit dataclasses per domain.
- No ORM for manifest, no second schema.
- No event bus for restore — keep direct calls.

## 5. Ordered Refactor Plan — small testable steps

Each step: buildable, testable, reversible, with behavior-preservation.

### Step 0 — Characterization tests (before any refactor)

- **Goal:** Lock current behavior.
- **Tests to add:**
  - `tests/test_workspace_refactor_char.py` (new, not in scope of quality gates as test file):
    - save: `SaveRequest` with selected=None vs explicit, allow_partial, file_docs merge for session.json, _capture_block shapes, snapshot_dir_name sanitization, publish atomicity (temp survives on failure).
    - restore: selection_providers unknown ids, expand_strict transitive, _guarded crash → skip row, _version_row unsupported, _policy_row secret, _rollback success/failure, _checked_doc migration+semantic, restore_workspace with missing file, checksum mismatch, unsafe path.
    - gates: safe_rel_path rejects `..`, absolute, drive, empty; load_files dedup.
    - registry: restore_order known+unknown, all_providers length, get unknown → None.
    - snapshot_index: recent_snapshots prunes missing, record_snapshot caps at RECENT_CAP, last_snapshot returns "" when missing.
    - recover: backup_live copies existing, records absent, refuses on copy failure, prune keeps 10.
    - reports: save_report result logic, restore_result damaged → failed.
- **Verification:** `pytest tests/test_workspace_* -q` green.

### Step 1 — Extract JsonFileProvider base (S6)

- **Files:** new `app/services/workspace/providers/_base.py`, modify `captcha_stats.py`, `job_history.py`, `cooldowns.py` to inherit.
- **Behavior:** identical capture/apply, only validate overridden.
- **Rollback:** revert inheritance, keep old methods.
- **Tests:** existing `test_workspace_providers.py` must still pass; add char test for each provider's live_paths.

### Step 2 — Introduce SaveRunContext dataclass (S1)

- **Files:** `save.py`: new `@dataclass SaveRunContext`, change `_stage`, `_publish_save`, `_snapshot_manifest` signatures to accept context, remove dict mutation.
- **Behavior:** same folder, same manifest, same report.
- **Rollback:** restore dict version (git revert file).
- **Tests:** char test for save with mocked fsio.

### Step 3 — Introduce BackupResult + ManifestRead dataclasses (S2)

- **Files:** `recover.py` returns `BackupResult`, `manifest.py` returns `ManifestRead`, wrappers `backup_live` and `read_manifest` keep backward compat returning tuple for one commit, then migrate callers in `apply.py` and `restore.py`.
- **Behavior:** same refusal messages, same error strings.
- **Rollback:** revert to tuple.

### Step 4 — Split apply.py into selection.py, transaction.py, restore_runner.py (S5)

- **Files:** new `selection.py`, `transaction.py`, `restore_runner.py`; `apply.py` becomes facade importing and re-exporting public symbols (`restore_workspace`, `selection_providers`, `expand_strict`) for compatibility.
- **Behavior:** identical restore flow.
- **Tests:** `test_workspace_restore.py` and char tests must pass.
- **Quality:** each new file <150 LOC, functions ≤20 LOC.

### Step 5 — SnapshotIndex class + pure recent() (S4)

- **Files:** `snapshot_index.py`: new `SnapshotIndex` class, `recent_snapshots` pure (no write), new `prune_missing` explicit; `record_snapshot`/`record_restore` delegate.
- **Behavior:** UI still sees pruned list because `prune_missing` called by `record_snapshot` and by `get_workspace_state` (panel) — add explicit call in panel.
- **Rollback:** restore old function with side-effect.

### Step 6 — RecoveryService + UTC fix (S10, S2)

- **Files:** `recover.py`: new `RecoveryService`, `_recovery_dir` uses `utc_now_iso` (UTC), returns `BackupResult`.
- **Behavior:** backup folder name now UTC, still sorts; old local-time folders still pruned correctly.
- **Tests:** backup creates folder, copy, absent, refusal.

### Step 7 — Manifest dataclass (S13, optional, if time)

- **Files:** `manifest.py`: new `Manifest` dataclass, `build_manifest` returns `Manifest`, `to_dict()` for writing; `check_format` and `parse_manifest` use dataclass internally.
- **Behavior:** wire JSON unchanged.
- **Rollback:** revert to dict builder.

### Step 8 — Unify safe_rel_path (S8) + fix fsio race (S15)

- **Files:** `integrity.py`: add `is_safe_path(rel) -> (bool, normalized)`; `restore.py:_inside` and `gates.py:_gated` both call it; `fsio.py:publish` uses `os.replace` semantics with exist check removed, rely on `FileExistsError` from rename (atomic) — or keep check but document race as acceptable because retry will fail with FileExistsError.
- **Behavior:** same refusal for unsafe paths.

### Step 9 — Rename restore.py preview to preview.py (S12) with alias

- **Files:** new `preview.py` containing current `restore.py` logic; `restore.py` re-exports `preview_restore` for compatibility; update `ui/panels/workspace.py` to import from `preview` (or keep old import, both work).
- **Behavior:** identical preview.

### Step 10 — Quality gates + baseline

- Run `tools/verify_quality.py --changed --base origin/main --allow-legacy`, `pytest`, coverage, `npm run test:js` if needed.
- Update `tools/quality_baseline.json` via `--record-baseline`.

## 6. Behavior-Preservation + Rollback per Step

| Step | Preservation strategy | Rollback |
|------|----------------------|----------|
| 0 | Add tests only, no prod change | Delete test file |
| 1 | Inherit + override, keep method signatures; existing tests pin behavior | Revert provider files to old impl |
| 2 | Dataclass replaces dict, same fields, same mutation via new instance (frozen=False for file_entries) | `git checkout HEAD~1 -- save.py` |
| 3 | New dataclasses with `.ok` property, old tuple wrapper kept for 1 commit | Revert recover.py, manifest.py |
| 4 | Move functions verbatim, no logic change, facade re-exports | Revert new files, restore apply.py from git |
| 5 | Pure getter + explicit prune, panel calls prune | Revert snapshot_index.py |
| 6 | UTC folder name, same backup content | Revert recover.py |
| 7 | Dataclass to_dict produces identical JSON (canonical_bytes) | Revert manifest.py |
| 8 | Unified safe check, same refusal strings | Revert integrity.py, restore.py, gates.py |
| 9 | Alias keeps old import path | Delete preview.py, restore restore.py |

All steps must keep `verify_quality --changed --base origin/main` green and `pytest tests/test_workspace_*` green.

## 7. Tests Required Before/After Each

### Before (Step 0) — Characterization

- `test_workspace_refactor_char.py`:
  - save: full save publishes valid workspace, partial save with allow_partial, abort without allow_partial, file_docs merges session.json, snapshot_dir_name sanitizes, publish fails → .failed folder.
  - restore: preview ok/missing/excluded/unsafe, selection unknown → refusal, strict deps transitive, version mismatch → skip, policy → skip with advice, guarded crash → skip, rollback success/failure, damaged → failed result.
  - gates: safe_rel_path rejects `../`, `/abs`, `C:/`, empty, `//`, `a/../b`; size mismatch, sha mismatch, parse error.
  - registry: order, unknown ids sorted after known.
  - snapshot_index: recent capped, prune missing, last_snapshot.
  - recover: backup copies, absent recorded, copy failure → refusal, prune keeps 10.
  - reports: save_result logic, restore_result damaged.

### After each step

- Run `pytest tests/test_workspace_* -q` (must stay green)
- Run `pytest tests/test_workspace_architecture.py -q` (import direction)
- Run `python -m py_compile app/services/workspace/*.py app/persistence/workspace/*.py`
- Run `tools/verify_quality.py --changed-files <changed> --allow-legacy`

### Final

- Full `pytest tests -k workspace -q`
- `tools/verify_quality.py --changed --base origin/main --allow-legacy`
- Coverage not decreased.

## 8. Documentation Changes

- Update `docs/current/SYSTEM_OF_RECORD.md` if behavior table mentions workspace save/restore — add note that internal modules split but external behavior unchanged.
- Update `docs/README.md` map: point to this archive doc.
- No new top-level doc — this archive doc is the design record.
- If preview.py introduced, update import docs in `app/services/workspace/__init__.py` docstring.

## 9. Before/After Quality Metrics

### Before (measured 2026-09-29, branch HEAD 2d35536)

- `app/services/workspace/save.py`: 235 LOC, max function LOC ~35 (`save_workspace` + `_publish_save`), CC max ~8, nesting max 2.
- `apply.py`: 276 LOC, 16 functions, max function LOC ~30 (`restore_workspace`), CC max ~9 (`_restore_one`), cognitive ~12, nesting 2.
- `provider.py`: 106 LOC, 3 dataclasses + 1 class, methods ≤10 LOC.
- `registry.py`: 51 LOC, import-time side effects.
- `snapshot_index.py`: 69 LOC, getter with side-effect.
- `recover.py`: 102 LOC, tuple return, local time.
- `gates.py`: 64 LOC, dedup logic.
- `restore.py`: 101 LOC, duplicate safe check.
- `fsio.py`: 133 LOC, backoff, race.
- `manifest.py`: 84 LOC, dict builder.
- `integrity.py`: 64 LOC.
- `errors.py`: 63 LOC.
- `reports.py`: 69 LOC, dict returns.
- `workspace.py` panel: 185 LOC, 6 slots, lambdas.

**Quality gate baseline:** `tools/quality_baseline.json` 242 py + 99 js, floor line 89.34 branch 86.37. `verify_quality --changed --base origin/main` PASSED before refactor (with allow-legacy).

### After (target)

- `save.py`: ~180 LOC after extracting `SaveRunContext` to `save.py` or new `context.py` (<50 LOC), functions ≤20 LOC, CC ≤6.
- `apply.py`: becomes facade ~30 LOC re-exporting; new `selection.py` ~80 LOC, `transaction.py` ~150 LOC (split further if needed), `restore_runner.py` ~120 LOC — each file 150–300 ideal, functions 4–20 LOC, CC ≤8, nesting ≤3.
- `provider.py`: split utilities to `persistence/workspace/fsio` or new `live.py` (config_dir, read_live_json, live_capture) — provider.py becomes pure contract ~70 LOC.
- `registry.py`: explicit `register()` function, no import-time loop side effects beyond explicit list, ~60 LOC.
- `snapshot_index.py`: `SnapshotIndex` class ~90 LOC, pure recent, explicit prune, functions ≤15 LOC.
- `recover.py`: `RecoveryService` class ~110 LOC, UTC, returns dataclass, CC ≤6.
- `gates.py`: uses unified `is_safe_path`, ~60 LOC.
- `preview.py` (ex-`restore.py`): ~100 LOC, single responsibility.
- `manifest.py`: `Manifest` dataclass + builder ~110 LOC, to_dict preserves wire format.
- `integrity.py`: add `is_safe_path` helper, ~75 LOC.
- `reports.py`: add dataclasses `SaveReport`, `RestoreReport` internally but to_dict for wire, ~90 LOC.
- `providers/_base.py`: ~50 LOC.
- Providers: each ~40–60 LOC after inheriting base.
- `workspace.py` panel: extract pure helpers to `workspace_helpers.py` (clamp, refresh table) ~80 LOC, panel itself ~120 LOC, slots only.

**Quality gate target:** no new function >30 LOC, no class >150 LOC, params ≤4, CC ≤10, cognitive ≤15, nesting ≤4. `verify_quality --changed --base origin/main --allow-legacy` PASSED, coverage not decreased, branch coverage ≥75%.

**Metrics to capture after each step:** `radon cc -s app/services/workspace/*.py`, `radon raw`, `wc -l`, `verify_quality` JSON.

## 10. Risks and Mitigations

- **Risk:** Changing `safe_rel_path` logic could open path traversal — mitigate by char tests with `..`, absolute, drive, empty.
- **Risk:** UTC vs local time change could break existing recovery folder sorting — mitigate by keeping prune that sorts lexicographically and accepts both.
- **Risk:** Splitting apply.py could break import path `app.services.workspace.apply.restore_workspace` — mitigate by keeping facade re-exports.
- **Risk:** Manifest dataclass could change JSON key order — mitigate by using `canonical_bytes` which sorts keys, so order irrelevant, but to_dict must produce same keys as before.
- **Risk:** SnapshotIndex pure recent changes UI behavior (recent list not auto-pruned) — mitigate by adding explicit prune call in panel's `get_workspace_state`.

## 11. Acceptance Criteria for Refactor Done

- [ ] All 32 files diff vs origin/main still contain only workspace save/restore + prior shutdown fix (no unrelated changes)
- [ ] No behavior change: existing `tests/test_workspace_*` green + new char tests green
- [ ] No file format change: old snapshots still load, new saves produce same manifest shape
- [ ] Quality gates: `verify_quality --changed --base origin/main --allow-legacy` PASSED
- [ ] Ideal sizes: no new function >30 LOC, file 150–300 where possible, module 5–15 files
- [ ] Docs: this archive doc + SYSTEM_OF_RECORD.md updated if needed
- [ ] Rollback: each step reversible via git checkout of single file(s)

## 12. Next Steps (implementation order)

1. Step 0 — write `tests/test_workspace_refactor_char.py` and run
2. Step 1 — `_base.py` + 3 providers
3. Step 2 — `SaveRunContext`
4. Step 3 — `BackupResult`/`ManifestRead`
5. Step 4 — split apply.py
6. Step 5 — `SnapshotIndex`
7. Step 6 — `RecoveryService` UTC
8. Step 7 — `Manifest` dataclass (optional)
9. Step 8 — safe_path unification
10. Step 9 — preview.py alias
11. Step 10 — quality gate + baseline record

Each step: TDD — write/adjust char test first, then refactor, then `verify_quality --changed-files <files> --allow-legacy`, then `pytest -k workspace`, then commit.

