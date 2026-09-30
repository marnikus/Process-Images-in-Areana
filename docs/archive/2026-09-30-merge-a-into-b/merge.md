# Merge: `arena/01a0ef64` (A) into `arena/01a0ef65` (B) — 2026-09-30

Both branches took the same two-part assignment — **audit #3 + TDD refactor of the
Global Save/Restore workspace feature** and **audit + refactor of the I-79
new-chat-as-new-tab handover chain** — and both forked from `97f4ed3` (main HEAD).
This is the record of how they were combined, kept verbatim (RULE 17).

* Branch A = `arena/01a0ef64-process-images-in-areana` (19 commits, 55 files, +2842/−583)
* Branch B = `arena/01a0ef65-process-images-in-areana` (11 commits, 32 files, +1583/−237)
* Base = `97f4ed3`

## 1. Why B is the base

An independent comparison of the two branches scored **B 8.13 / 10 vs A 7.28 / 10**
and, more importantly, verified **8 fixes with 0 regressions for B** against
**7 fixes with 1 regression for A**, from 40 % less new production code
(net +217 prod LOC vs +367). B is pyflakes-clean with a warning-free suite; A
ships a crash on a production path (§3).

So B was merged whole and A's surviving fixes were ported on top of it, one
concern per commit, red-first. Nothing in B was rewritten to make room.

## 2. What was ported from A, and what each one cost

| Item | Where it landed | Verified |
|---|---|---|
| **H1** — a second save in the same second gets its own `-02` folder | `fsio.unique_dir` (new), `save._run_context`, `recover._recovery_dir` (dedup: it carried the identical loop inline) | red → green |
| **H4** — only a failed **required** domain refuses a save; a non-required one degrades to `partial` and is marked `excluded` | `save._blocking` (new), `save._causes` (new), `save._abort_result` | red → green |
| **H5** — the preview runs the restore's own gates, so `ok` means ok | `restore.preview_restore`, `_gate_note` / `_gate_loaded` (new) | red → green |
| **N1** — a Reparse queued during a new-tab handover runs when the handover ends | `live/pass_hold.py` (new, 81 lines), `live/reconcile.py`, `services/new_tab.py` | red → green |
| **N7** — every services/browser module must import on its own | `tests/test_import_cycles.py` (162 modules) | non-vacuous, see §4 |

Net production cost on top of B: **+214 / −38 lines** across 8 files.

### Two tests were flipped, not deleted

H4 changes a user-visible contract, so the tests that pinned the old one were
renamed and re-aimed rather than dropped:

* `test_corrupt_live_file_refuses_the_save` → `test_corrupt_live_file_is_never_
  saved_as_empty` — a corrupt `job_history` / `captcha_stats` / `cooldowns` live
  file now publishes `partial` with the domain excluded, instead of refusing.
* `test_aborted_save_logs_its_cause` now drives a **required** domain
  (`arena_state`), which is the path that still aborts.
* `test_partial_snapshot_requires_explicit_confirmation` split into
  `test_a_non_required_domain_failure_needs_no_confirmation` (RED) and
  `test_a_required_domain_failure_still_needs_explicit_confirmation` (green —
  the preserved behaviour).

## 3. A's N1 fix was ported with its bug corrected

A's headline new-tab fix **crashes in production while its own tests pass**. In
A, `reconcile.py` imports `install_drain(bridge, run_pass)` from the new
`pass_hold` leaf and then defines its own `install_drain(bridge, deps)` at
module level — pyflakes F811. `start_reconciler` passes a **lambda** meant for
the first signature; Python binds it to the second, so the drained pass runs
with a lambda where a `LiveDeps` was expected and dies with
`AttributeError: 'function' object has no attribute 'log'` on the background
loop. The queued flag is cleared first, so the Reparse is **lost** — worse than
the delay it replaced.

A's test missed it because it called `reconcile.install_drain(w.bridge, deps)`
directly, with the arguments the *local* function wanted, under a comment
claiming it was "exactly what `start_reconciler` does".

Ported here:

* one `install_drain` — the imported one. No module-level redefinition exists,
  and `pyflakes` is clean on every changed file.
* both tests go through the real `start_reconciler`, and the drained pass talks
  to its deps (`p.deps.log`) the way the real `_pass` does on its first step, so
  a wrong-deps drain cannot pass.
* the flag is acquired through `pass_hold.take` in **both** holders. A left
  `_hold_reconciler` writing `_auto_scan_running` directly, which contradicted
  the leaf's own "both acquire here" docstring.

## 4. Verification

| Lane | base `97f4ed3` | B | this merge |
|---|---|---|---|
| Full pytest (`-n 4`) | 3008 pass / 3 fail | 3046 pass / 3 fail | **3219 pass / 2 fail** |
| JS lane (`npm run test:js`) | 479 / 485 | 481 / 487 | **481 / 487** |
| pyflakes on changed files | clean | clean | **clean** |
| Warnings in the suite | 6 | 6 | **6** (the same 6) |

The 2 remaining pytest failures (`test_single_job_runner`,
`test_ui_wiring`) and the 2 JS failures (`live_debug`) fail identically on
base — they are pre-existing, not carried in by either branch. The third base
failure (`test_quality_gate::test_40loc_js_function_fails`) is the missing
`node_modules/acorn` the comparison report called environmental: it passes once
dependencies are installed.

The import-cycle guard was checked for vacuity: re-adding
`from app.services.live import reconcile` to `new_tab.py` fails it with the
original `ImportError: cannot import name 'ensure_pool_page' from partially
initialized module 'app.services.cooldown_service'`. The N1 tests were checked
the same way: reproducing A's shadowing fails both with
`AttributeError: 'function' object has no attribute 'log'`.

New code coverage: `live/pass_hold.py` **100 %** (line and branch) from
`tests/test_new_tab_handover.py`.

## 5. Deliberately not ported

| A item | Why not |
|---|---|
| **H2 / H3 / M8 / M5** | B fixed the same four defects with its own design. B keeps the UI notes reply-only (`refresh`) where A writes them to disk; both are defensible and A's version would have reopened B's R6/N3 decision. |
| **N2** (the handover's success line says when the old tab would not close) | Real, small, and unfixed by B — but it is a behaviour change in the owner-visible log line, and the audit that asked for it is A's. Left for its own change with its own red test. |
| **N5** (`_log` swallow docstring), **N3** (default URL comment + guard test), **L3–L10**, **M1/M4/M7**, the provider-table consolidation, the `meta.inclusion_policy` move | Structural work over files B restructured differently (B's `selection.py`, B's provider imports). Porting them means re-doing A's workspace pass against B's layout for no new verified behaviour. |
| **The JS panel split** (`workspace.js` 368 → `bridge.js` / `render.js` / `flow.js` + a 56-line mount) | The report lists it as optional and independent. It also changes `index.html` load order, and B touched the same 368-line file — the split has to be re-derived from B's version, which is a separate reviewable change. |
| **A's characterization suite** (`tests/test_workspace_characterization.py`, 474 lines) | Its H1/H4/H5 members are ported into the topical files (`test_workspace_save.py`, `test_workspace_restore.py`). The rest assert A's own structure (the removed `published` key, `meta.inclusion_policy`), which is not true here. |
| **A's `test_the_success_line_says_so_when_the_old_tab_would_not_close`** | Not imported, so its never-awaited `close_that_lies` coroutine (the report's step 7) never runs here. The suite's warning count is unchanged. |

## 6. Result

* Base B: 8 verified fixes, 0 regressions.
* Plus A's H1, H4, H5 and a **working** N1: 12 of the 12 defects the comparison
  probed are now fixed, and A's one regression is not carried in.
* The two open items the report listed for B — H1, H4, H5 — are closed; N1 is
  closed too. Nothing that either audit found is left unaddressed except the
  items in §5.

SoR rows updated in the same change: **I-81** (workspace: H1 / H4 / H5) and
**I-79** (the pass flag has one owner).
