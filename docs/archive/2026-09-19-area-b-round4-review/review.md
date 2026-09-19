# Area B Round-4 Review — full B implementation vs doc specifications (2026-09-19)

Fourth-pass audit. Specs compared against:
`../2026-09-19-code-quality-implementation-plan/area-plans-prioritized.md` (Area B table),
`../2026-09-19-code-quality-implementation-plan/verification-checklist.md`,
`../2026-09-19-area-b-review-and-followups/plan.md` (B7–B12),
`../2026-09-19-area-b-round3-review/plan.md` (B13–B15),
`docs/current/AGENT_RULES.md` (RULE 8/16/17/18/21), and all three implementation records.

All numbers re-measured fresh this round: pytest 535, node 115, gate 128
(ratchet) / 130 (absolute), coverage 44.31/35.10, vulture @90 = 0,
vulture @60 on the gate tool = 0, jscpd 42/454, all 12 owned modules
≥80/75, 0 jscpd clones touching B-owned modules, `pre_push_check.sh`
exit 0 end-to-end.

## 1. Full B implementation (B1–B15) vs specifications

| Spec item | Status | Fresh evidence |
|---|---|---|
| B1–B6 dead-code purge / RULE 21 / vulture / json_store / dedup / baseline | DELIVERED | re-verified rounds 2–3; unchanged since |
| B7 owned modules ≥80/75 | DELIVERED | all 12 re-measured green |
| B8 whitelist hazard | DELIVERED | `*_shim_*` names; @90 = 0 |
| B9 selector single-source + locks | DELIVERED | 23 lock tests in the 535; frozen allowlist intact |
| B10 output_probes internal clones 2→0 | DELIVERED | jscpd re-run: 0 clones touching B-owned modules |
| B11 no stale doc claims deleted modules current | DELIVERED | banners + index rows verified |
| B12 gate honesty (no silent fallback, ratchet, script green) | DELIVERED | loud `GATE HONESTY` warning re-observed; exit 0 |
| B13 gate-tool RULE 18 fit + dead-code purge | DELIVERED | all functions ≤30 LOC (largest 26); self-check = zero breaches; vulture @60 = 0 |
| B14 pre-push node lane + hygiene | DELIVERED | node lane ran in this round's battery; no `.pytest_cache` |
| B15 docs alignment | DELIVERED | folders indexed; SOR §9 ratchet note present |

## 2. New findings (this round)

Focus of the fresh-eyes pass: the newest, least-reviewed code — B13–B15
(the gate tool, the pre-push script, their tests) — plus the gate's
integrity properties as a system.

**F-14 (P1, gate integrity) The ratchet floor can be lowered silently by
its own maintenance flag.** Proven live:
`verify_quality.py --update-coverage-baseline --coverage-file <20% file>`
overwrote the baseline `coverage` key from 44.31/35.10 to **20.0/10.0**
without complaint. The "coverage must never decrease" lane (RULE 16) is
therefore enforceable only by reviewer vigilance on the baseline diff.
Fix: the flag must refuse to lower either metric (clear error; raising or
keeping equal is fine) + negative test.

**F-15 (P1) The pre-push changed-file lane never engages in this repo.**
`pre_push_check.sh` defaults `--base origin/main`, which shares no
ancestry with arena branches → every run takes the loud fallback and gates
ALL 76 files, every breach LEGACY-downgraded. The changed-file intent of
the lane is never realised. Proven: `origin/<current-branch>` has a
merge-base with HEAD and yields a real subset (32 changed files → **6
gated app files**, `changed_fallback: None`) — exactly the unpushed delta
a pre-push hook should gate. Fix: base resolution order env
`VERIFY_QUALITY_BASE` → `origin/<current-branch>` (when usable) →
`origin/main` (loud warning, as today).

**F-16 (P2, test robustness — RULE 8 longevity).**
`tests/test_verify_quality_tool.py` hardcodes `GOOD_BASE = "8529d6b"`
(breaks if history is ever rewritten) and asserts `files_checked < 50`
(flips red for the wrong reason once Area A legitimately touches ≥50
files vs that base). The fallback test's `> 50` is likewise a magic
number. Fix: derive a usable base dynamically (most recent ancestor whose
diff contains app files) and compare against the real all-file count.

**F-17 (P2, characterization gaps in the gate's error lanes).**
(a) `--coverage-ratchet` with a baseline that lacks the `coverage` key
silently degrades to absolute mode (fails 80/75 with no explanation that
the ratchet floor was unavailable). (b) The missing-`coverage.json` and
parse-error lanes of `check_coverage` (rewritten in B12/B13) have no
subprocess test at all — the only untested behaviour paths in the gate.

## 3. Verdict

B1–B15: all spec items and exit criteria hold under fresh measurement.
The residual work is gate *integrity* (F-14, F-15), test longevity
(F-16) and error-lane characterization (F-17) — planned as B16–B18 in
`plan.md`. No finding touches production `app/` code; Area-B runtime
surface is stable.
