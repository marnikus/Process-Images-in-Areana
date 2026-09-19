# Area B Round-3 Review — full B implementation vs doc specifications (2026-09-19)

Third-pass audit. Specs compared against:
`../2026-09-19-code-quality-implementation-plan/area-plans-prioritized.md` (Area B table),
`../2026-09-19-code-quality-implementation-plan/verification-checklist.md`,
`../2026-09-19-area-b-review-and-followups/plan.md` (B7–B12 specs + exit criteria),
`docs/current/AGENT_RULES.md` (RULE 8/16/17/18/21), and the two implementation records.

All numbers below re-measured fresh this round (pytest, node, gate absolute+ratchet,
coverage, vulture, jscpd, pre-push script end-to-end).

## 1. B1–B12 vs specifications — status

| Spec item | Status | Fresh evidence |
|---|---|---|
| B1–B6 (dead-code purge, RULE 21, vulture, json_store, dedup, baseline) | DELIVERED | re-verified in round 2; unchanged |
| B7 exit: owned modules ≥80/75 | **DELIVERED** | 12 owned modules re-measured: all ≥81.8 line / ≥83.3 branch (8 at 100/100) |
| B7 exit: coverage never below 43.09/33.76 | **DELIVERED** | 44.31 / 35.10 |
| B8 exit: whitelist hazard removed | **DELIVERED** | bare `a`/`args` gone; `*_shim_*` names only |
| B9 exit: no live selector literal outside site_adapter beyond frozen list | **DELIVERED** | source-scan test green; frozen allowlist in `tests/test_action_block_defaults.py` |
| B9 exit: JS `getDefaultBlocks()` mirror lock | **DELIVERED** | 23 tests green (caught real DOWNLOAD/SAVE drift, pinned) |
| B10 exit: output_probes internal clones 2→0, field sets unchanged | **DELIVERED** | jscpd re-run: 0 internal; key-set + source-shape locks green |
| B11 exit: no doc outside archive claims deleted modules current | **DELIVERED** | banners + index rows verified |
| B12 exit: pre-push script green end-to-end, no silent fallbacks | **DELIVERED** | `bash tools/pre_push_check.sh` exit 0; loud `GATE HONESTY` warning on no-merge-base |
| Round-2 findings F-1…F-7 | ALL CLOSED | per `../2026-09-19-area-b-review-and-followups/implementation-2026-09-19.md`; re-verified |

Round totals re-measured: pytest 533, node 115, coverage 44.31/35.10,
gate 128 (ratchet) / 130 (absolute incl. 2 coverage lanes), jscpd 42/454,
vulture @90 = 0.

## 2. New findings (this round)

**F-8 (P1) Gate tool dead code — partly introduced by B12.** The B12 refactor
made `main()` call `changed_app_files()`/`all_app_files()` directly and
orphaned `find_py_files()` (nothing references it). Also in the same file:
`import os` (unused — would be a @90 vulture finding if the gate scanned
tools/, which it does not), and legacy dead code: `TESTS_DIR` (assigned,
never read), `nesting_nodes` (assigned, never read — and its stale comment
misdocuments the nesting rule), `fp` loop variable (body uses only
`entries`), `val` unpack (only `reason` used). The standard vulture lane
(`vulture app tools/vulture_whitelist.py`) is blind to all of this because
tools/ source is not scanned.

**F-9 (P1, RULE 18) The gate tool violates the ideals it enforces.**
`tools/verify_quality.py`: `check_file` 215 LOC containing a NESTED `walk`
of 194 LOC; `main` 118 LOC. No function added this round exceeded 30 LOC,
but the tool that enforces that rule carries 3×–7× overloads itself.
Given the standing instruction to recheck RULE 18 fit, this is the top
improvement candidate. Safety net exists: the full `--json` output can be
byte-diffed before/after the split (deterministic), plus 6 subprocess
tests + 533 pytest.

**F-10 (P1, RULE 16) Pre-push gate has no node lane.** 115 node tests gate
the JS production code (`app/ui/web/js/**` — action-blocks panel, sash,
composer, output probes) but `pre_push_check.sh` never runs them. RULE 16
("gates on every production change") is not enforced for JS changes at
push time.

**F-11 (P2) Push-hook hygiene.** `.pytest_cache` is not in `.gitignore`
and the script's pytest runs lack `-p no:cacheprovider` — running the
pre-push hook dirties the worktree mid-push.

**F-12 (P2, RULE 17) Doc index gaps from the same day as the B11 sweep.**
`docs/README.md` has no index row for
`archive/2026-09-19-area-b-review-and-followups/` (created that round —
the sweep fixed two older docs but missed indexing the new folder itself).
SOR §9 still presents coverage as "<80% or below baseline" without the
mid-round ratchet vs final D4 distinction that §8 and the tool now carry.

**F-13 (P3, handover notes — not Area B gaps).** Coverage-inventory
orphan: `cdp_events` 83.3/58.3 (branch <75) is named in no area plan.
For the record (correctly other areas' scope, re-measured):
`output_wait` 11.7/5.6 → Area C6 / D4.2; `single_job_runner` 34.1/20.3 →
Area A2; `cdp_client` 9.2/0.0 → Area C/D4.2. No action in Area B.

## 3. Verdict

B1–B12: all spec items and exit criteria hold under fresh measurement.
Residual work is tooling-shape (F-8/F-9), gate completeness (F-10/F-11)
and doc alignment (F-12) — planned as B13–B15 in `plan.md`.
