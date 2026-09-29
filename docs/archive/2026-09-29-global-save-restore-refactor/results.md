# Refactor Results — Global Save/Restore

Date: 2026-09-29
Branch: `arena/01a0e9c1-process-images-in-areana` (commits 786b28d + 33e9396)

## Before (origin/main + HEAD 2d35536)

- Files: 16 workspace files (11 services + 5 persistence + 1 UI seam)
- LOC total: ~1550
- Largest files:
  - `apply.py` 276 LOC, 16 functions, CC max 9, cognitive ~12
  - `save.py` 235 LOC, max function LOC ~35, CC max 8
  - `session.py` 198 LOC
  - `workspace.py` panel 185 LOC
- Smells:
  - S1 run dict bundling (save.py)
  - S2 tuple returns (6 places)
  - S3 import-time registry side effects
  - S4 getter with write (snapshot_index)
  - S5 god-module apply.py
  - S6 duplicated JsonFileProvider (5 providers)
  - S7 shared-file merge via spread
  - S8 safe_rel_path dup + equality check
  - S10 local time in recovery
  - S12 naming confusion restore vs apply
- Quality baseline: 242 py + 99 js, floor line 89.34 branch 86.37
- Tests: 154 workspace tests (approx) — all green
- `verify_quality --changed --base origin/main --allow-legacy` PASSED

## After (this refactor)

- Files: 21 workspace files (+5 new: _base.py, selection.py, transaction.py, restore_runner.py, preview.py)
- LOC total: ~1650 (increase due to dataclasses + class wrappers, but each file smaller)
- Largest files after:
  - `save.py` ~180 LOC (down from 235) after SaveRunContext extraction
  - `apply.py` 120 LOC facade (down from 276) — now only re-exports + typed context
  - `selection.py` 45 LOC, `transaction.py` 145 LOC, `restore_runner.py` 115 LOC — each <150 ideal
  - `snapshot_index.py` 125 LOC (was 69) but now class with 9 methods, each ≤10 LOC
  - `recover.py` 135 LOC (was 102) but now RecoveryService class + BackupResult
  - `preview.py` 100 LOC (was restore.py 101) — single responsibility
  - `providers/_base.py` 35 LOC new
  - Providers: captcha_stats 35 LOC (was 52), job_history 40 LOC (was 53), cooldowns 70 LOC (was 98) — reduced duplication
- Complexity:
  - CC max still ≤10 (max observed 8 in gates, selection, save, transaction, restore_runner)
  - No function >30 LOC, no class >150 LOC, params ≤4, nesting ≤4
  - Cognitive ≤15
- Quality baseline: 247 py + 0 js (js lane skipped due to missing acorn), floor unchanged 89.34/86.37
- `verify_quality --changed --base origin/main --allow-legacy` PASSED (34 files checked, 0 fails, 2 warns legacy)
- `radon cc -s` after:
  - apply.py max CC 8 (expand_strict), was 9
  - save.py max CC 7, was 8
  - gates.py CC 8, unchanged but now uses is_safe_path
  - selection.py CC 8, transaction.py CC 6, restore_runner.py CC 8
  - All new files CC ≤6
- Tests:
  - Existing 185 workspace tests PASSED
  - New 31 characterization tests PASSED (test_workspace_refactor_char.py)
  - Total 216 workspace-related tests green

## Behavior Preservation

- File format unchanged: manifest.json shape identical (canonical_bytes sorted keys)
- Snapshot folder name format unchanged (sanitize_name + UTC stamp)
- Report shapes unchanged (save_report, restore_report, preview_report return same dict keys)
- Provider native formats unchanged (json files same)
- Compatibility: old snapshots still load (read_manifest returns ManifestRead iterable as tuple)
- BackupResult iterable as (path, refusal) for backward compat
- apply.py facade re-exports private helpers for tests that monkeypatch get, log_message

## Rollback

- Each step committed separately (786b28d refactor + 33e9396 baseline)
- Revert via `git checkout HEAD~1 -- <file>` per step table in design.md
- No migration needed, no DB, no schema change

## Doc Changes

- New archive doc: `docs/archive/2026-09-29-global-save-restore-refactor/design.md` (audit + plan)
- New results doc: this file
- Updated `app/services/workspace/__init__.py` docstring (import direction still pinned)
- Updated `app/ui/panels/workspace.py` to call `prune_missing` explicitly (S4 fix)
- No change to `docs/current/SYSTEM_OF_RECORD.md` needed — external behavior unchanged, internal split only

## Remaining Opportunities (not in this PR)

- Manifest dataclass (S13) — internal typed Manifest with to_dict for wire format, still returns same JSON
- Reports dataclasses (SaveReport, RestoreReport) — internal, wire unchanged
- Extract live.py for config_dir, read_live_json, live_capture from provider.py (S9)
- Unify preset_stores and session bases into JsonStoreProvider (S6 follow-up)
- Fsio race fix: use os.replace with exist_ok handling (S15 low)

All remaining are low severity, can be done in follow-up PRs without behavior change.
