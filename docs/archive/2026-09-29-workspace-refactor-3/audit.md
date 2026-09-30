# Global Saving System — audit #3 and TDD refactor design (2026-09-29)

**Scope:** the global save/restore system as it stands at `97f4ed3` — the code *added* across
`1c0ff4c5e5a6ba904ae4922df20e093392fc116a..97f4ed374861bb2055e2f9303d316263e99c8f89`
(35 commits, of which 9 are `fix(workspace)`/`refactor(workspace)`/`docs(workspace)`) plus the whole
feature it hardens (`app/persistence/workspace/**`, `app/services/workspace/**`,
`app/ui/panels/workspace.py`, `app/ui/web/js/panels/workspace.js`, `tests/test_workspace_*.py`,
`tests/js/test_workspace_panel.mjs`, `docs/current/GLOBAL_WORKSPACE_SAVE_DESIGN.md`).
Legacy code outside the integration seams is out of scope. No legacy refactor is proposed.

**Previous audits, not repeated here:**
* `docs/archive/2026-09-25-global-workspace-save/` (structure/size pass — its S1–S3 steps landed here)
* `docs/archive/2026-09-28-workspace-refactor-2/audit.md` (failure edges — steps 1–10 landed in
  `39d68c3`…`4843edb`; §8 of that doc is the execution log of the range under review)

This pass looks at what is left **after** audit #2, and at the three seams audit #2 declared
out of scope (U2 cross-language refresh table, V5/V6 private seams, S6/S7 report-format rows).
Every High/Medium finding below was **reproduced against the real code** by a throwaway probe
(P1–P14, §3), not inferred from reading. Probes were deleted after the audit; each became a
committed red test first (plan step 0 / steps 7–11).

---

## 1. Code map of the added feature

```
app/persistence/workspace/          stdlib only; no app imports (test_workspace_architecture)
  errors.py       (63)   STAGES vocabulary + WorkspaceError(domain, stage, cause, evidence, advice)
  integrity.py    (65)   canonical_bytes / sha256_bytes / bytes_entry / doc_entry / safe_rel_path / file_sha
  manifest.py     (84)   FORMAT_NAME, WORKSPACE_FORMAT, MIN_WORKSPACE_FORMAT, build/check/parse/read, entry_for
  fsio.py        (134)   sanitize_name, snapshot_dir_name, new_temp_dir, write_bytes, write_report,
                          publish (rename → EXDEV copy), _with_backoff, copy_tree, remove_tree
app/services/workspace/
  provider.py    (106)   StateProvider contract + CaptureResult + ApplyOutcome
                          + config_dir / read_live_json / live_capture (the shared capture helpers)
  registry.py     (51)   the provider table: RESTORE_ORDER, _TABLE, get, all_providers, restore_order
  meta.py         (79)   config paths, utc_now_iso, snapshot_id_for, app_meta (git subprocess),
                          compat_block, log_message, live_run_error, META_FILE, RECENT_CAP
  save.py        (235)   SaveRequest, Capture, selection, capture_all (state_lock), file_docs,
                          domain_entries, _stage, _publish_save, _publish_failed
  restore.py     (101)   PREVIEW ONLY: preview_restore, _preview_row, _file_status, _remap_notes
  apply.py       (276)   RESTORE MUTATION: _preflight, selection_providers, expand_strict,
                          _restore_row, _restore_one, _apply_domain, _rollback, _finish, _reconcile_all
  gates.py        (64)   load_files / load_one / _gated  (safe path → size → sha-256 → parse)
  recover.py     (102)   RECOVERY_DIR, _recovery_dir, _affected_files, _copy_affected, backup_live, prune_recovery
  reports.py      (69)   save_report / restore_result / restore_report / preview_report
  snapshot_index.py (69) record_snapshot / record_restore / recent_snapshots / last_snapshot / last_restore
  providers/     (9 files, 744 LOC)
    session.py    (198) _SessionDomainProvider + SessionSettingsProvider + GridWindowProvider  (2 domains, 1 file)
    arena_state.py(108) queue/urls/folder/prompt/settings/jobs  → state/app_state.json
    preset_stores.py(76) WindowPresetsProvider + ArenaPresetsProvider
    cooldowns.py  (98)  timers / per-URL stats / tab aliases
    policies.py   (76)  CaptchaKeysProvider (secret) + RecordingsProvider (opt-out)  — no file, never exported
    undo.py       (55)  the ONE global undo timeline (RULE 12)
    job_history.py(53)  append-only finished-job log
    captcha_stats.py(52) counters + per-site + balance (balance marked stale on restore)
app/ui/panels/workspace.py      (185)  6 frozen slots + _answer crash guard + _REFRESH_TABLE + clamp_to_screen
app/ui/web/js/panels/workspace.js (368) mount + flow + per-domain checklist + result + RULE 24 live sync
tests/    test_workspace_{core,providers,save,restore,secrets,architecture,panel,live_refresh,split_helpers,failure_edges}.py
          → 10 files, 1 790 LOC, 154 tests
tests/js/test_workspace_panel.mjs (332)  18 tests
docs/    docs/current/GLOBAL_WORKSPACE_SAVE_DESIGN.md (544) + docs/current/WORKSPACE_REFACTOR_AUDIT.md (52)
```

**Import direction today (verified by `tests/test_workspace_architecture.py`):**
`panels/workspace.py` → `services/workspace/*` → `persistence/workspace/*` + `core/*`.
`providers/*` must not import `.save` / `.restore` / `.meta` / `.apply` / `.coordinator`.
**One gap the test does not cover:** `save.py` imports `providers.policies` (finding **M4**).

**Transaction boundaries.**
* **Save** — one temp sibling folder; `manifest.json` written **last** (the commit marker);
  publish = one same-volume `os.rename`, `EXDEV` → copy-then-rename. A save that fails before the
  manifest leaves nothing claiming to be a snapshot; a failure after the rename leaves a valid
  snapshot plus a `report_note`.
* **Restore** — one recovery backup for the whole run, then **one transaction per domain**
  (pre-apply capture → `apply()` → rollback to the capture on exception). **No cross-domain
  rollback by design.** Every non-`restored` row is `skipped` with a stage; `damaged` (apply *and*
  rollback both failed) forces the whole run to `failed`.
* **Schema ownership** — `manifest.workspace_format` (min 1, current 1) is owned by
  `persistence/workspace/manifest.py`; each provider owns its `schema_version` +
  `supported_migrations`. Only `grid_window` accepts older versions (4…`GRID_VERSION`).

**Measured baseline at `97f4ed3` (this machine, same commands before and after every step):**

| Metric | Value |
|---|---|
| Python modules / LOC (persistence + services) | 26 / **2 230** |
| Python panel / JS panel | 185 / **368** LOC |
| Python functions | 199 |
| Max function LOC | **22** (`manifest.build_manifest`, carries an `ideal-size` note) |
| Max class LOC / methods per class | 64 (`CooldownsProvider`) / 7 |
| Max cyclomatic complexity | **10** (`integrity.safe_rel_path`) — fail line is >10 |
| Max params | 5 (`WorkspaceError.__init__`, `self` excluded) — fail line is >4, legacy-baselined |
| `tools/verify_quality.py` on the workspace scope | 0 fail, 0 warn |
| Workspace pytest / JS tests | **154 pass** / **18 pass** |
| Full pytest suite | **3 008 passed, 6 skipped, 3 failed** (pre-existing, §9) |
| Coverage, workspace scope (`--branch`) | **93 %** line+branch combined; panel 83 % |

---

## 2. Review areas — what was checked and what it found

| Review area | Verdict |
|---|---|
| module & folder structure | Good. 26 modules, one responsibility each, no god file after audit #2. Two nits: `save.py` (235) and `apply.py` (276) are both inside the RULE 18.2 ideal; `workspace.js` (368) is over it. |
| function/class responsibilities | Clean. Max 22 LOC, all inside the 4–20 band or just above. No long function, no god class. |
| interface & provider boundaries | Sound, with two leaks: `save → providers.policies` (**M4**) and `restore_advice` used through `getattr` but never declared on the contract (**M2**). |
| cohesion / coupling / dependency direction | Correct direction, one inverted edge (**M4**), one deferred import (`capture_all` → `live.feed.state_lock`, documented and correct). |
| duplicated logic / unnecessary abstractions | Validator shape repeated in 5 providers (**L10**); `_REFRESH_TABLE` / `WS_LIVE_PANELS` / `WS_CONFIG_RELOADERS` name domain ids as raw strings in two languages (**M7**, audit #2's U2). No speculative abstraction found. |
| long functions / large classes / deep nesting / excess params | Nothing over the RULE 16 fail lines. `WorkspaceError.__init__` has 5 params, legacy-baselined with a reason. |
| naming / typing / validation / error handling | One undeclared attribute (**M2**), weak `object` typing on `Capture.result` / `SaveRequest.selected`, one swallow-all log helper (**L1**). |
| save/restore transaction boundaries | Correct and well documented — but the *save* boundary holds the queue lock and the *restore* boundary does not (**M6**, probe P10: 0 `state_lock` uses during a full restore). |
| corruption handling / rollback / partial restore | Strong after audit #2 (P1/P2/P3 of audit #2 all fixed). Remaining: **`required` is inert** (**H4**) and the **on-disk restore report disagrees with the UI reply** (**H3**). |
| schema/version/migration ownership | Correct. Two dead artefacts around it: `reports.save_report(published=…)` is always `True` (**M3**), and preview never consults the schema gate or `validate` (**H5**). |
| logging & warning consistency | A **refused save logs nothing** (**H2**) while a successful save logs one line — RULE 2. Everything else is consistent. |
| testability / missing seams | 154 + 18 tests, 93 % coverage — strong. Untested seams: same-second publish, failed-save logging, on-disk report content, `required` semantics, preview-vs-validate (**H1–H5**), and the implicit `DEFAULT_SESSION` key set (**M9**). |
| documentation accuracy / code drift | Five real drifts, incl. the design doc's own status line contradicting its title (**D1**). §7. |

---

## 3. Findings (evidence → severity → risk)

Severity is impact on the user's data or on truthfulness of what the app tells them.
**Probes** are real code runs; the probe file was deleted after the audit.

### 3.1 High — reproduced defects

| id | Sev | File / symbol | Evidence (probe → observed) | Risk if unfixed |
|---|---|---|---|---|
| **H1** | High | `fsio.snapshot_dir_name` + `fsio.publish` + `save.save_workspace` | **P1**: two `save_workspace(bridge, SaveRequest(name="dup"))` calls inside one wall-clock second → first `ok:True`, second `{"ok": False, "error": "publish failed: target already exists: …/workspaces/dup_20260101-000000"}`. Folder name is `<name>_<UTC yyyyMMdd-HHMMSS>`; `publish()` raises `FileExistsError` when the target exists. Audit #2 fixed exactly this class for the **recovery** folder (`recover._recovery_dir` adds `-02`, `-03`… — `8a341c7`, C2) and left the **snapshot** folder behind. | Double-clicking Save, a scripted save, or a save fired by an undo/preset action within one second **fails with a scary "publish failed"** even though the first snapshot is fine. The partial temp folder is also left on disk as `<target>.tmp-…` (the `_publish_failed` path renames the *temp*, not the collision). |
| **H2** | High | `save._abort_result`, `save._publish_failed` | **P3**: `get("arena_state").validate → "boom"` ⇒ `reply = {"ok": False, "error": "domain(s) failed to capture: arena_state …"}` and `log_message` called **0 times**. Compare `_publish_save`, which logs `💾 Workspace saved: …` on success. | RULE 2 violation: the two ways a save can fail are invisible in the Activity Log / `logs/arena.log`. The user sees the error only in the Workspace window, which is not on screen when the save came from a preset/undo/unattended action. |
| **H3** | High | `panels/workspace.py::_do_restore` vs `apply._finish` | **P4**: after a full restore, `reply["reconciled"]` has **8** notes (the three provider `reconcile` notes + `geometry may need clamping…` + the five RULE 24 `_REFRESH_TABLE` pushes), while `reports/restore-report.json` in the same folder has **3** — the five refresh notes are added *after* `fsio.write_report` already ran. | The persistent record of the run understates what was done. Anyone (or any tool) reading the snapshot's report cannot see that the live UI was re-pushed, or that a push **failed** — `_emit_refresh` failures are notes that are likewise never persisted. |
| **H4** | High | `provider.StateProvider.required` (docstring line 80) vs `save.save_workspace` | **P5**: forcing `get("captcha_stats").capture` to fail (`ok=False`, a *non*-required domain) ⇒ save returns `{"ok": False, "error": "domain(s) failed to capture: captcha_stats …"}`. The abort condition is `if failed and not request.allow_partial` — `required` is never read on the save path; it is only read by `reports.save_report` to fill `failed_required`. The class docstring says *"save aborts (unless allow_partial) when a **required** domain fails"*. | The published contract, the manifest field, and the code disagree. A transient `captcha_stats.json` read error blocks a workspace checkpoint entirely; the user must tick "allow partial" without knowing why. |
| **H5** | High | `restore._preview_row` (manifest-only by design, §C.6.1) | **P7**: a snapshot whose `state/captcha_stats.json` holds `{"per_site": "not-an-object"}` (manifest re-stamped, so the size/sha gates pass) previews as **`('captcha_stats', 'ok')`**; the restore that follows returns `success_with_warnings` with a `semantic` skip row. The same is true for an unsupported `schema_version` and for anything `migrate` would touch. | The per-domain checklist the user ticks before restoring **promises a restore that will be refused**. This is the one place where preview and restore disagree by construction, and it is the screen the user trusts most. |

### 3.2 Medium — structure, ownership, duplication

| id | Sev | File / symbol | Evidence | Risk |
|---|---|---|---|---|
| **M1** | Medium | `registry._TABLE` (class tuple) + `registry.RESTORE_ORDER` | **P13**: a new `StateProvider` subclass is **silently unregistered** — `registry.get("forgotten") is None` for a class that exists in `providers/`. Two lists describe the same set; only `test_registry_table_matches_restore_order` notices, and only for the ids already in both. | RULE 10 ("one table, no second list"). A contributor adds a provider, the architecture test passes, and the domain silently never saves or restores. |
| **M2** | Medium | `providers/policies.py::RESTORE_ADVICE` (line 20-21) + `apply._policy_row` (line 99) | The dict is **dead** — `grep -rn RESTORE_ADVICE` returns only its own definition. Its comment claims *"The one restore advice per policy domain (apply._policy_row consumes this)"*; `_policy_row` actually reads `getattr(provider, "restore_advice", "")`, an attribute **not declared** on `StateProvider`. | Dead code whose comment actively misleads, plus a `getattr` for a contract slot that should be part of the contract (a typo in a provider would degrade silently to "no advice"). |
| **M3** | Medium | `reports.save_report(published: bool)` (line 18, 25) | The only caller (`save._stage` line 190) passes `published=True`; `save._publish_save` returns `_publish_failed(...)` *before* a report is ever built. `grep published` confirms one call site. Coverage confirms it: `reports.py:26` is the only uncovered line in the file. | A dead branch inflates CC 7→5 would drop, and a reader must work out why a save report can claim "not published" when the design says a non-published save leaves no report at all. |
| **M4** | Medium | `save.py` line 24: `from .providers.policies import INCLUSION_POLICY` | A *service* imports one *provider* module for a metadata constant. `providers/policies.py` in turn imports `app.services.workspace.provider`. The architecture test bans the reverse edge only. | Wrong dependency direction (RULE 10: the manifest/registry is the one registry, not a provider file). Adding a second policy domain makes `save.py` import two provider modules. |
| **M5** | Medium | `meta.app_meta` + `save._write_env` + `save._snapshot_manifest` | **P2**: one `save_workspace` ⇒ **2** `subprocess.run(["git","rev-parse","--short","HEAD"])` spawns (`app_meta` is called once per function). `compat_block()` is also called twice, and `_write_env` re-derives `grid_version` / `workspace_format` / `format` — three of the four keys `compat_block()` already owns. | Two process spawns (5 s timeout each) per checkpoint, on the Qt main thread, for a value that is constant for the process. Two homes for the same three format constants. |
| **M6** | Medium | `save.capture_all` (holds `state_lock`) vs `apply._apply_domain` (pre-apply capture + apply, no lock) | **P10**: a full restore uses `state_lock` **0 times**; a full save uses it once around the whole capture pass. The save side documents the lock as *"One coherent capture pass under the queue funnel's lock (snapshot boundary)"*. | Between a domain's pre-apply capture and its `apply`, a background writer (pool cooldown push, watcher autosave, a Qt slot) can change live state; the rollback then reverts that change. Narrow window, real corruption path, and the asymmetry is invisible from the restore side. |
| **M7** | Medium | `restore._remap_notes` (`"arena_state"`), `panels/workspace.py::_REFRESH_TABLE` (5 ids), `workspace.js` `WS_LIVE_PANELS` / `WS_CONFIG_RELOADERS` (6 ids) | Domain ids are raw strings outside `registry.RESTORE_ORDER`. A renamed domain silently stops getting its live refresh and stops producing a remap note — no test fails. | RULE 10. A domain rename is a five-site edit with no compiler and no failing test. |
| **M8** | Medium | `panels/workspace.py::_answer` wraps 2 of 6 slots | `get_workspace_state`, `preview_workspace` and `browse_workspace_folder` call their worker directly. `_state_payload` touches three `snapshot_index` readers (each of which does a `Path.exists()` on a path from a JSON file); `preview_restore` does `path.stat()` after `path.exists()`. | The guard policy from audit #2 (U1) is per-slot and unwritten. A crash in a read slot returns `''` to QWebChannel, which `wsParse` turns into `{ok:false,error:'bad reply'}` — a *misleading* message for what is really an internal crash. |
| **M9** | Medium | `providers/session.py::settings_keys()` | **P14**: the captured key set is `DEFAULT_SESSION` minus the grid trio = **24 of 27** keys, computed at call time. Nothing pins the set. | Adding a key to `DEFAULT_SESSION` silently changes what a workspace snapshot contains — including any future secret-shaped key. The RULE 20 redaction decision for this domain has no test behind it. |

### 3.3 Low — hygiene

| id | File / symbol | Evidence |
|---|---|---|
| **L1** | `meta.log_message` | `except Exception: pass` — a logging helper that cannot report that logging failed. Acceptable (it is a guard) but it is the only place in the package where an exception is fully silent. |
| **L2** | `panels/workspace.py::_do_restore` | `if restored:` then `if "grid_window" in restored:` — a redundant nesting level around a single guarded line. |
| **L3** | `persistence/workspace/errors.py` | Two truncation limits with no shared name: `self.cause = str(cause)[:400]` and `_short(value, limit=120)`. |
| **L4** | `snapshot_index.recent_snapshots` | A **read** that writes the index file when it prunes. The Workspace window calls it on every open and after every save. |
| **L5** | `providers/cooldowns.py::reconcile` | `load_entries(cooldown_file(bridge))` and `load_stats(cooldown_file(bridge))` — the same path resolved and read twice. |
| **L6** | `providers/session.py::SessionSettingsProvider.reconcile` | `bridge.config.get_state(key)` is called twice per key (once for the value, once for the `is not None` test). CC 6. |
| **L7** | `restore._remap_notes` | `except (OSError, ValueError): pass` — a remap note that cannot be produced is indistinguishable from "no remap needed". |
| **L8** | `save.inclusion_policy()` | A one-line re-wrap of `dict(INCLUSION_POLICY)`; `policies.INCLUSION_POLICY` is imported directly anyway. |
| **L9** | `app/ui/web/js/panels/workspace.js` (368) | Over the RULE 18.2 file ideal (150–300) with no `ideal-size` note, and it holds two responsibilities: bridge flow/state and DOM rendering. |
| **L10** | `stats_error` / `sections_error` / `history_error` / `history_error(undo)` / `_StoreProvider.validate` | Five near-identical "is it a dict / are these members the right type" validators, each re-deriving the same `isinstance` ladder. RULE 16.4 duplication. |
| **L11** | coverage | `fsio.py` misses 86-87, 112, 124, 132-133; `providers/session.py` misses 16 lines (52-58 `_states_error` branches, 66/73 `_geometry_error`, 99/107/177/186); `providers/cooldowns.py` 85 %; `providers/job_history.py` 80 %. |
| **L12** | `tests/test_workspace_failure_edges.py:164`, `tests/test_workspace_providers.py:111,177` | vulture: 3 unused locals and one unsatisfiable ternary in the feature's own tests. |

### 3.4 Rejected as non-findings (checked, deliberately kept)

* **Shared `state/session.json` for two domains** — documented, order-safe, and the merge is
  deterministic (`file_docs` merges per key, both providers apply only their own keys). Keeping it.
* **No cross-domain rollback** — a design decision (§C.6.7), and `damaged → failed` already makes
  the outcome honest.
* **`preview` doing its own size check instead of reusing `gates`** — §C.6.1 chose preview
  manifest-only. Audit #3 changes that (step 11) by **reusing** `gates.load_files`, not by adding a
  second gate implementation.
* **Cross-language refresh table (audit #2's U2)** — Python `_REFRESH_TABLE` and the two JS lists
  cannot be unified without a bridge round-trip per domain. Audit #3 fixes the *ids* (M7) and leaves
  the language split, stated.
* **`app_meta` calling git at all** — one call per save is fine; two is the defect (M5).
* **The `reports`/`recover` split and the `run`-dict context objects** — measured, readable, inside
  every limit. `run` as a context dict is fine; only its use as an *out*-channel is noted (M10/L).

---

## 4. Proposed interfaces / boundaries (only where they remove real duplication or coupling)

1. **One provider table, one source of truth (M1).** `registry` gains
   `PROVIDER_CLASSES: tuple[type[StateProvider], …]` as the single registration list and derives
   `_TABLE` **and** an `ORDER_OF: dict[str, int]` from it; `RESTORE_ORDER` becomes the *sorted-by-
   dependency* view of that one list. New invariant test: **every** `StateProvider` subclass defined
   anywhere under `app/services/workspace/providers/` is in the table. A forgotten provider fails a
   test instead of vanishing. No new class, no new interface.
2. **One metadata home (M4 + M5).** `meta.py` gains `inclusion_policy()` and keeps `app_meta` /
   `compat_block`. `save.py` stops importing `providers.*` entirely; the architecture test is
   extended from "providers must not import services" to "services must not import `providers.*`
   except `registry`". `_write_env` composes from `compat_block()` instead of re-deriving three keys,
   and `_stage` computes `app_meta`/`compat_block` **once** and passes them to both consumers.
3. **The contract declares what `apply` reads (M2).** `StateProvider.restore_advice: str = ""`
   becomes a class attribute, so `_policy_row` drops its `getattr`. `RESTORE_ADVICE` is deleted.
4. **`reports.save_report` loses `published` (M3).** The report is only ever written for a published
   snapshot (the manifest is the commit marker); the parameter and its dead branch go.
5. **Preview reuses the restore's gates (H5).** `restore._preview_row` keeps its identity/status
   columns but asks `gates.load_files` for the parsed doc and runs `provider.validate` + the schema
   gate. New statuses are **additive** (`invalid`, `unsupported_schema`, `parse`); existing ones
   (`ok`, `size_mismatch`, `missing`, `unsafe_path`, `excluded`, `not_in_manifest`) are unchanged, so
   the JS checklist keeps working. *This is the only proposed change that adds a public value to a
   frozen shape, and it is additive-only.*
6. **One domain-id vocabulary for the live refresh (M7).** `_REFRESH_TABLE` is asserted against
   `registry.RESTORE_ORDER` by a test, and the JS lists are asserted against a Python-exported
   payload. No new bridge slot is added (the slot surface is frozen at 141).

**Explicitly not proposed:** a `WorkspaceError` result type, a shared cross-language refresh
registry, a per-domain transaction class, a `plan()` object, a `StateProvider` ABC, or a generic
"domain middleware" — each was considered and buys nothing the 26 small modules do not already do.

---

## 5. Ordered refactor plan — small, independently testable, reversible

`S` = structural (behaviour-preserving; the existing suite is the equivalence gate).
`B` = behaviour (a red test that fails on `97f4ed3` is written **first**, then the fix).
Each step is one commit. Rollback of any step = `git revert <sha>`; no step changes a file format
except the **additive** status values in step 11, and a revert re-reds exactly that step's test.

| # | Kind | Change | Tests before → after |
|---|---|---|---|
| **0** | T | Characterization tests for the five untested seams (H1–H5) and the implicit key set (M9). These pin **today's** behaviour and are the equivalence gate for the S steps. | 154 → **169**; all green on `97f4ed3` |
| **1** | S | **M1** — one provider table: `PROVIDER_CLASSES` is the single list; `RESTORE_ORDER` derived; new test fails for an unregistered subclass. | architecture + registry tests; suite green |
| **2** | S | **M2** — delete `policies.RESTORE_ADVICE`; declare `StateProvider.restore_advice`; `_policy_row` reads the contract. | secrets + restore tests; suite green |
| **3** | S | **M3** — drop `save_report(published=…)` and the dead branch. | save/restore report tests; `reports.py` 93 % → 100 % |
| **4** | S | **M4 + M5** — `meta.inclusion_policy()`; `save` stops importing `providers.*`; `app_meta`/`compat_block` computed once per save; architecture test extended. | determinism tests (byte-identical reports) stay green; subprocess count 2 → 1 |
| **5** | S | **M7 (Python half) + M8** — `_REFRESH_TABLE` ids asserted against `RESTORE_ORDER`; one `_answer` for every JSON slot (`get_workspace_state`, `preview_workspace`, `browse_workspace_folder`). | panel tests; new test: a crashing read slot answers `{"ok": false, …}` |
| **6** | S | **L10 + L3** — one small `object_doc` / `members` validator helper in `provider.py`; the five duplicate validators use it; the two truncation limits get shared names. | provider validator tests; vulture clean |
| **7** | S | **M6** — the restore per-domain transaction runs under the same `state_lock` the save capture uses. | new test: a background writer cannot interleave between capture and apply; deadlock guard (lock acquired once per domain, never nested) |
| **8** | S | **L1, L2, L4, L5, L6, L7, L8** — hygiene: `_do_restore` flatten, prune moved out of the read path, one `cooldown_file` read, one `get_state` per key, remap read failure becomes a note. | existing tests; no new behaviour |
| **9** | B | **H1** — a same-second second save gets its own folder (the rule `recover._recovery_dir` already uses). **RED:** `test_two_saves_in_one_second_both_publish`. | new red test → green |
| **10** | B | **H2** — a refused or failed save logs **one** error line. **RED:** `test_refused_save_logs_one_error_line`, `test_publish_failure_logs_one_error_line`. | new red tests → green |
| **11** | B | **H3** — the notes the panel adds after the restore reach `reports/restore-report.json` (the panel hands them to the report before it is written; `record_restore` keeps its ordering). **RED:** `test_restore_report_on_disk_has_the_refresh_notes`. | new red test → green |
| **12** | B | **H4** — `required` means what its docstring says: a non-required failure downgrades the save to `partial`; a required failure still refuses without `allow_partial`. **RED:** two tests (non-required ⇒ `partial` + listed in `errors`; required ⇒ refused). | new red tests → green; manifest `snapshot_kind` for a partial-with-no-required-failure becomes `"partial"` (already possible) |
| **13** | B | **H5** — preview reuses `gates.load_files` + `provider.validate` + the schema gate. Additive statuses only. **RED:** `test_preview_marks_a_semantically_invalid_domain`, `test_preview_marks_an_unsupported_schema`. | new red tests → green; existing 18 JS tests keep passing |
| **14** | S | **L9** — split `workspace.js` (368) into `panels/workspace/flow.js` + `panels/workspace/render.js` with `workspace.js` as the thin mount, following the `panels/url-list/` folder precedent. | `node --test tests/js` + `tests/test_ui_wiring.py` + `tests/js/test_boot_all_panels.mjs` |
| **15** | docs | **D1–D4** + SoR invariant + `docs/README.md` + `docs/current/WORKSPACE_REFACTOR_AUDIT.md` → `docs/archive/2026-09-25-workspace-refactor-1/`. | — |

**Order rationale.** Steps 1–8 are provably behaviour-preserving and land first so the
behaviour changes (9–13) sit on a clean, understood base. The behaviour steps run cheapest-risk
first (H1, H2) and end with the two that touch a user-visible contract (H4 semantics, H5 statuses),
each isolated in its own revertable commit.

---

## 6. Behaviour-preservation and rollback strategy (per step)

* **Global invariants frozen by every step 1–8:** the 26 module paths; the manifest key set
  (`format`, `workspace_format`, `snapshot_id`, `parent_snapshot_id`, `name`, `description`,
  `snapshot_kind`, `created_utc`, `updated_utc`, `app`, `compat`, `domains`) and every per-domain
  entry key; the report key sets in `reports/save-report.json` and `reports/restore-report.json`;
  `recovery.json`; the six slot names **and signatures**; the eleven domain ids; `RESTORE_ORDER`
  contents; the `STAGES` vocabulary; the preview statuses `ok` / `size_mismatch` / `missing` /
  `unsafe_path` / `excluded` / `not_in_manifest`; the restore statuses `restored` / `skipped` /
  `damaged` and the result vocabulary `success` / `success_with_warnings` / `failed` /
  `partial`.
* **Equivalence gate for S steps:** the full workspace suite (169 after step 0) plus
  `tests/test_workspace_architecture.py`, plus `python tools/verify_quality.py` (workspace files
  must stay at 0 fail / 0 warn), plus the byte-determinism tests
  (`test_save_is_deterministic_for_unchanged_state`, `test_save_report_is_deterministic_for_unchanged_state`)
  which fail if any report/manifest byte moves.
* **Rollback:** every step is a single commit with no file-format change, so `git revert <sha>`
  restores the exact prior behaviour. Steps 9–13 each own a red test; reverting a B step re-reds
  exactly that test and nothing else, which is the signal that the revert was clean.
* **Step 14 (JS split)** is the only step that can break a non-workspace suite, because
  `index.html` script order and `window.X` publication are checked by `tests/test_ui_wiring.py` and
  `tests/js/test_boot_all_panels.mjs`. It is therefore last among the code steps and runs against
  both JS gates plus the full Python suite.
* **Step 12 is the only step that relaxes a safety behaviour** (a non-required capture failure no
  longer refuses the save). It is isolated, documented in the SoR row, and reverts with one commit.
* **Never mixed:** no commit contains both a structural move and a behaviour change.

---

## 7. Tests required before and after each refactor

**Before (step 0, all on `97f4ed3`, all green — they pin today's behaviour):**

| Test | Pins |
|---|---|
| `test_workspace_characterization.py::test_a_second_save_in_the_same_second_is_refused` | H1 today: `ok:False`, `"target already exists"` |
| `::test_a_refused_save_writes_no_log_line` | H2 today: zero `log_message` calls |
| `::test_the_on_disk_restore_report_has_only_the_provider_notes` | H3 today: 3 notes on disk, 8 in the reply |
| `::test_a_non_required_capture_failure_still_aborts_the_save` | H4 today: `required` is inert |
| `::test_preview_calls_a_semantically_invalid_domain_ok` | H5 today |
| `::test_the_captured_session_key_set_is_exactly_these_24_keys` | M9 today: the set is pinned, so a future `DEFAULT_SESSION` addition is a deliberate, visible decision |

**After (the B steps' red tests, each written before its fix):**

| Step | Red test first |
|---|---|
| 9 | `test_two_saves_in_one_second_both_publish` (and the folder names differ) |
| 10 | `test_refused_save_logs_one_error_line`, `test_publish_failure_logs_one_error_line` |
| 11 | `test_restore_report_on_disk_has_the_refresh_notes` (UI reply == on-disk `reconciled`) |
| 12 | `test_a_non_required_capture_failure_saves_a_partial_snapshot`, `test_a_required_capture_failure_still_refuses` |
| 13 | `test_preview_marks_a_semantically_invalid_domain`, `test_preview_marks_an_unsupported_schema`, `test_preview_of_a_healthy_snapshot_is_unchanged` |

**After (the S steps' new tests, green-on-arrival because they pin the new structure):**

| Step | Test |
|---|---|
| 1 | `test_every_provider_class_is_registered` (fails today for an unregistered subclass) |
| 2 | `test_restore_advice_is_part_of_the_provider_contract` (`StateProvider.restore_advice == ""`) |
| 3 | `test_save_report_has_no_published_flag_only` — fold into the existing determinism test |
| 4 | `test_services_never_import_provider_modules`, `test_one_save_spawns_at_most_one_git_call` |
| 5 | `test_refresh_table_names_registered_domains`, `test_a_crashing_read_slot_answers_ok_false` |
| 6 | existing validator tests; `vulture` clean |
| 7 | `test_restore_holds_the_state_lock_around_each_domain_transaction` |
| 8 | existing tests only (behaviour-preserving by construction) |
| 14 | all 18 existing `test_workspace_panel.mjs` tests, plus `test_ui_wiring.py` and `test_boot_all_panels.mjs` |

**Not covered, and said so:** a real-Chromium end-to-end save/restore round trip. Every test here is
in-process against real stores and a real filesystem (`RULE 8`); the browser layer is not part of
the workspace feature, and `docs/manual_test_checklist.md` owns the manual pass.

---

## 8. Documentation changes required after the code is reorganized

1. **`docs/current/GLOBAL_WORKSPACE_SAVE_DESIGN.md` line 4 — D1.** The status line still reads
   *"design gate — no production code written"* while the title says *"(implemented…)"*. Rewrite the
   status line to state what is true: implemented, audit #3 landed, with pointers to both audit
   docs. Same edit for the four "Next: W…" phase rows in §I, which describe work that is done.
2. **`docs/current/WORKSPACE_REFACTOR_AUDIT.md` — D2.** It is an audit *record* and lives in
   `docs/current/`, which RULE 17 reserves for what is true today. Move it to
   `docs/archive/2026-09-25-workspace-refactor-1/audit.md` and replace it in `docs/current/` with a
   pointer line, exactly as RULE 17 prescribes. `docs/README.md` index row updated in the same change.
3. **`app/services/workspace/providers/policies.py` lines 20–21 — D3.** Delete `RESTORE_ADVICE`
   (step 2); the comment disappears with it.
4. **`app/services/workspace/provider.py` line 80 — D4.** The `required` docstring is rewritten to
   match the implemented behaviour (step 12) and says plainly that `allow_partial` is the user's
   override.
5. **`§F` fault matrix in the design doc** — add the two rows this audit adds: `rollback`-after-a-
   failed-pre-apply-capture, and the preview-vs-restore gate divergence that step 13 closes.
6. **`§M` (RULE 24 live-sync table)** — it is the only place that lists the restored-domain → refresh
   mapping across both languages. After step 5 it is checked by a test instead of by reading; the
   doc keeps the table and gains the sentence "the ids in this table are asserted against
   `registry.RESTORE_ORDER` by `tests/test_workspace_architecture.py`".
7. **`docs/current/SYSTEM_OF_RECORD.md`** — one new invariant row for audit #3 (I-81) covering:
   a same-second save never refuses, a failed save always logs, the on-disk report equals the UI
   reply, `required` is honoured, and the preview checklist is gate-accurate. Plus the history-of-X
   link to this doc.
8. **`docs/current/CODE_VERIFICATION.md`** — the coverage floors move if the full-suite numbers move.
9. **No new top-level doc** (RULE 17): this audit lives at
   `docs/archive/2026-09-29-workspace-refactor-3/audit.md`; its durable rows move into
   `SYSTEM_OF_RECORD.md` and the doc map.

---

## 9. Before/after quality metrics (measured, same commands)

| Metric | Before (`97f4ed3`) | Target after | Where measured |
|---|---|---|---|
| Python modules / LOC (persistence + services) | 26 / 2 230 | 26 / **≈ 2 200** (M1/M2/M3 delete code) | `wc -l` |
| Python panel / JS panel LOC | 185 / **368** | 185 / **2 files ≤ 200** | `wc -l`, `node --test` |
| Python functions | 199 | **≈ 196** (M3 branch, L2, L8) | `ast` walk |
| Max function LOC | 22 | 22 (unchanged — `build_manifest` is one wire dict) | `ast` walk |
| Max CC (workspace scope) | 10 (`safe_rel_path`) | **10** (untouched, pure path validation) | `radon cc -s` |
| CC ≥ 7 functions in scope | 14 | **≤ 10** (M1 `_finish` 8, M3 `save_report` 7→5, L2/L8) | `radon cc -s` |
| Max cognitive / nesting | within RULE 16 | unchanged | `tools/verify_quality.py` |
| `verify_quality` fails in workspace scope | 0 | **0** | `python tools/verify_quality.py` |
| Dead public symbols / vulture findings (feature + its tests) | 1 (`RESTORE_ADVICE`) / 4 | **0 / 0** | `vulture --min-confidence 80` |
| Uncovered lines in the workspace package | 69 | **≈ 55** (M3 `reports.py:26`; step 11/13 add covered paths) | `coverage report -m` |
| Coverage, workspace scope (`--branch`) | 93 % | **≥ 95 %** | `coverage run --branch --source=app` |
| Workspace pytest / JS tests | 154 / 18 | **≈ 176 / 18** | `pytest` / `node --test` |
| Full pytest suite | 3 008 pass · 6 skip · **3 fail (pre-existing)** | **3 008+ pass · 3 fail, no new failure** | `pytest -q` |
| Duplicated validator bodies (5 → ?) | 5 | **1 helper + 5 one-line call sites** | `pylint R0801` / review |
| `git` subprocess spawns per save | **2** | **1** | probe P2 |
| Reproduced defects P1–P14 | 9 confirmed (P12 green by design) | **0** | probes re-run on the final sha |

**Pre-existing failures at `97f4ed3`, out of scope and not made worse by any step:**

| Test | Why it fails here |
|---|---|
| `tests/test_quality_gate.py::test_40loc_js_function_fails` | `acorn` is not installed (`npm ci` not run in this sandbox) — the JS lane of the gate cannot start. |
| `tests/test_single_job_runner.py::test_handler_map_covers_all_types` | belongs to the I-79 / text-output line, not the Global Saving System. |
| `tests/test_ui_wiring.py::test_closing_the_window_drops_the_cdp_socket_inside_a_guard` | belongs to the app-close line (`2d35536` / `37a1cf1`), not the Global Saving System. |

---

## 10. Rules compliance for this plan (RULE 16 §16.7 self-review)

```text
[ ] No new function >30 physical LOC                         — steps add no function over 22
[ ] No new class >150 LOC / >15 methods                       — step 1 adds no class
[ ] No new function with >4 params                            — step 4 threads one dict, not params
[ ] radon CC ≤10, cognitive ≤15, nesting ≤4 on every new fn    — measured after every step
[ ] overall line coverage ≥80 % and not below baseline; branch ≥75 %  — step 0 pins 93 % first
[ ] every new function has a test that would fail if deleted   — §7 table
[ ] no new vulture findings, no new duplication groups        — L12 folded into step 0/6
[ ] quality-override only with a real constraint               — none added
[ ] no metric gaming (no foo_part1, no lambda dispatch)        — every extraction names a domain concept
[ ] RULE 18 ideals: functions 4–20, files 150–300, module 5–15  — step 14 closes the one file over 300
[ ] RULE 19 order respected (nesting → CC → cognitive → size)  — M3/L2/L8 are size last, after the decision is gone
[ ] SYSTEM_OF_RECORD.md + docs/README.md updated in the same change as the code
```
