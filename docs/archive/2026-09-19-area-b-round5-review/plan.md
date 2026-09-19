# Area B Round-5 Follow-up Plan — B19–B20 (2026-09-19)

Derived from `review.md` (same directory). Scope: the gate tool Area B
owns and edits (B12–B17 precedent) + docs. NOT here: full per-metric
ratchet with new baseline schema fields (stays R0.3/D6 — B19 implements
only the LOC/class-LOC increase check on the EXISTING schema), JS acorn
gate (R0.2/D6), AGENT_RULES.md edits (F-20 → Round 0/D7 owner).

| Step | Finding | Deliverable | Priority | Exit criteria |
|---|---|---|---|---|
| B19 | F-18 | Legacy-growth check in `tools/verify_quality.py`: `downgrade_legacy` keeps `fail=True` for `loc` breaches with value > baseline `max_func_loc` and `class-loc` breaches with value > baseline `max_class_loc` (message `[LEGACY GROWTH] … §16.5 legacy must not grow`); all other legacy downgrades unchanged (cc/cognitive/params/methods/nesting have no baseline maxima). Characterization: allow-legacy JSON snapshot of the CURRENT tree (hash `8c979b24…`) must stay byte-identical (no current file exceeds its baseline maxima — verified). Tests: synthetic tight baseline → bridge loc breaches FAIL with LEGACY GROWTH; real baseline → bridge loc/class-loc breaches stay warns and NO LEGACY GROWTH lane appears anywhere; anti-gaming still fails on legacy files. Live re-proof: re-run the exact F-18 exploit commit (36-LOC function in bridge.py) → pre-push lane must now FAIL; then reset | P1 | exploit re-proof: gate exit ≠ 0 on the growth commit; current-tree allow-legacy output byte-identical (`8c979b24`); absolute/ratchet/text hashes unchanged (`e371764d`/`5a91b6db`/`4d5baeca`); +2 tool tests; 539 pytest + 115 node green |
| B20 | F-19 + record | Docs: SOR §8 row for `tests/test_verify_quality_tool.py`; round-5 implementation record (Before→After, hashes, RULE 18/16 end-recheck); `docs/README.md` index row; push | P2 | record matches measured numbers; folder indexed; branch pushed |

Order: B19 → B20.

Per-step gates (RULE 16): pytest + node green, ratchet gate ≤128 fails,
coverage ≥44.31/35.10, vulture @90 = 0, no production `app/` change
(B19's proof commit is created and reset within the step), anti-gaming
§16.2 respected (no `foo_part1`; the growth check is a named
responsibility, not a dodge).

---

## Amendment (during B19 implementation)

Research disproved the planned mechanism before it shipped: "loc breaches
with value > baseline `max_func_loc`" can never catch the D6 exploit
(a new 36-LOC function does not exceed bridge's baseline max of 1209).
B19 therefore implements **per-symbol grandfathering** instead: the
baseline gains a `funcs` {symbol: LOC} map per file (merged, existing
maxima preserved); a known symbol may not exceed its own baseline LOC
(`[LEGACY GROWTH]` fail) and an unknown symbol is new code in a legacy
file (`[LEGACY-NEW]` fail). Exit criterion unchanged and met: the
identical exploit commit now fails the pre-push lane (exit 1).
