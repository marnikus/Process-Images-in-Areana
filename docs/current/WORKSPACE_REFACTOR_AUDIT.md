# Workspace Save/Restore — Refactor Audit & Plan (2026-09-25)

Scope: ONLY the new global save/restore feature (commit range `6eb15e2..4a49f99`):
`app/persistence/workspace/**`, `app/services/workspace/**`, `app/ui/panels/workspace.py`,
`app/ui/web/js/panels/workspace.js`, `tests/test_workspace_*.py`,
`tests/js/test_workspace_panel.mjs`. No legacy code touched. No format/API/behavior
changes except the two explicitly marked ones (§5/§6: F2, S1).

Baseline (measured): 20 Python modules / 2211 LOC, 96+103 pytest workspace tests,
14 workspace JS tests. All functions already inside RULE 16/18 limits
(worst: 27 LOC CC 8). The findings below are about **structure, ownership and
duplication**, not size.

---

## 1. Code map

```
app/persistence/workspace/          stdlib-only; no app imports (architecture-locked)
  errors.py       STAGES vocabulary + WorkspaceError (domain/stage/cause/evidence/advice)
  integrity.py    canonical_bytes, sha256, doc_entry, safe_rel_path, file_sha
  manifest.py     build/check/parse/read manifest; entry_for/domain_for_file (ownership registry)
  fsio.py         sanitize_name, snapshot_dir_name, temp dir, write_bytes, publish (rename+EXDEV), remove_tree
app/services/workspace/
  provider.py     StateProvider contract + CaptureResult/ApplyOutcome
  registry.py     the ONE provider table + RESTORE_ORDER; get/all_providers/file_providers
  reports.py      deterministic save/restore/preview report shapes
  coordinator.py  ⚠ grab-bag: SaveRequest, capture machinery, file-doc merge, manifest entries,
                  app env/meta, compat, paths, time, log helper   (see F1)
  save.py         SAVE algorithm + publish + snapshot meta (recent/last)
  restore.py      ⚠ preview + selection + recovery backup + file loading (see F2)
  apply.py        ⚠ transaction loop + reconcile + report; imports 4 privates from restore.py (see F2)
  providers/      9 files: arena_state, session (2 domains), undo, preset_stores (2),
                  cooldowns, captcha_stats, job_history, policies (2 never-exported domains)
app/ui/panels/workspace.py          6 frozen slots + post-restore live refresh (RULE 24)
app/ui/web/js/panels/workspace.js   save/browse/load-last/preview/restore flow + live sync
tests/  test_workspace_{core,providers,save,restore,secrets,architecture,panel,live_refresh}.py
tests/js/test_workspace_panel.mjs
docs/current/GLOBAL_WORKSPACE_SAVE_DESIGN.md (§A–M) + ADR-0001
```

Import directions today: panels → services; services → persistence+core; providers → nothing
in workspace services (architecture test). Sound — the problems are *inside* services.

## 2. Code smells (evidence) & 3. severity/risk

| # | Smell | Evidence | Severity / risk |
|---|---|---|---|
| F1 | **`coordinator.py` is a mislabeled grab-bag**; docstring says "save side, snapshot meta" but it holds SaveRequest, capture+validation under the feed lock, file-doc merging, manifest-entry building, env introspection (git subprocess), compat, paths, time, log. Design doc §C (line 137) says coordinator should own save/preview/restore entry points — it owns none. Every sibling imports its privates. | `coordinator.py` L18–168; save.py imports `META_FILE, RECENT_CAP, SaveRequest, _domain_entries, _file_docs, _log, _selected_providers…`; tests import `capture_all, app_meta…` from it | **Medium** / reader cannot predict where a symbol lives; privates across 3 modules = unclear contracts; new contributors edit the wrong file |
| F2 | **restore/apply split is along the wrong seam** — restore.py holds preview (read-only) AND the mutation machinery (selection, strict expansion, recovery backup, file loading); apply.py imports 4 underscore names from it (`_backup_live, _expand_strict, _load_files, _selection_providers`). | apply.py:21; restore.py L92–221 | **Medium** / apply (mutating) depends on preview module internals; refactoring preview can silently break restore |
| S1 | **`_capture_one` reports capture failures with stage `"apply"`** whose advice reads "The previous values were kept" — wrong stage, wrong advice on the SAVE side. | coordinator.py `_capture_one` raises `WorkspaceError(pid, "apply", "capture failed: …")` | **Medium** (user-facing precision, task rule "precise warning": feature+path+stage+cause+action) |
| F3 | **Duplicated policy knowledge in 3 places**: `policies.py` KEYS_EXCLUDED / KEYS_REAPPLY; `apply._policy_row` re-inlines the captcha-keys advice; `save._inclusion_policy` re-inlines short exclusion codes. | policies.py L14–16; apply.py `_policy_row`; save.py `_inclusion_policy` | **Medium** / wording drift breaks the "precise action" promise; RULE 10 (one home) |
| D1 | **Duplicate hashing**: `fsio.write_bytes` re-implements the integrity entry with a local `import hashlib`, while `integrity.doc_entry` exists; `_load_one` calls `file_sha(path)` **twice** in the sha check. | fsio.py `write_bytes`; restore.py `_load_one` | **Low** / drift risk in entry shape; wasted hash pass |
| D2 | **Duplicate ordering logic**: `preview_restore` inlines `[x for x in RESTORE_ORDER if x in …] + [rest]` — exactly `_restore_order(set(…))` defined 40 lines below. | restore.py preview_restore vs `_restore_order` | **Low** |
| D3 | **`_expand_strict` silently drops providers outside RESTORE_ORDER** while `_selection_providers` deliberately tolerates unknown-order ids (`known + sorted(rest)`). Latent inconsistency; transitive strict deps untested (known gap). | restore.py `_expand_strict` final filter vs `_restore_order` | **Low-Med** / future domain registered but forgotten in the order tuple would restore in save but never in restore |
| N1 | **Dead code/params**: `preset_stores._unused()` stub; `preview_restore(bridge, root)` never uses `bridge`; `apply._restore_row(bridge, plan, provider)` never uses `bridge`. | preset_stores.py tail; restore.py/apply.py signatures | **Low** / noise; misleads callers |
| N2 | **Format literals instead of constants**: `_write_env` hardcodes `workspace_format: 1`; `compat_block` hardcodes `min_workspace_format: 1` (constants `WORKSPACE_FORMAT`/`MIN_WORKSPACE_FORMAT` exist). | save.py `_write_env`; coordinator.py `compat_block` | **Low** / format bump would miss these |
| N3 | **`plan`/`run` dict param objects** named `plan` collide conceptually with `StateProvider.plan()`; `_publish_save` mutates `plan["file_entries"]` mid-function as an output channel. | save.py/apply.py | **Low** / readability only |
| N4 | **JS `wsRestore` no-preview fallback re-inlines `wsLoadLast`** (get state → last → preview → restore). | workspace.js wsRestore vs wsLoadLast | **Low** |
| T1 | **Untested seams**: `_expand_strict` transitive behavior (0 tests); `capture_all`'s `state_lock` import is deferred inside the function (undocumented seam). | tests grep; restore.py/coordinator.py | **Low** / characterization tests required before moving (this plan adds them) |
| DOC1 | **Code/doc drift**: design §C module map shows `coordinator.py # save_workspace / preview_restore / restore_workspace` (none of which live there); §F stage list lacks `capture`; §A.2 drift items still open. | design doc L137; errors.py STAGES | **Low** / fixed by this plan's doc step |

Non-findings (checked, deliberately kept): shared `session.json` two-domain merge (documented, order-safe); write-on-read pruning in `recent_snapshots` (documented); `app_meta` git subprocess per save (once per save, acceptable); `WorkspaceError.evidence` tuple (RULE 16 params fix, keep).

## 4. Proposed boundaries (only where they remove real duplication/coupling)

1. **`meta.py` (new, replaces coordinator.py)** — one home for snapshot *meta/environment*:
   `config_dir, default_base, utc_now_iso, snapshot_id_for, app_meta, compat_block,
   log_message (public rename of _log), META_FILE, DEFAULT_DIR_NAME`.
   Pure functions; no capture logic. Provider/registry unchanged.
2. **`save.py` owns the whole SAVE side**: + `SaveRequest`, `selected_providers`,
   `capture_one/capture_all` (feed-lock seam stays), `file_docs`, `domain_entries`
   (renamed public — they were cross-module privates).
3. **`restore.py` becomes preview-only** (read-only path): `_preview_row`,
   `preview_restore`, `_remap_notes`. Nothing imports it anymore.
4. **`apply.py` owns the whole RESTORE mutation side**: + selection/strict-expansion,
   recovery backup (`backup_live`, prune), file loading (`load_files/load_one/entry_owner`).
   Zero private imports from restore.py.
5. **`registry.py` gains `restore_order(ids)`** — the single id-ordering helper
   (preview and strict-expansion both use it; kills D2, fixes D3 by construction).
6. **`policies.py` owns policy strings**: `RESTORE_ADVICE` (per policy domain) and
   `INCLUSION_POLICY` (short codes for app-environment.json). `apply._policy_row`
   and `save._inclusion_policy` become consumers (kills F3).
7. **`errors.py` gains stage `"capture"`** (kills S1) — one vocabulary stays one.
8. No new interfaces elsewhere. No changes to provider contract, manifest shape,
   file formats, RESTORE_ORDER, report shapes (except the stage value above), JS API.

## 5. Ordered refactor plan (small, independently testable, reversible)

Every step: full workspace suites + architecture tests green before → after;
one commit per step; revert = `git revert <commit>`.

| Step | Content | Tests before | Tests after |
|---|---|---|---|
| R0 | **Characterization tests** for the seams about to move: (a) `_expand_strict` transitive chain with fake providers; (b) `write_bytes` entry ≡ `integrity` entry shape; (c) `_load_one` evidence fields on each gate. No production change. | new tests green | same |
| R1 | Dead code/params (N1): drop `_unused`, drop `bridge` from `preview_restore` + `_restore_row`. Update 5 call sites + test call sites. | suites green | suites green |
| R2 | Local dedup (D1, D2, N2): single `file_sha` call; preview uses `registry.restore_order`; `WORKSPACE_FORMAT`/`MIN_WORKSPACE_FORMAT` constants into env/compat. | R0 tests green | same |
| R3 | `fsio.write_bytes` delegates entry shape to `integrity.bytes_entry` (new tiny fn; `doc_entry` keeps its doc API). | R0(b) | same |
| R4 | Policy single-home (F3): `policies.RESTORE_ADVICE` + `INCLUSION_POLICY`; `apply`/`save` consume. **Strings byte-identical** (secrets tests pin them). | secrets suite | same |
| R5 | Stage `"capture"` (S1): errors vocabulary + `_capture_one` uses it. **Deliberate report change**, documented; update stage-vocabulary test + design §F. | core stage test updated first (RED→GREEN) | all green |
| R6 | **Module move** (F1/F2, §4.1–4.5): create `meta.py`; move capture+selection into `save.py`; move selection/backup/loading into `apply.py`; `registry.restore_order`; delete `coordinator.py`. Update 8 test import sites + panel import. No symbol bodies changed beyond the move. | all suites (imports updated in-step) | all green; architecture test extended to ban `.meta` in providers |
| R7 | Naming/readability (N3, N4): rename `plan` dicts to `run`; `wsRestore` fallback delegates to `wsLoadLast(done)`. | suites | same |
| R8 | Data-driven `_post_restore_refresh` (drop the 5-branch if-chain for a table). | live_refresh suite | same |

Explicitly NOT done (would be churn without payoff): renaming public report keys;
changing manifest/file formats; merging provider files; typing the `bridge` param
(no shared type exists — duck-typed by design); caching `_build_sha`.

## 6. Behavior preservation & rollback

- R1–R4, R6–R8: **byte-identical outputs** (manifest, reports, env JSON, skip rows).
  Guaranteed by: determinism tests (save twice → identical report), corruption-matrix
  tests, secrets string pins, publish-failure pins. Any diff = step failed.
- R5 is the only intended behavior change: capture failures report
  `stage:"capture"` with correct advice. Rollback: revert commit; stage list returns
  to 11; no stored data references the stage name.
- Each step is one commit → `git revert` restores exactly; no step changes the
  on-disk snapshot format, so snapshots saved before any step restore identically after.

## 7. Tests required per step

See table (R0 new characterization: expand-strict transitive, entry-shape equality,
gate evidence fields; R5 RED→GREEN stage test). After every step: the 9 workspace
pytest suites + `test_bridge_slots` + `test_window_catalog` + JS
`test_workspace_panel.mjs`. Final: full pytest + `npm run test:js` + quality gate.

## 8. Documentation changes after the refactor

- Design doc §C module map: `coordinator.py` row → `meta.py` + honest save/restore/apply
  descriptions; §F matrix + stage list: add `capture`; §A.2 drift items 1–8 ticked
  where this work resolves them; §L/M unchanged.
- ADR-0001: no format/decision changes — add one line to the outcome note
  (module layout realized as meta/save/restore/apply).
- `persistence/workspace/__init__.py` docstring: "coordinator" wording → meta.

## 9. Measurable before/after (collected at the end)

| Metric | Before | After (measured 2026-09-25) |
|---|---|---|
| Cross-module **private** imports inside services/workspace | 3 import lines / 7 names | **0** (radon/AST sweep) |
| Modules named contrary to content | coordinator.py | 0 — meta/save/restore/apply |
| restore.py LOC (preview-only) | 221 | 71 |
| Policy-string homes | 3 | 1 (policies.py, guarded by test) |
| Duplicated hash/ordering/literal sites | 5 (D1, D2, N2×2, env literal) | 0 (integrity.bytes_entry, registry.restore_order, policies, meta) |
| Stage vocabulary correctness | capture failures mislabeled "apply" | precise `capture` stage (12-stage vocabulary) |
| Worst function (py) | 27 LOC / CC 8 (apply.restore_workspace) | 27 LOC / CC 8 — no regressions |
| Test count (workspace pytest / JS panel) | 96 pytest + 14 JS | 123 pytest (8 suites; +27 incl. characterization) + 17 JS |
| Modules / LOC in scope (persistence/workspace + services/workspace + panel) | 20 / 2211 | 20 / 2222 (same file count; net +11 lines of tests-informed guards/comments) |
