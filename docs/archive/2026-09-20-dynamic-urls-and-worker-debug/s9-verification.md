# S9 implementation and verification

2026-09-20 · base `747e23c` (S8) · scope: read-only live worker/queue detail,
not S10 consolidation. Follow RULE 8/16/17/18, frozen slots and goldens.

## Pre-implementation findings / interface adjustments

- `live_view` will use `feed.eligible_images` (core owns the rule), row.receiver,
  cadence and run state only; never sample or mutate the pool.
- Existing pool rows include job/image/status/busy_since and cooldown time, but
  **not pause-clock evidence**. `busy_since` is job start, not captcha start.
  `PauseClock.total` is charged after each settle, not continuously. The UI must
  not fabricate absorbed/remaining seconds from the job's elapsed time.
  New UI serializer `pool_debug.pool_snapshot(bridge)` wraps one existing pool
  snapshot and reads registered controllers' clocks without changing them. It
  adds optional per-worker last-settled pause evidence, and a fail-closed scope
  flag. The pool class and PageInfo stay unchanged. The existing pool emitter
  and getter delegate with same-line substitutions. Missing clock means unknown,
  not zero; last-settled numbers are labeled and are not advanced by the ticker.
- Progress pushes have the complete live payload. To populate a newly opened UI
  without waiting for a mutation, the **existing** `get_arena_state` getter adds
  the same payload inside `progress.live`; normal arena_state_updated remains
  unchanged. No new slot or signal. One boot read, then pushes; Refresh reads
  only the pool. A 1-second UI tick recalculates elapsed/cooldown/cadence locally,
  with no bridge traffic. Existing PagePool refresh behavior stays untouched.
- Malformed payloads retain the last good snapshot with an explicit stale/error
  message; an empty pool is a valid snapshot that clears all worker lines.
- Watcher OFF suppresses new captcha wording even for a stale waiting row;
  existing Page Pool content remains under its original owner.

## Quality budget before edits

Gate measurements at S8: debug_view max func 9/CC5, layout_state max func19/CC6,
bridge max func15/CC3/class95, page_pool panel max func16/CC7/class139. Existing
bridge and page_pool methods get only same-line serialization substitutions;
layout_state gets a small initial snapshot builder and swaps cadence to live_view.
New functions target <=20 LOC, <=4 parameters, CC<=10; new data/view leaf files
stay below 150 lines where one responsibility does not warrant padding. The S8
LiveDebugPanel stub intentionally grows into the planned S9 facade (not baselined).
No baseline recording, no new quality override. Frozen arena-app/listeners.js and
URL controls are not edited. Test evidence and final measurements follow below.

## RED at S8

Before any production edit: `pytest tests/test_live_debug_view.py` → **11 failed**
(missing `live_view`, missing `pool_debug`, missing `progress.live`/`pause`).
`node --test tests/js/test_live_debug_panel.mjs` → **6 passed / 8 failed**:
all existing S8 tests stay green; new cases fail on missing real DOM content.
Tests drive actual bridge methods and real index.html script order. Clock/signal/
CDP test doubles are boundaries, not the functions under test.

### Additional RED: idle freshness

Initial GREEN work exposed one more S6 assumption: the loop stamps pass time/count
**after** any mutation-driven emission and emits nothing on idle passes. A real
loop + real UI deps test fails with no progress event on an empty scan. Before
fixing it, add optional `LiveDeps.publish` (default None), invoked after stamping.
The UI supplies a read-only progress+pool publisher; no commit/save/joins/probes,
no change to scan or wait decisions. This also refreshes OFF scope on the existing
cadence. `reconcile_once`, its overrides and the four existing deps stay unchanged.

Two test-fixture corrections: frozen listeners has 193 physical lines plus final
newline (194 by the JS gate, 54 functions; 168/51 were stale pre-merge plan
measurements, not the S8 base or current baseline); the boot fake
now returns a valid live getter reply rather than `{}`. Initial getter must copy
progress before augmenting: its legacy serializer shares the state progress dict.
The read-only test now snapshots independently and checks for this mutation.

## Implementation review

- Initial arena augmentation moved to the same UI serialization leaf as pool
  telemetry, rather than growing the >300-line layout panel. Existing accessors
  and `emit_arena_state` retain their function lengths. Bridge/pool methods only
  substitute the read serializer. Service->UI import direction is unchanged.
- Shared `UIHelpers.esc` owns escaping; no duplicate pool-row template. Negative/
  missing/non-finite timing inputs never render NaN/Infinity. Job elapsed and
  cooldown may tick locally; pause values never do. A further executable RED
  caught exhausted-cap wording; the view now says `pause cap exhausted`, not
  `generation timeout paused`. Boot-read coverage is equivalence with the new
  initial payload, not claimed as RED against the whole S8 stage.
- Local focused results: **14 Python passed**, **16 JS passed** (6 S8 + 10 S9).
  Idle-heartbeat tests assert no arena save/cooldown persistence and no mutation;
  a throwing observation callback cannot stop the reconciler or its wait.
- The JS suite already lists this test file from S8; no package.json churn or
  S10 orphan-test adoption is necessary here.

## Final RULE 16 / RULE 18 recheck

`VERIFY_QUALITY_BASE=747e23c bash tools/pre_push_check.sh` **exit 0**, committed
production diff (not an empty/fallback diff): **7 Python + 4 JS files** gated,
**0 failures / 0 warnings**. No `--record-baseline`, new override, golden change,
slot or signal. JS components stay cohesive leaves rather than padded files.
`live/` remains 7 Python files; `ui/services/` is 10 including the new serializer.
The >300-line existing panels only delegate with bounded edits; no extraction
into dummy wrappers and no new decision tree. Existing `reconcile_once` is
unchanged (gate CC11/LOC32 override; standalone radon reports CC12).

| Python file | Gate file LOC | Max function LOC | Max gate CC |
|---|---:|---:|---:|
| live/debug_view | 61 | 9 | 5 |
| live/reconcile | 224 | 32 (existing override) | 11 (existing override) |
| ui/services/pool_debug | 53 | 12 | 4 |
| ui/bridge | 153 | 15 | 3 |
| ui/panels/page_pool | 235 | 16 | 7 |
| ui/panels/layout_state | 313 | 19 | 6 |
| ui/panels/browser_tabs | 560 | 20 | 7 |

All new Python functions: radon CC <=4, <=12 LOC, <=2 parameters;
changed `reconcile_loop` remains radon CC5. New serializer has **100% combined
line/branch coverage**. Bridge's class95/method10 and pool class139/method9
remain unchanged; no legacy maximum grows. Layout emitter remains the same size.

| JS file | Gate file lines | Max function LOC | Max CC | Params | Nesting |
|---|---:|---:|---:|---:|---:|
| live-debug facade | 18 | 8 | 2 | 1 | 1 |
| store | 61 | 12 | 6 | 1 | 1 |
| render | 91 | 12 | 6 | 2 | 1 |
| actions | 34 | 8 | 3 | 3 | 1 |

`arena-app/listeners.js` remains **194 gate lines / 54 functions**, byte-identical
to S8. The stale 168/51 plan measurement was corrected, not used to waive a growth.
All URL-list JS and the S8 registration/grid sources remain byte-identical.

### Final command results

- Full plain pytest: **1763 passed, 4 skipped, 5 warnings** (196.88 s).
- Fresh branch coverage pytest: **1763 passed, 4 skipped, 5 warnings** (198.91 s),
  including all 12 golden traces and the supervisor byte-identity check.
- `npm run test:js`: **267 passed**, 48 suites, 0 failed.
- Explicit `node --test tests/js/test_title_fit.mjs`: **10 passed**, 0 failed.
- Coverage: **88.2193% statements / 83.5600% branches** (12326/13972 statements,
  2704/3236 branches), above stored floors; no baseline re-record.
- jscpd: **1.079195%**, **23 groups / 399 lines**, below 1.240% baseline, no new group.
- Syntax and hygiene passed. Optional pyflakes check skipped (not installed).
  Vulture reports the same four pre-existing unused imports in bridge/browser_tabs;
  not presented as a clean Vulture run. Pytest warnings remain the existing
  unawaited test-coroutine warnings.
- Frozen bridge-slot/metaobject/cooldown tests, all golden JSONs and quality
  baseline byte-identical to S8; slot contract remains **135**. Diff whitespace
  check fixed one trailing blank in the new serializer (no behavior change).
- RULE 16 / RULE 18 reread and checked. Current docs land with the implementation;
  the missing I-53 current-table entry now identifies the existing S7 owner and
  its S9 read-only consumer. S10's whole-chain consolidation remains separate.
