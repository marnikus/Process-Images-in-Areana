# Area B Round-5 Implementation Record — B19–B20 (2026-09-19)

Execution of `plan.md` (same directory, including the in-flight
amendment), order B19 → B20. Per-step gates (RULE 16): pytest + node
green, ratchet gate ≤128 fails, coverage ≥44.31/35.10, vulture @90 = 0.
No production `app/` change persisted (the F-18 proof commits were
created and reset within the step; final tree contains none).

## Per-step outcomes

| Step | Commit | Deliverable | Outcome |
|---|---|---|---|
| B19 per-symbol legacy ratchet (F-18) | `d6a5c7d` | legacy hotspots cannot grow | **Plan amendment first**: the planned `value > file max` mechanism was disproven by research — a new 36-LOC function never exceeds bridge's baseline max 1209 (and the first re-proof attempt was invalidated by its own `git reset --hard` wiping the uncommitted fix; lesson recorded: commit before reset-based proofs). Implemented per-symbol grandfathering: `legacy_verdict()` (`[LEGACY GROWTH]` = known symbol above its own baseline LOC; `[LEGACY-NEW]` = unknown symbol in a legacy file; both FAIL), `file_symbol_stats()` + `--rebuild-legacy-baseline` (integrator-only merge: existing maxima/func_count preserved byte-for-byte, `funcs` maps added for all 76 files, bridge 220 symbols, coverage floor carried over). **Exploit re-proof (committed tree): identical 36-LOC function in bridge.py → pre-push lane exit 1, `[LEGACY-NEW] … LOC 35 > 30 … must meet the standard (RULE 16 §16.5)`** — the master plan's R0.3/D6 negative test ("adding 31-LOC func to bridge.py fails") now holds. Current-tree byte-identity preserved in all four gate modes (`8c979b24` / `e371764d` / `5a91b6db` / `4d5baeca`). +2 tests (new-symbol fails + grandfathered-symbol-stays-warn; symbol-growth fails) — 14 tool tests |
| B20 record + docs (F-19) | this commit | SOR §8 row + record + index | `tests/test_verify_quality_tool.py` row added to SOR §8 (14 tests: fallback/subset/ratchet/refuse-lower/error-lanes/per-symbol-legacy); plan amendment recorded; this record; `docs/README.md` index row |

## RULE 18 / RULE 16 end-recheck (user-instructed)

- **RULE 18**: every function in the touched file ≤30 LOC
  (`tools/verify_quality.py`: largest = 26; `legacy_verdict` 17,
  `downgrade_legacy` 23, `file_symbol_stats` 16, `rebuild_legacy_baseline`
  22 — all named responsibilities, no `foo_part1` splits).
- **RULE 16**: pytest 541 (+2), node 115, ratchet gate 128 fails
  (unchanged), coverage 44.31/35.10 (floor held), vulture @90 = 0,
  vulture @60 on the gate tool = 0, all four gate-mode outputs
  byte-identical on the current tree, `pre_push_check.sh` exit 0.
- **Anti-gaming §16.2**: the per-symbol map is the anti-gaming enforcement
  itself (a new over-limit symbol cannot hide behind the file's legacy
  status); no gaming patterns introduced.
- **§16.5**: the exploit proof demonstrates the enforcement works in both
  directions (before: exit 0 with 69 warns; after: exit 1).

## Findings resolution (round 5)

- **F-18** closed: per-symbol legacy ratchet; D6 negative test satisfied
  (proven live both before and after).
- **F-19** closed: SOR §8 row added.
- **F-20** handover note only (AGENT_RULES.md RULE 16 ratchet wording →
  Round 0/D7 owner; no unilateral rules edit).

## Remaining honest limitations (documented, other owners)

- cc/cognitive/params/methods/nesting on legacy files still downgrade
  (no baseline maxima for them) — full per-metric ratchet stays R0.3/D6.
- New classes in legacy files are not detected (funcs map covers
  functions only) — same owner.
- `cdp_events` coverage orphan, `output_wait`, `single_job_runner`
  coverage — A/C/D owners (unchanged from round 3).
