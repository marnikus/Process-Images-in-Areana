# Every file this branch refactored, with its line counts (2026-09-30)

Companion inventory for audit #3 (`docs/archive/2026-09-29-workspace-refactor-3/audit.md`, I-81) and audit #4
(`audit.md` in this folder, I-79 / I-80). Counts are taken from the branch tip with `git diff --numstat` for the
change and `wc -l` + a comment/blank filter for the file itself, so a refactor that *shrinks* a file (the point of
both passes) shows up as a small `+`/`−` pair. `code` = non-blank, non-comment lines (docstrings count as code).

Passes: **#3** = `97f4ed3..01825c5`, **#4** = `4b249e0..HEAD`.

### Audit #3 — workspace save/restore (production)

| File | pass | total | code | + | − |
|---|---|---:|---:|---:|---:|
| `app/persistence/workspace/integrity.py` | #3 | 76 | 55 | +12 | −0 |
| `app/services/workspace/apply.py` | #3 | 255 | 209 | +35 | −56 |
| `app/services/workspace/gates.py` | #3 | 63 | 51 | +4 | −5 |
| `app/services/workspace/meta.py` | #3 | 85 | 62 | +7 | −1 |
| `app/services/workspace/restore.py` | #3 | 95 | 79 | +3 | −9 |
| `app/services/workspace/save.py` | #3 | 274 | 217 | +74 | −35 |
| `app/services/workspace/selection.py` | #3 | 81 | 64 | +81 | −0 |
| `app/services/workspace/snapshot_index.py` | #3 | 115 | 81 | +62 | −16 |
| `app/ui/panels/workspace.py` | #3 | 201 | 157 | +30 | −14 |
| `app/ui/web/js/panels/workspace.js` | #3 | 368 | 306 | +8 | −8 |
| **total (10 files)** | | **1613** | **1281** | **+316** | **−144** |

### Audit #4 — new-tab handover + cooldown seams (production)

| File | pass | total | code | + | − |
|---|---|---:|---:|---:|---:|
| `app/browser/cdp/browser_targets.py` | #4 | 173 | 140 | +5 | −0 |
| `app/persistence/config_manager.py` | #4 | 162 | 134 | +4 | −1 |
| `app/services/live/reconcile_rows.py` | #4 | 126 | 100 | +5 | −2 |
| `app/services/live/supervisor.py` | #4 | 228 | 176 | +7 | −3 |
| `app/services/live/tab_owner.py` | #4 | 70 | 54 | +8 | −4 |
| `app/services/new_tab.py` | #4 | 324 | 267 | +69 | −43 |
| **total (6 files)** | | **1083** | **871** | **+98** | **−53** |

### Tests (both passes)

| File | pass | total | code | + | − |
|---|---|---:|---:|---:|---:|
| `tests/js/test_workspace_panel.mjs` | #3 | 358 | 312 | +27 | −1 |
| `tests/test_workspace_failure_edges.py` | #3 | 310 | 234 | +1 | −1 |
| `tests/test_workspace_panel.py` | #3 | 117 | 84 | +35 | −0 |
| `tests/test_workspace_reply_truth.py` | #3 | 137 | 100 | +137 | −0 |
| `tests/test_workspace_restore.py` | #3 | 447 | 344 | +39 | −6 |
| `tests/test_workspace_save.py` | #3 | 267 | 199 | +129 | −0 |
| `tests/test_browser_targets.py` | #4 | 260 | 196 | +7 | −0 |
| `tests/test_live_supervisor.py` | #4 | 264 | 214 | +14 | −0 |
| `tests/test_new_tab_handover.py` | #4 | 719 | 548 | +113 | −27 |
| **total (9 files)** | | **2879** | **2231** | **+502** | **−35** |

### Docs (both passes; the two moved design docs are renames, counted at their new name)

| File | pass | total | code | + | − |
|---|---|---:|---:|---:|---:|
| `docs/README.md` | #3+#4 | 117 | 95 | +6 | −3 |
| `docs/archive/2026-09-29-workspace-refactor-3/audit.md` | #3 | 322 | 275 | +322 | −0 |
| `docs/current/SYSTEM_OF_RECORD.md` | #3+#4 | 433 | 372 | +10 | −4 |
| `docs/archive/2026-09-30-new-tab-handover-audit/audit.md` | #4 | 236 | 196 | +56 | −1 |
| **total (4 files)** | | **1108** | **938** | **+394** | **−8** |

## What the two passes cost and saved

| | audit #3 | audit #4 | branch vs `main` |
|---|---:|---:|---:|
| files | 10 prod + 6 tests + 4 docs | 6 prod + 3 tests + 3 docs | 31 |
| lines added | +1017 | +293 | +1488 |
| lines removed | −155 | −85 | −237 |
| code lines now in the touched production files | 1281 | 871 | 2152 |

Two further paths changed by **rename only**, verbatim moves into the archive (RULE 17) — not refactors, so they
carry no line delta: `docs/current/GLOBAL_WORKSPACE_SAVE_DESIGN.md` →
`docs/archive/2026-09-25-global-workspace-save/design.md` (544 lines) and `docs/current/WORKSPACE_REFACTOR_AUDIT.md` →
`docs/archive/2026-09-25-global-workspace-save/audit-1-structure.md` (150 lines).

Files that shrank most (the refactor's purpose): `workspace/apply.py` −56 net, `new_tab.py` −43 net after its
splits, `restore.py` −9, `snapshot_index.py` +62/−16 (the new live-read rule), `save.py` +74/−35 (one response
builder instead of five). `new_tab.py`'s suite grew +113/−27 because every finding was reproduced before it was
fixed.
## The commits that did it

| Pass | Commits |
|---|---|
| #3 | `aa198d8` (R0, the defect-pinning tests) → `740c920` (R1–R8c) → `01825c5` (R9 docs) |
| #4 | `4b249e0` (audit + design, doc first) → `ca43184` (P1–P3) → `9df026d` (P4–P5 + the import-cycle fix) → `3944d3b` (P6) → `73893eb` (P7) → `ff16c69`, `7351626` (P8 docs) |

Both passes followed the same shape: the audit/design document first, then one commit per step with the RED test in
the same commit, and the docs (SYSTEM_OF_RECORD + README + the audit's own execution log and after-values) last.
