# Area B Round-3 Follow-up Plan — B13–B15 (2026-09-19)

Derived from `review.md` (same directory). Scope discipline unchanged:
Area-B lane only (tooling, own modules, docs). Explicitly NOT here:
bridge/undo cluster (A5/A7), cdp_client surface (C2), preset_store split
(C6), output_wait (C6/D4.2), single_job_runner (A2), absolute 80/75 (D4),
cdp_events coverage (handover note only — F-13).

| Step | Finding | Deliverable | Priority | Exit criteria |
|---|---|---|---|---|
| B13 | F-8 + F-9 | `tools/verify_quality.py` RULE 18 fit + dead-code purge. Characterization FIRST: full `--json` gate output snapshotted and byte-diffed across the refactor. Remove dead code (`find_py_files`, `import os`, `TESTS_DIR`, `nesting_nodes`, `fp`/`val` leftovers). Split `check_file` (215 LOC, nested 194-LOC `walk`) into named per-metric checkers and `main` (118) into parse/legacy/report helpers — every function ≤30 LOC, real responsibility names, no `foo_part1`. CLI flags, exit codes and JSON schema unchanged | P1 | gate `--json` output byte-identical pre/post; every function in the file ≤30 LOC; 6 tool subprocess tests green; pytest 533 + node 115 green; vulture @90 = 0; @60 on tools/ shows the F-8 items gone |
| B14 | F-10 + F-11 | `pre_push_check.sh` gains the node lane (`npm run test:js`, LOUD graceful skip when npm/node_modules unavailable — same honesty principle as the F-6 warning, never a silent pass); pytest lanes use `-p no:cacheprovider`; `.pytest_cache` added to `.gitignore`; `bash -n` syntax check added as a pytest test | P1 | `bash tools/pre_push_check.sh` exit 0 end-to-end INCLUDING the node lane; worktree stays clean after a run |
| B15 | F-12 | Docs: `docs/README.md` index rows for `archive/2026-09-19-area-b-review-and-followups/` and this folder; SOR §9 one-line clarification of mid-round ratchet vs final D4 absolute | P2 | both folders indexed; §9 consistent with §8 and the tool |

Order: B13 → B14 → B15 (code first, docs last, mirroring the round-2
sequencing rationale).

Per-step gates (RULE 16, unchanged): pytest + node green, global gate
fails never above 128 (ratchet mode), coverage never below 44.31/35.10,
vulture @90 = 0, no §16.5 legacy hotspot growth, anti-gaming §16.2
respected (no `foo_part1` splits — B13's checkers are split by METRIC,
each owning one rule). Baseline `quality_baseline.json` per-file keys
untouched; the `coverage` key may only move UP (ratchet) and only at
round end.
