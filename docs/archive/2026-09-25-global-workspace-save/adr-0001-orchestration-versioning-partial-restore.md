# ADR 0001 — Global Workspace Save: orchestration, versioning, compatibility, partial restore

**Status:** Proposed (Phase 0 gate — awaiting owner approval)
**Date:** 2026-09-25
**Companion design:** `docs/current/GLOBAL_WORKSPACE_SAVE_DESIGN.md` (inventory §B, algorithms §C–E, fault matrix §F, test plan §H, phases §I)
**Rules applied:** `docs/current/AGENT_RULES.md` RULE 13, 16, 17, 18, 20, 23; SYSTEM_OF_RECORD invariants I-29, I-39, I-43, I-50, I-51, I-59, L-2

## Context

The app persists ~10 independent JSON stores (see design §A.1), all atomic per file, all written through feature-owned code paths (33 `_save_arena` call sites, pool-push cooldown autosave, closeEvent flush). The owner wants one **Global Saving System**: capture the complete restorable workspace — every feature's sub-state plus the sash/grid layout — in one folder, with save / load / save-as / quick-load-last, whole-workspace OR selected-part restore, and per-domain fault isolation (one bad file must not block the rest). Real-world constraints already observed: a Windows/cloud-sync access-denied on `cooldowns.json` (retry hardening exists only for `app_state.json` — design §A.2.5), and transient browser/worker state that must never be trusted after restart (§A.2.9).

## Decision

1. **Orchestration: provider/adapter registry over native stores.** Each of the 10 persisted domains gets one small `StateProvider` (protocol in `app/services/workspace/provider.py`) that owns capture/validate/migrate/apply/rollback/reconcile for **its existing native file and format**. A thin coordinator (`app/services/workspace/coordinator.py`) owns folder creation, ordering (topological, design §B.2), integrity (sha-256 + manifest), reports, and recovery. No second schema, no giant AppState, no re-serialization of feature state into a unified model. Store files are exported byte-identical-in-content (canonical deterministic serialization) and restored through the feature's own stores.
2. **Versioning & compatibility: explicit, per-layer.** `manifest.json` carries `workspace_format` (starts 1) + per-domain native `schema_version` + `supported_migrations` + `compat` block (app build range, `GRID_VERSION`). Future native versions are refused with a precise message; older supported versions migrate through **pure functions** that never rewrite the snapshot on disk. Unknown fields are preserved where the native loader is already tolerant, otherwise dropped **with a report line** — never silently.
3. **Partial restore: manifest-resolved, dependency-aware, per-domain transactional.** Preview reads the manifest only; selection by domain or by native file resolves through the manifest (never by filename inference); strict dependencies auto-expand; each domain passes safe-path → checksum → parse → schema → semantic → migration gates, then applies atomically with per-domain rollback; a failure skips only that domain and its strict dependents, records a structured warning (domain, exact file, failure stage, cause, expected vs actual, recommended action), and never rolls back successful independents. A recovery snapshot (`config/workspace_recovery/<ts>/`) backs up every affected live file before the first apply.
4. **Shared physical file (`session.json`): key-ownership contract.** `session_settings` and `grid_window` are separate logical domains over one file with an explicit per-key ownership table; grid keys validate through the existing `canonical_grid_payload` + added semantic checks (§C.7); invalid grid → grid keys skipped, current layout retained, default offered explicitly (RULE 13).
5. **Secrets: redacted presence only.** `captcha_solvers.json` is never exported; the manifest carries provider presence + masked fingerprints (same masking as the UI). Encrypted secret export is deferred to a separate opt-in ADR.
6. **Publish protocol: temp sibling folder, manifest written last (commit marker), atomic rename, copy fallback, bounded backoff on sharing violations.** A crash before the manifest leaves nothing claiming to be a snapshot; a crash after it leaves a valid one. Failed saves never touch previous snapshots.
7. **Live/derived state reconciled, not restored:** `run_state` forced idle, in-flight jobs → `interrupted`, `processing` images left to the existing `recover_stale_processing`, tab ids as hints, balance marked stale (design §C.6 step 8).

## Consequences

- (+) Every feature keeps its native format and flows (rules 1–2); the 135→141-slot JS contract grows deliberately in one commit (W8) with `test_bridge_slots.py`/`test_window_catalog.py` updates.
- (+) Fault isolation and reporting become testable as a matrix (design §F) instead of folklore.
- (−) ~2 new packages (≈18 small files) — justified by RULE 18 module budgets and the architecture tests that pin import direction.
- (−) Deterministic serialization means workspace files are not byte-identical to live `config/` files (sorted keys); restore accepts any parse-equal layout, documented in §C.3.
- (−) Undo restore is whole-timeline only in v1 (per-entry cherry-picking rejected — it would fork the one timeline, RULE 12).
- (o) `json_store.save_json_atomic` gains the same bounded retry `core/persistence.py` already uses (W4) — a behavior-preserving hardening that closes the `cooldowns.json` access-denied class for every store at once.

## Rejected alternatives (with reasons)

| Alternative | Why rejected |
|---|---|
| One giant `AppState` object / one merged JSON per workspace | Second competing schema; every feature change would bump a global version; couples unrelated features; re-introduces the god-service pattern the codebase removed in Areas A–C. |
| Single-file archive (zip/tar) for the workspace | Breaks human inspection of native files, single-file restore, and incremental report updates (`restore-report.json` inside the folder); no integrity benefit over per-file sha-256 in the manifest. |
| Copy the whole `config/` directory | Sweeps in secrets (`captcha_solvers.json`), logs, recordings, `.tmp` residue; no per-domain metadata/checksums; violates secret rule 6 and "no unnecessary personal data" manifest rule. |
| Central database (SQLite) as the save system | The repo is deliberately JSON-only, no DB (SYSTEM_OF_RECORD §1/§6); a DB becomes a second source of truth and a new corruption domain. |
| Export API keys encrypted by default | Key-management burden (passphrase storage, KDF, recovery) with no v1 demand; redacted presence + a future opt-in ADR is the honest scope. |
| Restore via best-effort filename matching when the manifest is missing | Explicitly forbidden by the task (rule: "Resolve the file through manifest metadata; do not infer ownership only from filename"); a manifest-less folder is reported as invalid, not guessed. |
| Continuous/automatic workspace snapshots on every mutation | Duplicates the existing per-mutation autosave write paths (design §B.1) and creates write races; explicit user snapshots + existing autosave + recovery backups cover the crash story. |
| Migrating snapshots in place (upgrade-on-read writes back) | Mutating the user's snapshot destroys the evidence of what was saved; migrations are pure and produce in-memory docs only. |
| Trusting `run_state`/`processing`/CDP `tab_id` on restore | Violates task rules 7/9 and repo invariants (L-2, I-50); stale runtime state is converted (`interrupted`/`idle`) and reconciled through the existing live machinery. |
| Splitting `session.json` into per-domain files first (refactor-before-feature) | Touches every `set_state` call site for zero user value before the feature exists; the key-ownership contract achieves isolation without the churn; a physical split can be a later, separately-tested refactor. |

## Outcome (2026-09-25)

Superseded in form only by the W9 refactor (WORKSPACE_REFACTOR_AUDIT.md): module boundaries moved (coordinator → meta/save/restore/apply/recover), every decision here — single orchestration path, workspace_format versioning, partial-restore semantics, stage vocabulary — is unchanged, except the one documented report change: capture failures now report stage `capture` (design §F).
