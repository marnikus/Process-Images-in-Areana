# S7 — Receiver flag + the ⊘ icon (final stage record)

**Date:** 2026-09-21 · **Status:** landed, gate-green · **Plan:** `../2026-09-20-dynamic-urls-and-worker-debug/tdd-interfaces.md` §S7

## What landed

One Python owner (`url_policy`) decides whether a URL row can take a run job right now; the web never
recomputes it. `UrlRow.receiver` (+ persisted `receiver_reason`) are appended last in the dataclass
(positional-constructor safe, RULE 13 round-trip via the existing `asdict`/`from_dict` shape — no
migration). `mark_receivers(rows, allowed, pool) -> int` is the single writer — called by
`url_queue.commit_urls` (every slot funnel) and by the Python reconciler each pass (`Report.flags`).
The reason ladder: `not enabled` → "unchecked" → `no tab_id / not run-gated` → "not linked" →
pool-missing-or-disconnected → "offline" → `current_image` set → "busy" → else `""` (receiver).
The icon is one span injected into the existing status-cell template (`render.js` stays 74 lines,
net-zero): `${u.receiver === false ? <span class="url-not-receiver" title="…">⊘</span> : ''}`,
+5 lines of CSS already-linked. Serializer + both undo builders carry the flag and the reason
(`bool(u.get("receiver", True))` — an unmarked row never flashes an icon).

## TDD ledger

- **RED:** `tests/test_url_receivers.py` (11 tests) — ImportError on the new symbols at base;
  `tests/js/test_url_list_receiver_icon.mjs` (5 tests) — `url-not-receiver` never appeared.
- **GREEN:** 11/11 + 5/5.
- **REFACTOR:** none — `receiver_reason` is a ladder, no chains.

## Adaptations from the plan-text (letter kept)

1. **`receiver_reason` also persisted as a dataclass field** (last, after `receiver`), not recomputed
   on the web: the plan's test 12 requires the JS `title` to equal the Python wording, and no path
   carries the reason to JS other than the row payload. UI still never computes eligibility — it
   renders `u.receiver_reason` verbatim. Budget impact: `undo_entries` builders 11/7 → 13/9,
   `arena_serialize.urls_to_js` 14 → 16 (file max unchanged), `UrlRow` span 26 → 28 (file max 74 unchanged).
2. **render.js function-count lock is 10**, not 12 — the actual base file has 10 methods (the plan's
   12 was aspirational). Line count 74 matches the plan. Lock pins 74/10.
3. **Run-gate source-lock scoped to the two new functions** — a whole-file "no `for u in`" ban trips
   on a pre-S7 set comprehension (`url_policy.py:110`); `inspect.getsource` on `mark_receivers` and
   `receiver_reason` enforces the intent (no re-filtering, `.enabled` only read in the ladder).
4. **`reconcile_once` marks receivers after join**, feeding `Report.flags` so icon-worthy changes
   commit + `wake("urls")` without spamming the auto-connect summary line (`_commit_and_log` now
   commits on `changed or flags`, logs the summary only on structural change).

## Gate evidence (this stage, `bash tools/stage_gate.sh --js`)

- Quality: **PASSED, 0 fails**.
- Frozen seams: 88 passed, 1 skipped.
- Full suite: **1763 passed, 4 skipped** (S6 recorded 1745/11; +11 S7 module + 7 earlier-skip-now-run).
- Characterization goldens through the supervisor pipeline: green (14/14 within the suite lane).
- JS: **252 passed / 0 failed** (247 + 5 new).
- Ratchets held: `models.py` max_class_loc 74, `undo_entries.py` max_func_loc 17,
  `arena_serialize.py` max 23, `render.js` 74 lines / 10 funcs.

## System of Record

Rows updated: **I-51** (new — single owner of the receiver gate, icon reflects only), I-45 verified
by `test_url_receivers.py:1-8` + `test_url_list_receiver_icon.mjs:9-13` + `tests/test_url_list*.py`.

## Remaining

S8 (window contract 15 → 16 + L-5 rescue), S9 (live debug content), S10 (consolidation + `--record-baseline`).
