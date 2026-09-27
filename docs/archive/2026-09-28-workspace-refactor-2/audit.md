# Global Saving System — audit #2 and TDD refactor design (2026-09-28)

Scope: every file the Global Saving System added (`git diff --stat f5cb06e c65f71f^2`, 59 files),
plus its integration seams (`json_store`, `preset_store`/`config_manager` `all_data`/`replace_all`,
`window_catalog`, `bridge`, `ui/panels/__init__`). Legacy code outside those seams is out of scope.
Previous audit: `docs/current/WORKSPACE_REFACTOR_AUDIT.md` (structure/size pass, 2026-09-25).
This pass focuses on **correctness at the failure edges**: transactions, corruption, rollback,
partial restore, schema ownership and doc truth. Every High/Medium finding below was **reproduced
against the real code** by a throwaway probe (P1–P10, §2), not inferred from reading.

## 1. Code map

| Layer | File (LOC) | Owns |
|---|---|---|
| persistence (stdlib only, pinned by `test_workspace_architecture`) | `errors.py` | `STAGES` taxonomy, `WorkspaceError` |
| | `integrity.py` | sha256, canonical bytes, `safe_rel_path` |
| | `manifest.py` | format constants, build/check/parse/read manifest |
| | `fsio.py` | temp dir, `write_bytes`, publish (rename, EXDEV copy), backoff |
| services | `save.py` (292) | SaveRequest, selection, capture under `state_lock`, temp build, manifest-last publish, **and** the snapshot index (recent/last save/last restore) |
| | `apply.py` (260) | restore: preflight, strict expansion, per-domain transaction, reconcile, report |
| | `gates.py` (56) | file gates safe-path → size/sha → parse (restore only) |
| | `restore.py` (82) | read-only preview (own size check + remap notes) |
| | `recover.py` (82) | recovery backup of live files + prune |
| | `meta.py`, `reports.py`, `registry.py`, `provider.py` | env/ids/log, report builders, provider table + order, provider contract |
| providers | `arena_state`, `session` (2 domains, 1 file), `undo`, `preset_stores` (2), `cooldowns`, `captcha_stats`, `job_history`, `policies` (2, file-less) | capture / validate / migrate / apply / reconcile per domain |
| UI | `ui/panels/workspace.py` (173), `web/js/panels/workspace.js` (368) | 6 slots + Python refresh table; JS window + JS refresh table |

Transaction boundaries: **save** = one temp folder, manifest written last = commit marker, one
rename = publish. **Restore** = one recovery backup for the whole run, then one transaction **per
domain** (pre-apply capture → apply → rollback to capture on exception). There is no cross-domain
rollback by design (§C.6.7). Schema ownership: manifest owns `workspace_format` (min 1); each
provider owns its `schema_version` and the readable set `supported_migrations`. Only `grid_window`
accepts older versions (4…9), and its `migrate` is a pure note (canonical grid pipeline migrates).

## 2. Findings (evidence → severity)

Probes lived in an uncommitted `tests/_probe_ws_test.py`; each becomes a committed red test in §5.

| id | Sev | File / symbol | Evidence |
|---|---|---|---|
| A1 | **High** | `apply._restore_one` (`provider.validate`, `provider.migrate` unguarded), `apply._apply_domain` (`provider.capture` outside `try`) | **P1**: a stamped `app_state.json` with an unhashable image id → `arena_state.validate` raises `TypeError` out of `restore_workspace`. Domains earlier in order are already applied, **no restore-report, no `last_restore`**, UI gets no reply. Violates §F ("one bad file never blocks unrelated recovery") and "never silent". Stages `migration` and `reconcile` from §F are **never produced** (grep: 0 sites). |
| A3 | **High** | `reports.restore_result` | **P3**: a `damaged` row (apply AND rollback failed → live state unknown) yields `success_with_warnings`, `ok: true`, logged at warn. |
| V3 | **High** | `job_history/captcha_stats/cooldowns.capture` via `json_store.load_json` (returns default on ANY error) | **P5**: truncated live `job_history.json` → save `success`, snapshot holds `{}`. Restoring that snapshot later wipes the real history. RULE 4 (empty ≠ broken). The pre-apply capture has the same blind spot. `cooldowns.read_live` retry is dead (load_json never raises); its note claims "no live cooldown file" for a corrupt one. |
| C1 | **High** | `recover._copy_live_file` / `backup_live` | **P7**: copy fails (locked file) → recorded as `absent`, restore proceeds and reports `success` with an **empty** recovery backup. `backup.mkdir`/`recovery.json` `OSError` escapes (A5). §C.6.4 promises a last-known-good. |
| U1 | **High** | `WorkspaceMixin.save_workspace/restore_workspace` slots; `workspace.js wsRunRestore` | **P10**: slot re-raises. QWebChannel then answers empty → `wsParse` → `{}` → restore shows **"restored"** (only `ok === false` counts as failure). Save shows "unknown error". |
| C2 | Medium | `recover._recovery_dir` (`%Y%m%d-%H%M%S`) | **P8**: two restores in one second share a folder, so the 2nd backup overwrites the 1st, i.e. the only copy of the pre-restore state. |
| S3 | Medium | `save._publish_save` lines 209–210 | **P6**: `save-report.json` write fails after the rename → exception escapes; snapshot is published and valid but not in the recent list, caller sees a crash. S4: `failed_folder` reported even when that rename failed. |
| R1 | Medium | `restore._file_status`, `_remap_notes` | **P9**: manifest path `../../x` → preview stats **and parses a file outside the snapshot** and shows its `root_path`, while restore refuses it (`unsafe_path`). Preview and gates drifted. |
| A2 | Medium | `apply._rollback` | **P2**: pre-apply capture not usable → no rollback runs, row still says `rolled_back: true`. |
| S1 | Medium | `reports.save_report` `failed_required` | **P4**: filters stages `semantic/apply`, which save never produces → always `[]`, even when required `arena_state` fails capture. S2: `required` has no behavioural effect (any failure aborts without `allow_partial`, **P4b**) — it is a report flag; design §C.5.6 says otherwise. |
| S8 | Medium | `save.py` 239–292, `apply` imports `record_restore` from `save` | Snapshot index is a second responsibility in `save.py` (292 LOC, at RULE 18 edge); restore depends on save. `_write_meta` swallows `OSError` silently. |
| C3 | Low | `recover.prune_recovery` | docstring and §C.6.4 say "logged"; nothing logs. |
| V1 | Low (dead) | `StateProvider.plan` + 8 overrides (9 defs) | 0 callers (grep). Design §C.2/§E.2 list it as preview input, but §C.6.1 fixes preview as **manifest-only**, which a doc-based `plan()` cannot be. Delete. |
| V2 | Low (dead) | `manifest.manifest_bytes`, `registry.file_providers` | 0 callers. `registry.domain_for_file` test-only (RULE 18: no test-only public API). |
| V4 | Low | `meta.config_dir`, `captcha_stats.stats_file`, `policies._masked_presence` | config-dir resolution written 3×; providers may not import `meta` (architecture test). |
| P1–P5 | Low | persistence hygiene | garbled `persistence/workspace/__init__` docstring; cycle-free local imports (`save._write_env`, `save.inclusion_policy`, `recover.backup_live`, provider `WorkspaceError` imports); `WorkspaceError(evidence: tuple = None)` hint; `except (OSError, FileExistsError)` redundant. |
| U2 | Low | Python `_REFRESH_TABLE` vs JS `WS_LIVE_PANELS`/`WS_CONFIG_RELOADERS` | live refresh split across two languages; `arena_state`, `window_presets` refreshed by both. Documented, not changed (cross-language unification = large, no bug). |
| V5, V6, A4, A6, S6, S7 | Info | private seams (`bridge._save_arena`, `_history_file`), shared `session.json` attribution, gate rows named by `display_name`, policy rows stage `apply`, `_stage` mutates `run`, two clocks | Kept: legacy seams / frozen report format; changing them buys nothing observable. |

Logging: save success = 1 line, restore = 1 line at success/warn/error. Missing: recovery prune, meta write
failure, slot crash, corrupt-live capture. Typing is consistent (`from __future__ import annotations`).
Coverage is 90% branch, yet no test exercises any failure path above, which is why P1–P10 survived.

### Doc drift (`GLOBAL_WORKSPACE_SAVE_DESIGN.md`)
§C.1 omits `gates.py`/`recover.py` and lists non-existent `workspace/{store,render,actions}.js`;
§C.2 contract shows `rollback()`, `derived_fields`, `validate(data, entry) → list[Problem]`,
`plan()` (code: `validate(doc) → str|None`, rollback = re-apply pre-apply capture, `live_paths`, `required`);
§C.4 claims one atomic commit for both session domains and an `unowned_keys_kept` report (code:
two per-domain commits, no such key); §C.5.2/4/6 (temp name, save-report inside temp, required-only abort);
§C.6.4 prune log line; §D.4 `dependents_blocked` (absent); §E.2 `plan()`; §F `migration`/`reconcile` stages;
§G `kept_unknown`. The doc is 523 lines (RULE 18.4 ideal ≤ 200): it gets a drift-fix pass, not a rewrite.

## 3. Interfaces (only where they remove real duplication)

1. `fsio.write_report(root, rel, data) -> str` — "write into the folder, else beside it, else say so".
   Today only restore has it; save needs the same (S3). Two call sites, one rule.
2. `provider.read_live_json(path) -> (doc, error)` — missing file = `({}, "")`, unreadable/corrupt =
   `(None, cause)`. Replaces three silent `load_json` reads + a dead retry (V3). `json_store` untouched.
3. `provider.config_dir(bridge)` — one home for the config dir (V4); `meta` re-exports it.
4. `snapshot_index.py` — recent/last-save/last-restore moved out of `save.py` (S8), no API change.
Rejected: a shared "gate" object for preview + restore (preview stays size-only per §C.6.1; it only
gains the `safe_rel_path` check), a cross-language refresh registry (U2), a `Result` type.

## 4. Behaviour decisions (justified changes; formats and public APIs otherwise frozen)

| Change | Why it is justified |
|---|---|
| A crash inside one domain becomes that domain's row: `migration` / `semantic` / `apply` (pre-apply capture failed → **not applied**, never apply without a rollback point) | §F contract; P1 |
| any `damaged` row → result `failed` (`ok: false`, error-level log); restored ids still listed | live state is inconsistent; the user must act (§F "never silent") |
| `rolled_back` is `true` only when the rollback ran | P2 truth |
| recovery backup cannot copy an existing live file / create its folder → restore **refused before any mutation** | §C.6.4 last-known-good; P7 |
| recovery folder name gets `-2`, `-3`… on collision (still sorts chronologically for prune) | P8 |
| preview row status `unsafe_path`; remap notes read only safe paths | P9; same rule as restore |
| post-publish report/index failures → `ok: true` + `report_note`; `failed_folder` only when it exists | snapshot is valid (manifest = commit marker); P6 |
| `failed_required` = failed domains whose provider is `required` | report truth; abort rule unchanged |
| corrupt existing live file → capture `ok: false` with cause (save refuses unless partial) | RULE 4; P5 |
| slots never raise: `{"ok": false, "error"}` + error log; JS treats `ok !== true` as failure | P10 |

## 5. Ordered plan — small, reversible steps (S = structural, B = behaviour; never mixed)

Each step = one commit; gate = `verify_quality --allow-legacy --coverage-ratchet` on full-suite
coverage + full pytest + `node --test tests/js`. Rollback of any step = `git revert <sha>` (no step
changes a file format; each B-step is guarded by its own test, so a revert re-reds exactly that test).

| # | Kind | Change | Tests before → after |
|---|---|---|---|
| 1 | S | delete `plan()` ×9, `manifest_bytes`, `file_providers`, `domain_for_file` (+ its test-only assertion) | suite green before/after; grep proves 0 callers |
| 2 | S | `snapshot_index.py` ← index from `save.py`; `apply` imports it; `save` re-exports nothing new | existing index tests unchanged, green |
| 3 | S | hygiene P1–P5; `provider.config_dir` single home (V4) | architecture + suite green |
| 4 | B | A1: guard `migrate`/`validate`/pre-apply `capture` → rows; report always written | red: P1 (crash → report + `last_restore`), migrate-raises → `migration`, capture-raises → not applied |
| 5 | B | A2 + A3: truthful `rolled_back`; `damaged` → `failed` | red: P2, P3 |
| 6 | B | C1/A5/C2/C3: backup refuses on failure, unique folder, prune logs | red: P7 (refusal, live untouched), P8, prune log |
| 7 | B | R1: preview safe-path | red: P9 |
| 8 | B | S1/S3/S4/S8b: `fsio.write_report`, guarded post-publish, `failed_required`, meta write logged | red: P4, P6, rename-fails → no `failed_folder` |
| 9 | B | V3: `read_live_json` in 3 providers; cooldowns note; dead retry removed | red: P5 ×3 providers |
| 10 | B | U1: slot guard (py) + `ok !== true` (js) | red: P10 py; JS test "empty reply is a failure" |
| 11 | docs | design doc drift pass (§C.1/C.2/C.4/C.5/C.6/D.4/E.2/F/G + new §O), SoR row I-77, README, CODE_VERIFICATION footer | — |

## 6. Behaviour preservation

Frozen: manifest/report/recovery.json keys and value sets (additions only: `migration` stage now
produced, `report_note` on save, `unsafe_path` preview status); slot names/signatures; provider
contract minus the dead `plan()`; restore order; strict/optional semantics; partial-save flag.
All 125 existing workspace tests + 17 JS stay green unmodified except the one `domain_for_file` assertion (step 1).

## 7. Metrics (measured; same commands before and after)

| Metric | Before (`9c99e5d`) | After (`4843edb`) |
|---|---|---|
| modules / LOC (persistence + services + panel .py) | 25 / 2339 | 26 / 2415 (+`snapshot_index.py`; −54 dead, +guards) |
| functions / max CC / max function LOC | 202 / 10 (`safe_rel_path`, untouched) / 21 (`build_manifest`, untouched) | 198 / 10 / 21 (same two) |
| largest file | `save.py` 292 | `apply.py` 276 (`save.py` 235) |
| workspace pytest / JS tests | 125 / 17 | 154 / 18 |
| full suite | 2843 passed, 6 skipped | 2872 passed, 6 skipped · JS 485 pass / 0 fail |
| workspace-scope coverage (pytest-cov TOTAL, workspace tests only) | 90% | 93% (`apply` 91→96, `recover` 93→100) |
| reproduced failure-edge defects (P1–P10) | 10 | 0 (original probe script re-run on `4843edb`) |
| dead public symbols | 12 | 0 |
| `verify_quality --allow-legacy --coverage-ratchet` (all changed files) | — | 0 fail, 0 warn |

## 8. Execution log

Commits (each gate-green, each revertable on its own): `39d68c3` S1 dead code · `1c0ff4c` S2 snapshot
index · `b14d282` S3 hygiene · `842cc27` A1 · `234e185` A2/A3 · `8a341c7` C1/A5/C2/C3 · `3fafbb9` R1 ·
`c80ed95` S1/S3/S4/S8 · `55bec0f` V3 · `4843edb` U1. Found while executing and folded into its step:
`gates.load_one` raised on an unreadable file (step 4); preview `_remap_notes` crashed on a non-object
queue doc (step 7); step 5 would have skipped the RULE 24 refresh of the domains a *failed* run did
restore — caught by a test in step 10, refresh now keys on `restored`, not `ok`.
Not done (see §2 Info rows): V5/V6/A4/A6/S6/S7, U2 cross-language refresh table.
RULE 18.4: `GLOBAL_WORKSPACE_SAVE_DESIGN.md` is 544 lines (> 200 ideal) — pre-existing; this pass
rewrote drifted text in place and added a 15-line §O instead of growing sections.
