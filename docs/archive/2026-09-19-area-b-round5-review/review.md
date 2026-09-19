# Area B Round-5 Review — full B implementation vs doc specifications (2026-09-19)

Fifth-pass audit. Specs compared against:
`../2026-09-19-code-quality-implementation-plan/area-plans-prioritized.md` (Area B table + Round 0/D exit criteria),
`../2026-09-19-code-quality-implementation-plan/verification-checklist.md`,
the B7–B12, B13–B15 and B16–B18 plans, `docs/current/AGENT_RULES.md`
(RULE 8/16/17/18/21), and all four implementation records.

Fresh battery this round: pytest 539, node 115, gate absolute 130 /
ratchet 128, coverage 44.31/35.10, vulture @90 = 0, jscpd 42/454,
`pre_push_check.sh` exit 0 with the changed-file lane engaged.

## 1. Full B implementation (B1–B18) vs specifications

| Spec item | Status | Fresh evidence |
|---|---|---|
| B1–B6 purge / RULE 21 / vulture / json_store / dedup / baseline | DELIVERED | unchanged since round 2 |
| B7 owned modules ≥80/75 | DELIVERED | re-measured green |
| B8 whitelist hazard | DELIVERED | @90 = 0 |
| B9 selector single-source + JS mirror locks | DELIVERED | 23 lock tests green |
| B10 output_probes internal clones 2→0 | DELIVERED | 0 clones touching B modules |
| B11 stale docs | DELIVERED | banners verified |
| B12 gate honesty / ratchet / script green | DELIVERED | loud warning re-observed |
| B13 gate-tool RULE 18 fit + dead-code purge | DELIVERED | all functions ≤30 LOC |
| B14 pre-push node lane + hygiene | DELIVERED | node lane green |
| B15 docs alignment | DELIVERED | folders indexed, SOR §9 note |
| B16 ratchet floor tamper-proof + honest degradation | DELIVERED | refuse-lower test green |
| B17 changed-file lane engages + robust tests | DELIVERED | 6-file subset gated vs pushed tip |

## 2. New findings (this round)

Focus: the gate's integrity as a *system* against the master plan's own
exit criteria — plus the standard fresh battery.

**F-18 (P1, gate hole — master plan R0.3/D6 exit criterion violated).
`--allow-legacy` downgrades without an increase-check, so growth of a
legacy hotspot passes the pre-push gate.** Proven live: a temp commit
adding a brand-new **36-LOC function to `bridge.py`** (baseline
`max_func_loc` 1209) was gated by the exact pre-push lane
(`--changed --base origin/<branch> --allow-legacy --coverage-ratchet`) —
result: bridge breaches 64→**69 (the new function's loc/cc/cognitive
breaches all present)**, every one downgraded to `[LEGACY]` warn,
**0 fails, gate exit 0**. The master plan's R0.3 "Done when: Adding
31-LOC func to `bridge.py` fails" and D6's identical negative test are
therefore violated by the current tool. B12's F-6 fix removed the silent
*fallback* dishonesty; this is the sibling *legacy-downgrade*
dishonesty. Fix (minimal, uses only existing baseline schema fields):
`downgrade_legacy` keeps `fail=True` for `loc`/`class-loc` breaches whose
value exceeds the file's baseline `max_func_loc`/`max_class_loc`
(§16.5 "legacy must not grow"); cc/cognitive/params/methods/nesting have
no baseline maxima and stay downgraded (full per-metric ratchet remains
R0.3/D6 deferred scope).

**F-19 (P2, RULE 17 docs).** `SYSTEM_OF_RECORD.md` §8 has no row for
`tests/test_verify_quality_tool.py` (12 tests characterizing the gate's
behaviour lanes) — the B11 indexing convention was not applied to the
test suite added in B12 and extended in B16/B17.

**F-20 (P3, handover note — no Area B action).**
`docs/current/AGENT_RULES.md` RULE 16 still describes coverage purely as
absolute 80/75 + never-decrease, with no mention of the tool's mid-round
`--coverage-ratchet` mode (documented in SOR §9 and the tool docstring).
The rules doc is cross-area; flagging for the Round 0/D7 owner rather
than editing it unilaterally.

Non-finding, recorded for honesty: vulture @60 run on B-owned module
*subsets* produces false positives (store methods, probe accessors) —
cross-module consumers live outside the subset. The gating lane remains
the whole-app `vulture app tools/vulture_whitelist.py --min-confidence
90` = 0 findings.

## 3. Verdict

B1–B18: all spec items hold under fresh measurement. One P1 gate hole
(F-18) with a proven exploit, one doc gap (F-19), one handover note
(F-20) — planned as B19–B20 in `plan.md`.
