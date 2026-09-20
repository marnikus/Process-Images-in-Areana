# Merge note — 2026-09-20

This round-1 plan was written on branch `arena/01a0bc3b-…` against `6bbaf8b` (B9) and merged into
`arena/01a0bba4-…` after B10–B13 had landed. It is superseded in shape by round 2 (one staged chain
S1…S10, `../2026-09-20-dynamic-urls-and-worker-debug/`), and the drift both plans must absorb is
recorded once, in **`../2026-09-20-dynamic-urls-and-worker-debug/merge-note.md`**. The two points that
hit this document directly:

* its invariants **I-39…I-42 are already taken** in `docs/current/SYSTEM_OF_RECORD.md` (B10–B12) —
  land them as **I-47…I-50** (mapping table in the round-2 note §1);
* the "one eligibility rule" it plans (`eligible_images`, replacing `queue_scan.selected_images` and
  `batch_orchestrator._selected_images`) **already exists** as `app/core/run_scope.py` (B13b, I-44) —
  both clones are deleted; S4 extends that module instead of adding a second rule.

The plan text below this folder is unchanged (RULE 17).
