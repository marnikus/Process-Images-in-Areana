# Area B Round-4 Follow-up Plan — B16–B18 (2026-09-19)

Derived from `review.md` (same directory). Scope discipline unchanged:
Area-B lane only (gate tooling, its tests, docs). Explicitly NOT here:
everything owned by Round 0 / Area A / C / D per the master plan, and any
production `app/` change (no finding requires one).

| Step | Finding | Deliverable | Priority | Exit criteria |
|---|---|---|---|---|
| B16 | F-14 + F-17a | Gate integrity hardening in `tools/verify_quality.py`: (1) `--update-coverage-baseline` refuses to LOWER the stored `coverage` floor (SystemExit with a clear message; equal/higher accepted) — closes the silent ratchet-defeat; (2) `--coverage-ratchet` with a baseline missing the `coverage` key appends an explicit WARN lane ("ratchet floor unavailable — absolute D4 lanes applied") instead of silently degrading. Normal-mode outputs must stay byte-identical (B13 discipline: snapshot all three modes before/after) | P1 | negative test: update-to-lower exits non-zero and leaves the baseline untouched; missing-key test shows the warn lane; absolute/ratchet/text outputs byte-identical; 535 pytest + 115 node green |
| B17 | F-15 + F-16 | Pre-push changed-file lane actually engages: `pre_push_check.sh` resolves the base as env `VERIFY_QUALITY_BASE` → `origin/<current-branch>` (if a merge-base exists) → `origin/main` (loud warning as today), and logs which base + how many files were gated; test robustness — `tests/test_verify_quality_tool.py` derives its valid base dynamically (most recent ancestor whose diff to HEAD contains app .py files) and replaces magic `50`s with a real all-file comparison | P1 | `bash tools/pre_push_check.sh` exit 0 AND the gate step shows a real subset (files_checked < all-files, no GATE HONESTY warning) while unpushed app changes exist; subprocess tests green without hardcoded hashes |
| B18 | record | Round-4 implementation record (Before→After, byte-identity hashes, RULE 18/16 end-recheck) + `docs/README.md` index row for this folder + push | P2 | record exists and matches measured numbers; folder indexed; branch pushed |

Order: B16 → B17 → B18 (integrity first, then the lane that depends on
it, record last).

Per-step gates (RULE 16, unchanged): pytest + node green, ratchet gate
fails never above 128, coverage never below 44.31/35.10, vulture @90 = 0,
no §16.5 legacy hotspot growth (no production file touched at all this
round), anti-gaming §16.2 respected. The baseline `coverage` key may only
move up, and only via the now-guarded flag.
