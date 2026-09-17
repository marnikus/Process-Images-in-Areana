# 2026-09-17 — Watcher window blank + grid divider/sash bug fixes

Status: implemented and verified. Root causes found by running the **real**
sash-grid JS in Node against a mini flexbox layout engine (see "Method"). Fixes
are JS-only; plus two pre-existing RULE 16 gate failures in Python that blocked
the pre-push check (pure extractions, no behavior change):
`app/ui/main_window.py` (`MainWindow.__init__` 53→29 LOC via 4 helpers) and
`app/services/multi_page_dispatcher.py` (`run_one_image_on_page` 32→26 LOC via
`_finish_page_safely(FinishCtx)`).

## Reported bugs

1. **Watcher window blank** — the Watcher window in the grid shows an empty frame, no content.
2. **2nd divider resizes all rows** — with 4 rows, dragging the 2nd horizontal divider
   changes the sizes of the rows above it; dividers 1 and 3 "work".
3. **Row sashes disappear after drag-dropping windows** — horizontal dividers vanish
   intermittently after dropping a window.

## Root causes

### Bug 1 — `watcher` missing from the panel map (deterministic)

`SashGridWindowStore._collectPanels()` (sash-grid-windows.js) maps window id → panel
element id, but has **no `watcher` entry**. `SashGrid.render()` rebuilds the grid with
`gridEl.replaceChildren(frag)` — every panel is re-parented from `this.winEls`, and
`#winWatcher` (a child of `#sashGrid` in index.html) is therefore **deleted from the
DOM on the first render**. The `watcher` leaf still renders its `.sash-window` frame,
but `_buildNode` finds `this.winEls['watcher'] === undefined` and appends nothing:
a blank window.

Fix: add `watcher: 'winWatcher'` to the map (plus the missing `watcher` icon in
`WIN_ICONS` for consistency).

### Bug 2 — resize commit double-counts hidden children (reproduced in simulation)

`_resizeUp()` (sash-grid-drag-resize.js) committed new sizes as:

```js
sizes[i] = renderedPx[i] / (total - sashTotal) * 100     // visible children
sizes[i] = prev[i]                                        // hidden children
```

When the split contains **hidden children** (closed/minimized windows or emptied
nested splits — common in the user's layout: `browser`, `arena_presets`,
`block_config`, `progress` closed; `settings` minimized), the visible children's
rendered px already fill the **entire** free area (hidden children occupy 0 px and
their sashes are 0 px). Their percentages therefore sum to **100**, and adding the
hidden children's old model percentages pushes the total to e.g. **130**.
`SashCore.normalizeSizes()` then rescales **every** size to 100 — so *all* rows get
new sizes and unrelated rows move.

Reproduced with the real code: in `col[a(hidden), b, c, d]` dragging divider `b|c`
moved `b`, `c` **and** `d`. Which dividers *look* broken depends only on where the
hidden children sit — e.g. with the hidden child at index 0 (the user's
`[browser(closed), …]` column), dragging the divider whose left child is the one
just after the hidden block rescales everything visible, while the last divider's
rescale lands almost entirely on its own left neighbor and looks "fine". That is
exactly the "only the 2nd divider is broken in case I have 4 rows" symptom.

Fix — commit in the hidden-child-safe coordinate system (visible free area):

```
hiddenSum  = Σ prev[i] over hidden children          (kept verbatim)
shownBudget = 100 - hiddenSum
sizes[i]  = (renderedPx[i] / Σ visible renderedPx) * shownBudget   (visible)
```

Visible children keep the exact relative ratios the user dragged (including the
dragged pair), hidden children keep their stored sizes, and the total is exactly 100
— `normalizeSizes` becomes a no-op (modulo float). With no hidden children this
degenerates to the old formula.

**Drag pair follows the visible boundary** (`_startResize`): the resizable pair is
the sash's left child and the **next VISIBLE** child (`rIdx`), because a hidden
child occupies no visible space. Before this, dragging the boundary sash next to a
hidden child was clamped by the hidden child's 96 px min-floor against its *own*
zero-width span (drag did nothing or shrank the visible row). Now the boundary
sash between `[A, B(hidden), C]` moves the A/C visible boundary: A and C trade
space 1:1, B keeps its stored size, and on re-render every child's px is exactly
what the user dragged.

### Bug 3 — sash visibility had two inconsistent writers (reproduced by inspection + fuzz)

Sash visibility was maintained in **two places with different rules**:

* `_syncHidden()` **toggled** `sash-hidden` when a neighbor was a hidden **window**;
* `_hideTouchedSashes()` **only added** `sash-hidden` (never removed) when a neighbor
  was a hidden window **or a hidden split**, and was called from
  `_syncEmptySplits()`.

Add-only accumulation plus a narrower toggle rule is a drift hazard, and the net
behavior had a real UX hole: a hidden window **between** two visible windows
(`[A, B(hidden), C]`) hid **both** neighboring sashes, leaving the A/C boundary with
**no divider at all** — after a drag-drop around such a boundary the user sees
"the sash disappeared" and cannot resize between the two visible rows.

Fix — one pure rule, one writer, called after every state change
(`_applyStates()`, visibility MutationObserver):

> **A sash is hidden if and only if its previous (left/top) sibling is hidden**
> (window `sash-win-hidden`/`sash-win-closed`, or split `sash-split-hidden`).

Consequences: a hidden window's slot boundary is always marked by exactly one
draggable 6 px divider (at the hidden slot edge); visible rows never lose the sash
between them; leading-edge hidden windows keep today's look (no line at the very
top/left). `_hideTouchedSashes` is deleted; the sash loop leaves `_syncHidden`.

## Verification

* `tests/js/test_sash_bugfixes.mjs` — regression tests running the **real**
  sash-core/sash-grid parts under Node with a minimal DOM + flexbox engine
  (`tests/js/fake_dom.mjs`, `tests/js/sash_harness.mjs`):
  * every window (incl. `watcher`) keeps its panel inside its grid frame;
  * dragging any divider of a 4-child col split with a hidden child changes only
    the two adjacent children (model + rendered px);
  * sash visibility matches the single rule after renders, close/open,
    minimize/restore, drops and resizes; a hidden window between two visible
    windows leaves a visible sash at the boundary.
* Fuzz (real code, user's real layout): 4 seeds × 900 steps of random drops,
  sash drags, close/open, minimize/restore — after every step: single sash rule
  holds, model sizes valid (sum 100, ≥ min), every visible window rendered with
  its panel at non-zero size. 0 failures across 3600 steps.
* Existing suites green: `pytest tests` **198 passed**, `npm run test:js` **42
  passed** (35 baseline + 7 new), `tools/verify_quality.py --changed
  --allow-legacy` **0 fails** (120 pre-existing legacy warns).

## Files touched

| File | Change |
|---|---|
| `app/ui/web/js/sash-grid-windows.js` | `winElIds`: + `watcher: 'winWatcher'` |
| `app/ui/web/js/sash-grid.js` | `WIN_ICONS`: + `watcher`; `_applyStates`: + `_syncSashes()` |
| `app/ui/web/js/sash-grid-tree.js` | `_syncHidden`: windows only; new `_syncSashes()` (single rule); `_syncEmptySplits`: no sash writes; `_hideTouchedSashes` deleted; MO callback: + `_syncSashes()` |
| `app/ui/web/js/sash-grid-drag-resize.js` | `_startResize`: next-visible `rIdx` pair; `_resizePixelAllocation`: pair = (sIdx, rIdx); `_resizeUp` → new `_commitResizeSizes()` (hidden-child-safe commit) |
| `app/ui/web/js/sash-grid-windows.js` | `showWindow`: + `_syncSashes()` |
| `tests/js/fake_dom.mjs`, `tests/js/sash_harness.mjs`, `tests/js/test_sash_bugfixes.mjs`, `tests/js/user_layout.mjs` | new regression harness + tests (user's real layout as shared fixture) |
| `package.json` | `test:js` includes the new test file |
| `app/ui/main_window.py`, `app/services/multi_page_dispatcher.py` | pre-existing RULE 16 gate fails fixed by extraction (no behavior change) |
| `docs/current/SYSTEM_OF_RECORD.md`, `docs/README.md` | row 19: accurate 13-window list + sash single-rule/resize invariants; archive pointer |
