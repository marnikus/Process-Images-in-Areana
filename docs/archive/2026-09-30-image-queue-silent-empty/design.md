# Fix — the image list displays nothing while the Folder Picker still counts the images (problem definition + design)

Owner report 2026-09-30 (screenshot): the **Folder Picker** window shows the path
(`F:/Stocks 2026/icons testing/single`), working Browse / Scan / New Batch Scan buttons, and the
stats line **"55 images 6 pending"** — but no image list anywhere; the area under the picker is
empty. "It bring bug and folder picker display nothing now."

## 1. Problem definition — what the screenshot proves, and what stays silent

**The scan and the state pipeline work.** The stats line is rendered by `FolderPicker.restore(state)`
(`folder-picker.js`), which needs `state.folder` AND `state.images` from the same arena payload —
so 55 images reached the UI. The rows, however, are rendered **only** by the Image Queue lane
(`image-queue.js` facade → `image-queue/{store,thumbs,render,actions}.js` → `#queueTableBody`).
That lane has three silent single points of failure, and each one ends in exactly the screenshot:
picker alive, list gone, no honest reason anywhere.

* **S1 — unwired modules are accepted silently.** `ImageQueue.init()` caches
  `window.ImageQueueStore / Thumbs / Render / Actions` without checking them. When one of the
  four files did not load (a partial deploy, or a **merge that kept the split facade while the
  other line carries a monolithic `image-queue.js` with no `image-queue/` directory** — the
  difference between this branch and the owner's `befor-merge…` line, verified in their trees),
  `init()` "succeeds" (assigning `undefined` throws nothing; `Boot` marks the panel booted).
  Every later push then throws a raw `TypeError` (`Cannot read properties of undefined (reading
  'restore')`) inside B10's per-panel guard — one cryptic log line, and the table is empty
  **forever**: each subsequent push hits the same dead lane. `FolderPicker` is self-contained and
  keeps rendering: precisely the reported split.
* **S2 — rendering into a missing table is silent.** `ImageQueueRender.render()` returns without
  a word when `#queueTableBody` is not in the DOM (the B11 class — render into an id that does
  not exist; the L-5 class — a window the grid never attached). The queue shows "nothing" with
  zero diagnostics.
* **S3 — no self-heal.** `init()` caches the modules once; `render`/`thumbs`/`actions` are read
  from the cache forever. Even if the missing file appears later (a repaired build, a finished
  partial load), the queue stays dead until an app restart — against the spirit of RULE 24 (no
  visible value waits for a restart).

## 2. The rule this fix enforces

> **A panel that cannot render says why — once, by name — and recovers the moment what it needs
> appears. Silence is a bug.**

| # | Sub-rule | Where |
|---|---|---|
| R1 | The facade resolves its four modules **at call time** (`_mod(kind)`); a missing module is reported **once** through LogConsole + console, naming the kind and the exact file that defines it (`image-queue/store.js` …). A broken lane never throws per push and never touches the DOM. | `image-queue.js` |
| R2 | Call-time resolution makes the lane **self-healing**: a module that appears later renders on the next push — no restart (RULE 24). | `image-queue.js` |
| R3 | `init()` verifies the wiring at boot and reports immediately — the user learns at startup, not at the first empty table. | `image-queue.js` |
| R4 | `render()` reports a missing `#queueTableBody` once instead of returning silently. | `image-queue/render.js` |

Precedents in this repo: B6 ("a missing bridge slot is reported instead of silently returning"),
B10 ("a live-state render failure is never silent"), B11 (render targets verified), L-5 (a panel
the grid dropped is rescued and reported).

## 3. Rejected shapes

* **Inline fallback store in the facade** — a second copy of the store rules (jscpd duplication
  gate; one-home RULE 4). The honest answer for a missing file is its name, not a shadow copy.
* **Blanket try/catch around every delegation** — hides real defects behind the report; only the
  *presence* check is guarded, an existing module that throws stays loud (B10 already isolates
  panels at the push boundary).
* **Adding FolderPicker to `LIVE_STATE_PANELS`** — the picker is not broken and its stats are
  restore-driven; widening the live set changes unrelated refresh behaviour.
* **Fixing the owner's merged index.html here** — this branch's script list is correct and
  pinned by tests; the fix makes any build *say* which file is missing instead of failing
  silently.

## 4. Structure (RULE 16 / RULE 18)

| File | Change | Size after |
|---|---|---|
| `app/ui/web/js/panels/image-queue.js` | `_mod(kind)` + `_files` map + one-time report; all delegations resolve at call time; `init()` boot check. | ~210 |
| `app/ui/web/js/panels/image-queue/render.js` | missing-`#queueTableBody` one-time report. | ~85 |
| `tests/js/test_queue_silent_empty.mjs` | RED-first whole-page tests (the real boot path, real scripts, fake QWebChannel). | new |

Longest new function `_mod` ≈ 12 LOC / CC 4; no file leaves the 150–300 band; no new dependency.

## 5. Tests first (RULE 8) — the RED list (whole-page harness: every script from index.html, page order)

1. RED `a missing queue module is reported by name, never a raw TypeError` — with
   `ImageQueueStore` absent (the merged-build shape: facade cache cleared + module deleted), a
   live push renders no rows and logs ONE line naming `ImageQueueStore` +
   `js/panels/image-queue/store.js`; the log never contains `Cannot read properties of undefined`.
2. RED `a second push does not repeat the report` — the missing-module line appears exactly once.
3. RED `a module that appears later renders on the next push — no restart` — restore the module,
   push again: 3 rows, no re-init, no restart.
4. RED `a queue table that is not in the DOM is reported, not silent` — `#queueTableBody`
   unresolvable: one line naming it; a second push stays at one line.
5. Kept green: the whole B10 suite (8 tests) — the wired lane must behave exactly as before.

## 6. Outcome (2026-09-30)

Implemented and green.

- **Fix shape as designed (§2)**: `image-queue.js` resolves every module at CALL time via
  `_mod(kind)` (cache + `window` fallback), reports a missing module ONCE per kind through
  `_reportMissing` (console.error + LogConsole, naming kind AND expected file — e.g.
  `ImageQueueStore … js/panels/image-queue/store.js`), and every delegation early-returns on a
  broken lane: no raw `TypeError`, no DOM writes, no per-push spam. `init()` boots the check for
  all four modules. `render.js` reports a missing `#queueTableBody` once (`_warnMissingTable`)
  and renders nothing; `thumbs.js` guards its store reads (`_requestable`, `fetchAll`, `onReady`)
  so even timer callbacks cannot crash. A module that appears later renders on the next push —
  RULE 24 self-heal without restart.
- **RED→GREEN**: `tests/js/test_queue_silent_empty.mjs` went 4 RED (raw
  `Cannot read properties of undefined (reading 'thumbCache')` escaping a thumb timer;
  zero reports) → 4 GREEN. Kept green: B10 (8), folder picker (8), boot-all-panels (4);
  full lanes: JS 486/491 (1 pre-existing base red: `test_live_debug_panel` off-by-one on
  `listeners.js` `split('\n')`, byte-identical to the branch point), pytest 3237 passed
  (3 known env reds deselected, unchanged since v7).
- **RULE 16 gates**: first cut breached ratchets (facade max_cc 9→10, render max_func_loc
  17→26 + nest 3, thumbs max_cc 7→8). RULE 19 squeeze: extracted `_reportMissing`,
  `_warnMissingTable`, `_requestable`, `_fillRows`; flattened `_resolvePath` (early return).
  All per-function maxima back at or under baseline; only `file_lines`/`func_count` grew
  (184→213, 78→98, 66→72) — the honest report code. `tools/quality_baseline.json` updated
  SURGICALLY for the three files only (a full `--record-baseline` refresh was tried and
  REVERTED: it would also have blessed pre-existing drift in workspace/live files that this
  change did not touch).
- **RULE 18 recheck (end-of-task)**: image-queue.js 213 LOC (150–300 ✓), longest function
  `_bindToolbar` 14 LOC, max CC 9 (`_resolvePath`/`onJobFinished`), nesting ≤2; render.js 98,
  thumbs.js 72; every new function 4–12 LOC, params ≤4, CC ≤10. No file or function leaves its
  band; the wired lane behaves exactly as before (B10 green).

Known left-overs, not this bug: the `test_live_debug_panel` count assertion is off-by-one
against `readJs().split('\n')` on a trailing-newline file (red at the branch point);
`listeners.js` itself is byte-identical to the branch point.
