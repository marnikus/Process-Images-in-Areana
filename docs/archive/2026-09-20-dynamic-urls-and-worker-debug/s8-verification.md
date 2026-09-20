# S8 verification — window catalog and Page Pool rescue

2026-09-20 · S8 only · base `a637bc2` (S7) · invariant **I-51** (plan I-43,
renumbered per `merge-note.md`). S9 worker/queue strips are not implemented here.

## Delivered contract

- `app/core/window_catalog.py` owns the ordered 16-window table, derived ids/titles,
  legacy rename map, grid version 6 and Python default tree. `layout_service` directly
  re-exports the same objects; no forwarding function or duplicate table remains.
- Python and JS agree on ids, order and titles. All JS built-in layouts (default/A/B/C)
  contain every leaf. v5 migration keeps the original subtree (positions and sizes)
  and appends the missing `live_debug` leaf; v6 re-serializes unchanged.
- `winPagePool`/unregistered `page_pool` was replaced by registered `winLiveDebug`/
  `live_debug`. Existing pool controls, counters and table ids remain inside it.
  The actual HTML boots every script in order in jsdom, renders twice and keeps the
  original panel/table nodes attached. Real clicks reach the three pool actions once.
- `LiveDebugPanel` publishes itself and boots through `Boot`; it is a registration
  shell, not S9's content. Pool controls still belong to `PagePoolPanel`.
- L-5 is closed (orphan rescue). L-8 is closed (dead `WIN_ICONS` removed; Python
  table order now agrees with JS). L-7 remains an S10 decision: title-fit runs
  explicitly here and from the S8 test; captcha-saved-page adoption is unchanged.

## TDD evidence and corrections

Initial RED: `fa96aac`, 7 Python failures (missing catalog) and 4 JS source checks.
Review found those JS checks did not exercise mounting and two Python checks lacked
real assertions about JS parity/migration. They were replaced, not treated as proof.

The strengthened 7 feature Python tests and 6 executable JS tests were copied to a
clean `git archive a637bc2` test directory without changing branches: **7 Python
failures, 6 JS failures**. Failures include missing catalog, missing live-debug
mount, unbooted panel, 15 rather than 16 windows, and v5 not gaining `live_debug`.
An additional unknown-node migration/walker test is **equivalence**, not feature RED.

Before the JS tree fix, the real mount test failed `winLiveDebug missing` after
render and preset validation failed `leaf count mismatch`. The old smoke checks
had missed the exact L-5 defect. Updating `sash-core/tree.js` is an S8 plan expansion:
all four shipped layouts must include the new leaf, not only the registry. These
are same-line edits, with no growth in file/function sizes. Title-fit's harness
also includes the real `poolStatusBadge` secondary.

Existing expectation updates (not weakened): four preset window counts in
`test_grid_layout.py` become 16; `test_panel_slots.py` canonical version becomes 6.
The bridge slot/metaobject tests, pinned cooldown test, and golden JSONs are unchanged.

The fresh coverage gate initially found branch coverage 83.22% below 83.24% and
per-file shortfalls in layout_service/browser_tabs/layout_state/url_queue. Added
`tests/test_live_panel_boundaries.py` (8 equivalence tests): real dependency wiring,
pool join with only the CDP boundary faked, idempotent boot scheduling, notification
failure tolerance, progress emit with bad cadence plus a positive control, receiver
read failure, invalid legacy URL and unavailable presets, empty vs broken tab fetch.
No feature or production change was made to those live-panel modules, and no
baseline was re-recorded or lowered.

## RULE 16 / RULE 18 recheck

| Item | Measured / decision |
|---|---|
| New Python catalog | 53 lines; maximum function 19 LOC, CC 1, cognitive 0, nesting 0, params 3; 100% line coverage |
| `layout_service.py` | 300 → 255 lines (gate measure), max function 20, CC 9; inside file ideal; direct re-export avoids dummy wrapper |
| Frozen JS files | constants/store/arena-app use same-line appends only; sash-grid removes 9 lines; tree same-line edits only |
| New small files | Catalog is a pure-data leaf; CSS is a scoped shell; panel `init` is the boot contract required by S8; do not inflate these to 150 lines |
| Core directory | 16 → 17 Python files including `__init__` (post-merge tree, not plan's older count); named catalog extraction removes the duplicated table without creating another package or wrapper |
| Complexity | No new override; no baseline recording; existing hard limits/ratchets remain enabled |
| Duplication | jscpd 1.09%, 23 groups, below 1.24% baseline |
| Vulture | No new findings; four unused imports in bridge/browser_tabs are identical at S7 and remain outside S8 production scope |
| Scope | UI shell/window persistence only; no new slot, signal or pipeline decision |

Validation commands (final results recorded below):

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m coverage run --branch --source=app -m pytest tests -q
.venv/bin/python -m coverage json -o coverage.json
npm run test:js
node --test tests/js/test_title_fit.mjs
.venv/bin/python tools/verify_quality.py --changed --base a637bc2 --allow-legacy --coverage-ratchet
.venv/bin/python -m radon cc -s app/core/window_catalog.py app/core/layout_service.py
bash tools/pre_push_check.sh
```

## Final results

`VERIFY_QUALITY_BASE=a637bc2 bash tools/pre_push_check.sh` **exit 0**:

- Python: **1749 passed, 4 skipped, 5 warnings**, both plain and fresh coverage runs.
  Warnings are unawaited test coroutines in existing panel tests; no golden changed.
- Node: **257 passed, 0 failed** (48 suites). Explicit title-fit: **10 passed**.
- Quality: **0 failures, 0 warnings**, 2 Python files and 6 changed JS files checked,
  `--allow-legacy --coverage-ratchet` enabled.
- Coverage: **88.09% statements / 83.44% branches**, above the stored floors.
- Duplication: **1.088%**, 23 groups (baseline 1.240%).
- Vulture: the four pre-existing S7 findings noted above remain; no new finding.
  Syntax compiled successfully; the script's optional pyflakes check was skipped
  because that package is not installed.
- JS line counts (gate convention): constants **25**, window store **122**,
  arena-app **176**, sash-grid **114**, tree **106** (unchanged).
- Frozen slot/metaobject/cooldown tests, golden JSONs and quality baseline are
  byte-identical to S7. `git diff --check` is clean. No S9 production work included.
