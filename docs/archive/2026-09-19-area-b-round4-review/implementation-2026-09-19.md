# Area B Round-4 Implementation Record — B16–B18 (2026-09-19)

Execution of `plan.md` (same directory), order B16 → B17 → B18.
Per-step gates (RULE 16): pytest + node green, ratchet gate ≤128 fails,
coverage ≥44.31/35.10, vulture @90 = 0. No production `app/` file was
touched this round (verified: `git diff --name-only 85fc63f..HEAD` lists
only docs/, tools/, tests/) — §16.5 hotspots unchanged by construction.

## Per-step outcomes

| Step | Commit | Deliverable | Outcome |
|---|---|---|---|
| B16 gate integrity (F-14, F-17a) | `0df83a4` | ratchet floor tamper-proof + honest degradation | `--update-coverage-baseline` now REFUSES to lower the stored floor (proven possible in review: 44.31/35.10 → 20.0/10.0 silently). Equal/higher accepted. `--coverage-ratchet` with a missing/unreadable baseline `coverage` key appends an explicit `ratchet-unavailable` WARN lane (absolute D4 lanes still fail) instead of silently degrading. Byte-identity of the three normal modes preserved (`e371764d` / `5a91b6db` / `4d5baeca`). +4 subprocess tests (refuse-lower with baseline-untouched check, missing-key warn, missing coverage.json, corrupt coverage.json) — 12 total |
| B17 changed-file lane + test robustness (F-15, F-16) | `3b08e08` | pre-push gates exactly what is pushed | `resolve_base()`: env `VERIFY_QUALITY_BASE` → `origin/<current-branch>` → `origin/main` (loud). Verified live both ways: with unpushed app changes the gate checked ONLY those 6 files (**first real changed-file run in this repo**); with no app files in the delta it warns `lists no gated app files` and conservatively gates all 76 — exit 0 either way, never silent. Tests: `GOOD_BASE` derived at runtime (most recent ancestor whose diff gates an app file — no hardcoded hashes, loud skipif if none), magic `50`s replaced by `GATED_ALL` from the tool's own `all_app_files()`; suite 7.7s → 2.6s |
| B18 record + RULE 18 fix | this commit | end-recheck + docs | End-recheck caught `main` at 33 LOC (B16 warn block) → folded into `collect_breaches` (a coverage lane) → every function ≤30 again, byte-identity still holds. This record + `docs/README.md` index row |

## RULE 18 / RULE 16 end-recheck (user-instructed)

- **RULE 18**: every function in every touched file ≤30 LOC
  (`tools/verify_quality.py` largest = 26 after the fix; test file clean;
  `resolve_base` in the shell script is 11 lines).
- **RULE 16**: pytest 539 (+4), node 115, ratchet gate 128 fails
  (unchanged), coverage 44.31/35.10 (at the ratchet floor), vulture @90 = 0,
  normal-mode gate outputs byte-identical across the whole round
  (`e371764d` / `5a91b6db` / `4d5baeca`), `bash tools/pre_push_check.sh`
  exit 0 end-to-end with the changed-file lane engaged.
- **Anti-gaming §16.2**: the refuse-lower guard is itself the anti-gaming
  measure for the coverage lane; no size/param gaming introduced (all new
  functions small and single-purpose).

## Findings resolution (round 4)

- **F-14** closed: floor cannot be lowered via the flag (negative test).
- **F-15** closed: changed-file lane engages against the unpushed delta;
  honest conservative fallback when the delta has no gated files.
- **F-16** closed: no hardcoded hashes, no magic file counts.
- **F-17** closed: ratchet-unavailable warn lane + all four coverage
  error lanes now under subprocess test (the only previously untested
  gate paths).

## Verification commands (unchanged)

`bash tools/pre_push_check.sh` — exit 0. `python tools/verify_quality.py
--json --coverage-ratchet` — CI lane. All B1–B15 locks re-verified green
this round (539 pytest incl. 23 selector locks + 12 tool tests, 115 node,
jscpd 42/454 with 0 clones touching B-owned modules, 12 owned modules
≥80/75).
