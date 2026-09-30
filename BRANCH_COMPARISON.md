# Branch comparison — `arena/01a0ef64` vs `arena/01a0ef65`

**Repo:** `marnikus/Process-Images-in-Areana` · **Base:** `97f4ed3` (both branches) · **Measured:** 2026-09-30

Both branches are refactoring **the same code** off the same base commit — the global workspace
save/restore line and the I-79 "new chat as new tab" handover line. Each ran its own audit-first
TDD pass and wrote its own audit documents. Every number below was re-measured in this sandbox by
checking both branches out as worktrees and running the repo's own lanes (`pytest`, `npm run
test:js`, `tools/verify_quality.py`, `coverage run --branch`). The audit documents' own claims are
noted where they disagree with the measurement.

---

## 1. Headline

The two branches are **not competing implementations of the same refactor — they are largely
complementary, and they are not mergeable.**

They overlap on exactly **one** finding (the duplicated owner probe), which both fixed the same way.
Everything else each branch fixed, the other left broken — I verified this at source level and by
test presence. Merging them produces **16 conflicted files**.

**Verdict: B2 (`01a0ef65`) is the more efficient refactor overall; B1 (`01a0ef64`) is the broader
one and fixes one user-visible bug B2 misses.** The right move is B2 as the base and cherry-pick
B1's N1 fix — see §8.

---

## 2. Footprint and cost

| Metric | B1 `01a0ef64` | B2 `01a0ef65` |
|---|---:|---:|
| Commits | 19 | 11 |
| Files changed | 55 | 32 |
| Lines inserted | +2,842 | +1,583 |
| Lines deleted | −583 | −237 |
| **Total churn** | **3,425** | **1,820** |
| New modules created | 1 (`live/pass_hold.py`, 78 L) | 1 (`workspace/selection.py`, 81 L) |
| JS files split | yes — `workspace.js` → 4 files | no |
| Production LOC in `workspace/` | 1,160 → **1,345** (+185) | 1,160 → **1,304** (+144) |

B1 costs **~88 % more churn** for a similar amount of changed ground. B1's workspace pass is the
more invasive one: it touches every `providers/*.py`, `provider.py`, `save.py`, `apply.py`,
`restore.py`, `registry.py`, `reports.py`, `recover.py`, `meta.py`, `snapshot_index.py`, plus the
Qt panel and a 4-file JS split. B2 concentrates on `save.py`/`apply.py`/`restore.py`/`meta.py`/
`snapshot_index.py`/`integrity.py` and leaves the rest alone.

Notably, **B2 shrank `apply.py` (276 → 255)** while **B1 grew it (276 → 319)** — and B1's audit
records an explicit RULE 18.2 exception for `apply.py` being over 300 lines, accepted rather than
reduced.

---

## 3. Test lanes (re-measured, full suite)

| Metric | `main` | B1 | B2 |
|---|---:|---:|---:|
| Python tests passed | 3,212 | **3,213** | 3,044 |
| Python failures | 7 | 7 → 6¹ | 7 → 6¹ |
| JS tests passed | 479 | **495** | 481 |
| JS failures | 2 | 2 | 2 |
| New Python test functions | — | **+47** | +28 |
| New JS test cases | — | **+5** | +2 |
| Plain suite runtime | 194 s | 195 s | **183 s** |
| Suite runtime w/ coverage | — | 296 s | **269 s** |

¹ The 7 failures are **identical on `main`** and are environment-only (no PySide6/`libGL`, IPv4
connect message, an `acorn`-less JS gate). Both branches introduce **zero new failures** — verified
by diffing failing test *names* against `main`, not just counts.

B1 wins raw test volume (+47 py / +5 js) and is the only branch that added a jsdom test file. B2
is ~9 % faster to run because it carries 169 fewer tests.

**Area-suite detail (new-tab handover):** `main` 92 → **B1 260** → B2 101. B1's number is inflated
by a new 161-case `test_import_cycles.py` (one parametrized import per module) — a genuinely useful
guard, but it is breadth, not behavioural depth on the handover itself.

---

## 4. Quality gate (RULE 16 ratchet) — the sharpest divergence

`tools/quality_baseline.json` is stale, so `main` *itself* fails 38 repo-wide ratchet checks. To
isolate each branch's own damage I gated **`main`'s copy of each branch's exact changed file set**
and subtracted.

| | B1 | B2 |
|---|---:|---:|
| Pre-existing ratchet fails on that file set (measured on `main`) | 8 | 4 |
| Ratchet fails on the branch | 20 | 5 |
| **NEW ratchet fails introduced** | **12** | **1** |
| Repo-wide gate fails (both lanes) | 50 | 39 |

**B1's 12 new findings:**

| File | Finding |
|---|---|
| `live/tab_owner.py` | max_func_loc 13 → 15 |
| `workspace/apply.py` | max_func_loc 20 → **27** |
| `workspace/provider.py` | max_class_loc 42 → 48 |
| `workspace/provider.py` | max_nest 1 → 2 |
| `providers/preset_stores.py` | max_methods 5 → 6 |
| `workspace/restore.py` | max_func_loc 19 → 22 |
| `workspace/restore.py` | max_cc 7 → 8 |
| `workspace/restore.py` | max_params 3 → 4 |
| `workspace/save.py` | max_class_loc 7 → **22** |
| `workspace/save.py` | max_methods 0 → 2 |
| `workspace/save.py` | max_params 3 → 4 |
| `ui/panels/workspace.py` | max_class_loc 30 → 34 |

**B2's 1 new finding:** `workspace/snapshot_index.py` max_cc 4 → 5.

Both audit documents claim "gate: **0 fail**" on their touched files. That claim does not survive
re-running the command on the branch tip with the committed baseline — B1 shows 20, B2 shows 5.
B1's claim is the further off. (Both docs also argue the baseline is stale and deliberately not
re-recorded; that is defensible, but the *differential* above is still the honest measure of what
each refactor did to complexity.)

B1 did improve one thing incidentally: `reports.py` max_cc went 7 → 6.

---

## 5. Coverage (full suite, `--branch`, re-measured)

| Metric | B1 | B2 |
|---|---:|---:|
| Statements in refactored area | 1,533 | 1,656 |
| Missed | 37 | 46 |
| **Area coverage** | **97 %** | **97 %** |
| Repo-wide line coverage | 89 % | 89 % |
| Core new-tab modules (`new_tab`, `new_tab_open`, `new_tab_setting`, `browser_targets`, `page_popup`) | 100 % line / 100 % branch | 100 % line / 100 % branch |
| `live/reconcile.py` | 99 % | 99 % |
| New module coverage | `pass_hold.py` 97 % | `selection.py` 100 % |
| Weakest touched file | `ui/panels/workspace.py` 86 % | `ui/panels/workspace.py` 85 % |

A **tie**. Both hold the five core modules at 100 %/100 % and lift the touched area to 97 %.

One asymmetry: under the *focused* area suites alone, B1's new `pass_hold.py` sits at **83 %**
(4 of 30 statements missed) and only reaches 97 % once the full suite runs. B2's `selection.py` is
100 % from its own suite. B1's own audit claims "100 % line + branch coverage on all five modules"
— true for those five, but `pass_hold.py` is a sixth module it added and did not cover at that level
locally.

Dead code (`vulture --min-confidence 80`, `app/` + `tests/`): `main` 70 → B1 **69** → B2 71.
No regression either way.

---

## 6. What each branch actually covers

### Both branches — the one shared fix

| Finding | Fix |
|---|---|
| Duplicated owner probe: `new_tab._read_owner_from_client` re-implemented `live/tab_owner._read_owner` with a **lazy import inside a bare `except`**, so the profile-truth guard could silently degrade to a no-op | Promote `tab_owner.read_owner` to public; `new_tab` calls it; the private copy and its lazy imports are deleted |

B1 numbered this **N6** and framed it as a silent-verification-disappears hazard; B2 numbered it
**N1** and framed it as a RULE 4 one-home duplication. Same code change, same test
(`test_the_owner_probe_goes_through_the_shared_reader`). **No conflict in substance.**

### B1 only — fixes B2 leaves broken

| # | Defect | Severity | Evidence |
|---|---|---|---|
| **N1** | A Reparse queued **during** a new-tab handover is never released. `new_tab._hold_reconciler` takes `_auto_scan_running` for its whole duration and releases it in its own `finally` **without ever reading `_reparse_queued`** — the only reader is `reconcile_once`'s tail. The user is told "runs right after the current pass"; it doesn't run. | **Medium — user-visible promise broken** | Fixed by new leaf `app/services/live/pass_hold.py` owning `take`/`release`/`install_drain`, so *both* holders of the flag acquire and release in one place. Test: `test_a_reparse_queued_during_a_handover_runs_when_the_handover_ends`. |
| **N2** | `_close_old` returns a bool nobody reads, so a handover that leaves the old tab open still returns `True, "new chat ready…"` — contradicting the docstring's `(False, why) = nothing changed`. | Low — misleading contract | Return value becomes the reason appended to the success line. |
| **N3** | Default new-chat URL had two owners (`new_tab_setting.DEFAULT_URL` and `config_manager`'s seed). | Low — order-dependent default | `config_manager` imports the leaf's `DEFAULT_URL`. |
| **N7** | An import cycle **B1's own N1 fix introduced**: `cooldown_service → new_tab → live.reconcile → reconcile_rows → run_state → cooldown_service`. 22 test modules failed at collection. Caught only by the full suite — every focused suite passed. | **High — module unimportable** | Fixed by the `pass_hold.py` leaf (stdlib-only, pass injected). Pinned by new `tests/test_import_cycles.py`. |

N7 is the most instructive finding in either branch: **a lane that reports clean the tree did not
have, three rounds running.** B1's own audit names the pattern explicitly.

### B2 only — fixes B1 leaves broken

| # | Defect | Severity | Evidence |
|---|---|---|---|
| **N2** | `_check_owner_preserved` compared `new_owner == move.owner.lower()` — a **second normalization rule** beside `tab_alias.normalize_owner`. `_plan` stored the *raw* pool label. An alias label like `aka_1234` normalizes to `""` on the probe side but compares as `"aka_1234"` on the guard side → **false rollback of a proven profile**. `Owner@Example.com` → false pass. | **Medium — latent wrong answer** | `_plan` now stores `normalize_owner(page.owner)`; the guard compares equal strings. Test: `test_an_owner_label_that_is_not_an_email_never_rolls_back` (3 cases). **Reproduced on B1**: `normalize_owner('aka_1234')` → `''` ≠ `'aka_1234'.lower()` → `False`. |
| **N4** | `ws://{host}:{port}/devtools/page/{id}` was **formatted in `new_tab` and parsed in `browser_targets`** — the pair could drift. | Low | New `browser_targets.page_ws`, the exact inverse of `endpoint_of_ws`; `new_tab._page_ws` deleted. Round-trip test. |
| **N6** | `supervisor._next_ready` hand-rolled `f"{secs // 60:02d}:{secs % 60:02d}"`, re-implementing `core.cooldown.format_remaining`. A ≥1 h cooldown printed **`75:00` instead of `1:15:00`**. | Low–Med — display bug at the hour boundary | `_next_ready` calls `format_remaining`. Test: `test_next_ready_uses_the_one_countdown_formatter`. **Verified on B1**: `app/services/live/supervisor.py:141` still has the `// 60` form. |
| **N3** | The `"arena.ai"` pattern default had four homes (`_Move.pattern`, twice in `_get_pattern`, plus `config_manager` and `reconcile_rows`). | Low | Key + default live in the leaf that owns session defaults; `reconcile_rows` aliases them. |

B2 also hit and fixed an import cycle of its own during P3 (`new_tab → reconcile_rows → run_state →
cooldown_service`), which the focused lane hid and only `pytest tests/test_live_supervisor.py`
alone exposed — a smaller-scale echo of B1's N7.

### Explicitly *not* fixed by either

- `_Move`'s 13–15 mutable fields (both kept, both documented as correct for a private record).
- The two `FakeBrowser` test fixtures (both kept).
- Legacy `run_state.py`'s hand-rolled `MM:SS` (B2 lists it as legacy, out of range).
- The six `devtools/page/` string sites outside the feature.
- `_current_tab_id` read in 9 places (B2 documents it, changes nothing).

---

## 7. JS lane

| | `main` | B1 | B2 |
|---|---:|---:|---:|
| `panels/workspace.js` LOC | 368 | 56 (+3 new files) | 368 |
| Total workspace panel JS LOC | 368 | **426** | 368 |
| Files loaded by `index.html` | 1 | **4** | 1 |
| `files > 300 LOC` in `js/panels/` | 2 | **1** | 2 |

B1 is the only branch that touched the JS. Its split (bridge / flow / render) removes the last
>300-line file in `js/panels/` and is correctly wired into `index.html` — but it **adds 58 lines**
to do it.

**B1 also caused and then fixed a real regression here.** `test_job_cycle_setting.mjs` went
**12/12 → 11/12** when the panel split moved the RULE 24 refresh table into `flow.js` and the test
kept reading `workspace.js`. The canonical `npm run test:js` lane could not see it because the
script names its test files by hand and did not include `test_job_cycle_setting.mjs`. B1 caught it
with `node --test tests/js/*.mjs`, fixed the test, and added the file to `test:js`. It now passes
12/12 on both branches. Documented in B1's `docs/current/QUALITY_RECHECK.md`.

---

## 8. Mergeability — a hard blocker

Attempting to merge B2 into B1 produces **16 conflicted files**:

```
app/services/live/tab_owner.py          app/ui/panels/workspace.py
app/services/new_tab.py                 app/ui/web/js/panels/workspace.js
app/services/workspace/apply.py         docs/README.md
app/services/workspace/meta.py          docs/current/SYSTEM_OF_RECORD.md
app/services/workspace/restore.py       tests/test_new_tab_handover.py
app/services/workspace/save.py          docs/archive/…/audit.md (add/add)
app/services/workspace/snapshot_index.py  + 2 rename/rename conflicts
```

Both branches also independently renamed the same two design docs to *different* archive paths
(`2026-09-25-workspace-refactor-1/audit.md` vs
`2026-09-25-global-workspace-save/audit-1-structure.md`).

These are **competing refactors of the same files, not a stack.** Only one can land as-is.

---

## 9. Documentation

| | B1 | B2 |
|---|---|---|
| Audit docs written | `2026-09-30-new-tab-handover/audit.md` (318 L) + own `2026-09-29-workspace-refactor-3/audit.md` (401 L) + `QUALITY_RECHECK.md` addendum (112 L) | `2026-09-30-new-tab-handover-audit/audit.md` (242 L) + `refactored-files.md` (89 L) + own audit #3 (322 L) |
| System-of-record rows updated | I-68(a), I-79 | I-79, I-80 |
| Honest self-critique | **Names its own audit miss (N6) and its own introduced defect (N7)**; records three separate "a focused lane reported clean the tree did not have" incidents | Names its own import-cycle slip and the log-ordering bug P7 caused |
| Claim accuracy vs. re-measurement | "gate 0 fail" → actually 20; "100 % on all five modules" → true, but omits `pass_hold.py` at 83 % locally | "gate 0 fail" → actually 5; "0 functions > 20 LOC" → holds |

Both are unusually candid. B2's `refactored-files.md` is the single best artifact either branch
produced — a per-file, per-pass, total-and-code-line inventory that makes the refactor auditable at
a glance, including the files that *shrank*. B1's `QUALITY_RECHECK.md` is the better record of
**process failures** (the three lane-blindness incidents), which is arguably more valuable long-term.

---

## 10. Scorecard

| Dimension | Winner | Margin |
|---|---|---|
| **Efficiency (churn per unit of work)** | **B2** | decisive — 1,820 vs 3,425 lines |
| **Quality-gate hygiene** | **B2** | decisive — 1 vs 12 new ratchet findings |
| **Commit discipline / step granularity** | **B2** | 11 commits vs 19; B1's series needed a N7 repair pass |
| **Coverage** | **tie** | both 97 % area, 100 % on core modules |
| **Test volume** | **B1** | +47 py / +5 js vs +28 / +2 |
| **Breadth of refactor** | **B1** | JS split, providers, import-cycle guard for all 161 modules |
| **User-visible bugs fixed** | **B1** | queued-Reparse (medium) vs countdown display + owner-label (low–med each) |
| **Latent correctness bugs fixed** | **B2** | owner-label normalization, page_ws drift |
| **Mergeability** | neither | 16 conflicts |
| **Documentation** | **B2** (inventory) / **B1** (process lessons) | — |

---

## 11. Recommendation

**Take B2 (`arena/01a0ef65-process-images-in-areana`) as the base.** It is the more disciplined and
more efficient refactor: 47 % less churn, 12 fewer new gate findings, a smaller and more reversible
commit series, and it shrank the files it touched rather than growing them.

Then **cherry-pick B1's N1 + N7 pair** (`fc39aff` + `97593c1`, or the whole `pass_hold.py` leaf and
its test) on top. That is the one genuinely user-visible defect B2 leaves open — a manual Reparse
clicked during a handover is silently stranded — and it is self-contained in a stdlib-only leaf with
its own test, so it ports cleanly. Note that porting it re-creates the import cycle B1 hit in N7,
so land the leaf form, not the direct `live.reconcile` import.

Do **not** try to merge the two branches wholesale, and do not adopt B1's workspace pass: it grew
`apply.py` past the RULE 18.2 ideal and introduced a documented exception rather than a reduction,
while B2's equivalent pass shrank it.

If only one branch can ship and the queued-Reparse bug must wait, B2 is still the correct choice —
its own defects (a false rollback of a proven profile, a wrong countdown past an hour) are latent,
whereas B1's cost is 12 new complexity findings that a future integrator has to pay down.


---

# 12. Outcome — the recommendation was carried out

Executed on `arena/01a0f198-process-images-in-areana` (2026-09-30). B2 taken as the
base, B1's stranded-Reparse fix ported on top **in the leaf form**.

## What landed

| Commit | What |
|---|---|
| `06017e0` | **merge** `arena/01a0ef65` (audit #3 + #4) as the refactor base |
| `af37553` | `test(new-tab)` — the characterization fence (B1's step 1) |
| `38aa379` | `fix(new-tab)` — `live/pass_hold.py` leaf; the queued Reparse is no longer stranded |
| `e3e6871` | `docs(new-tab)` — SoR I-68(a) holder rule + measured QUALITY_RECHECK addendum |

**Port size: 7 files, +297 / −12** against the B2 base — about 9 % of B1's own
3,425-line churn, for the one behaviour change that mattered.

## Measured after the port

| Gate | Result |
|---|---|
| Import cycles (`test_import_cycles.py`) | **162 passed** — one more than B1's 161, because B2 adds `workspace/selection.py` |
| Focused (handover + cycles + reconcile + reparse) | **229 passed** (was 101) |
| Full Python suite | **3 210 passed · 5 skipped · 6 failed** — the same six environment-only failures as the untouched base; no new failure |
| Canonical JS lane | **481 pass · 2 fail** — the same two `live_debug` subtests as `main` |
| New-tab jsdom | **12 / 12** |
| Repo-wide gate (both lanes) | **39 fails — identical to the B2 base** (B1 alone was 50). The port adds **0** new findings |
| Coverage of the ported area | `pass_hold.py` 97 % line / 100 % branch · `new_tab.py` 100 % / 100 % · `reconcile.py` 99 % |
| Vulture | 69 before, 69 after |

The one gate fail touching the port (`reconcile.py` `max_cc` 7→8) **reproduces
identically on the B2 base**, which never touched that file — stale-baseline noise,
not this change.

## The RED was re-verified, not assumed

Reverting only the one-line release and re-running:

```
>       assert ran == ["pass"], "the queued Reparse must run the moment the handover ends"
E       assert [] == ['pass']
1 failed, 47 deselected
```

Restored, it passes. The test fails for the right reason and only that reason.

## Conflict resolution

Two conflicts, both resolved by keeping both sides:

* `tests/test_new_tab_handover.py` — B2's owner-read tests and B1's characterization
  tests occupied the same region; both blocks are kept.
* `new_tab.py` — only the release path was ported. B2 had already deleted the
  duplicate owner probe and rewritten the module (`HandoverCtx` Protocol,
  `normalize_owner` at the boundary, `browser_targets.page_ws`), so B2's direct
  `from app.services.live.tab_owner import read_owner` import style is kept instead of
  B1's `from app.services.live import … tab_owner`.

B1's duplicate audit document (`archive/2026-09-30-new-tab-handover/audit.md`) was
**dropped rather than merged**, to keep one audit per range; B2's
`2026-09-30-new-tab-handover-audit/` already covers it.

## What was deliberately left out

B1's workspace pass (`providers/` split, 4-file JS panel split) and its N2/N3 fixes.
The JS split in particular is the single largest cost in B1's churn (+58 lines) for a
file-size win the repo gate does not require, and B1's workspace pass grew `apply.py`
past the 300-line ideal where the base branch shrank it.

## Residual risk

The stranded-Reparse fix is now covered, but the **inverse gap is still open**: this
branch does not carry B2's countdown-formatter or page-socket fixes *away* — it carries
them, because B2 is the base. So the remaining hole is the set of defects **neither**
branch fixed (the `_Move` field count, the two `FakeBrowser` fixtures, legacy
`run_state.py`'s `MM:SS`), all of which both audits explicitly checked and kept.
