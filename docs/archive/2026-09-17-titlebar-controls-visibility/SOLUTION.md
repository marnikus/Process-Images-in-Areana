# 2026-09-17 — Window minimize/close icons must never be hidden by window resize

Status: implemented and verified (tests-first; 10/10 new JS tests pass,
existing suites green, 4-seed × 900-step fuzz clean with the
"controls never fit-hidden" invariant asserted after every op). Report:
on the Prompt Editor (and every window whose
title bar carries secondary buttons/badges), the `─`/`✕` window controls at the
right edge of the title bar get partially or fully **clipped** when the window
isn't wide enough — the Save button sits on top of them / they run off the
window edge (screenshot: `Save` + half-cut `✕`).

**Requirement:** in ANY resize, `─`/`✕` must be fully visible on the right side
of every window, always clickable.

## Root cause (verified by reading the shipped CSS/HTML/JS)

The title bar is a flex row (sash-layout.css: `display:flex; gap:4px`) with
items in this order:

```
[grip] [icon] [bare title text] [spacer] [secondary buttons/badges] [.win-controls]
```

`.win-controls` is appended LAST by `_attachWindowControls()`, so it is always
the **rightmost** item — and therefore always the first thing clipped. The
row's minimum width is far larger than the minimum window width:

| item | min width | why it can't give space |
|---|---|---|
| title bar padding (6px × 2) | 12 | fixed |
| `.win-grip` | ~14 | `min-width:auto` (icon font) |
| gaps (4 × 4px) | 16 | flex gap, always present |
| leading `.material-icons` | ~16 | `min-width:auto` |
| **bare title text** | longest word | **anonymous flex item — a bare text node can never be ellipsized** (`text-overflow` needs an element box); `min-width:auto` floors it at min-content |
| `.btn-small` Save/Clear/Reparse… | full text width | `min-width:auto` = min-content, never shrinks |
| count/status badges | full text width | same |
| `.win-controls` | 20+2+20 + margin-left 6 = 48 | `flex-shrink:0` (correct, but the rest of the row doesn't yield) |

Minimum content row ≈ **190–250 px** depending on the window. But a window may
legally shrink to **96 px** (`--sash-min-panel`, also the JS resize floor).
`.panel { overflow: hidden }` (layout.css:49) then clips the overflow — at the
right edge, exactly where the controls are.

So the clipping is **deterministic and width-dependent**: any resize below the
row's min-content width cuts the icons. Prompt Editor (Save) is the classic
case; URL List (two buttons + badge) is the worst.

Note: even if *everything else* could vanish, the fixed core
(padding 12 + grip 14 + icon 16 + gaps 16 + controls 48 = **106 px**) still
exceeds the 96 px floor — so pure "let things shrink" CSS **cannot** satisfy
the requirement; the core itself must be trimmed, and secondary items need a
deterministic drop order.

## Design

Three parts, following the same **single-rule / single-writer** philosophy as
the 2026-09-17 sash fix.

### A. CSS — give the row space to yield (sash-layout.css)

* New `.win-name` — element wrapper for the title text:
  `flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap` → the text truncates to "…" **before** anything on the
  right is clipped.
* `.win-title { overflow: hidden }` — the bar itself clips; ellipsis needs it.
* Trim the fixed core so it fits the 96 px floor:
  `.win-title` padding `4px 6px` → `4px 2px` (the bar is full-bleed already),
  `.win-controls` `margin-left: 6px` → `0` (the 4px flex gap still separates).
  New core = 2+14+4+16+4+4+4+42+2 = **92 px < 96 px** — the guarantee's base.
* `.win-title .fit-hidden { display: none }` — class used by the fitter to
  drop secondary items.

### B. JS — one pure fit function, one writer: `_fitTitleBars()`

Same pattern as `_syncSashes()`: **recompute from scratch, never accumulate.**
Per title bar:

1. Un-hide everything it previously hid (class-based, idempotent).
2. While `title.scrollWidth > title.clientWidth` and a *secondary* item remains:
   hide the **rightmost** visible secondary (closest to the controls).

Protected (never hidden, never shrink below zero): `.win-grip`, the leading
icon (index 1), `.win-name` (truncates instead), `.spacer`, `.win-controls`.
Secondary = anything else in the title (Save/Clear/Reparse/Popup buttons,
count/status badges).

Call sites (every width/state change): `_applyStates()` (covers render,
close/open, minimize/restore, drops, drag commits), `_resizeMove` (mid-drag),
`window 'resize'` listener (app-window resize), once after
`_ensureWindowControls` on init.

**Termination/guarantee:** each iteration removes one item; the final state
(core 92 px) fits the 96 px floor, so the loop always exits with the controls
fully visible. Widen the window → next fit restores everything (pure function,
no state drift — a hidden Save reappears when there is room).

### C. JS — wrap the bare title text (`_wrapTitleText`)

Inside `_createWindowControls` (once per window, idempotent): every bare
non-whitespace text node directly under `.win-title` is wrapped in
`span.win-name`. This is what makes ellipsis possible — the browser cannot
truncate an anonymous flex text item. No HTML files change; all 13 windows are
covered uniformly, including future ones.

Drag safety: `_pointerDown` already ignores `button, …, .win-controls,
.win-btn` for drag start, so hidden/shrunk title items don't affect
drag-drop.

## Verification plan (tests first)

* `tests/js/test_title_fit.mjs` (real production JS under the Node harness):
  1. **Structure** — after `SashGrid.init()`, all 13 titles have a `.win-name`
     with the window's text and `.win-controls` is the LAST child.
  2. **Fitter algorithm** (stubbed title geometry via fake-DOM
     `clientWidth`/`scrollWidth`): wide window → nothing hidden; narrow window
     → rightmost secondary hidden first, protected items (grip/icon/name/
     controls) never hidden, final state fits; widen again → everything
     restored (purity).
  3. **CSS contract** — parse sash-layout.css: `.win-controls` has
     `flex-shrink: 0`; `.win-name` has the truncation quartet; `.win-title`
     has `overflow: hidden`; `.fit-hidden` is `display: none`; and the numeric
     core width computed from the CSS values ≤ `--sash-min-panel` (96 px).
     This pins the geometry guarantee so it cannot regress silently.
* Existing suites must stay green: `pytest tests` (198), `npm run test:js`
  (42 + new), `tools/verify_quality.py --changed --allow-legacy` (0 fails).
* Fuzz (drops/drags/close/minimize) re-run — `_fitTitleBars` now runs on every
  op/drag step; it must be a no-op when widths are wide (scrollWidth ==
  clientWidth in the stub).

## Actual results

* `node --test tests/js/test_title_fit.mjs` — **10/10 pass** (4 CSS contract,
  1 structure, 5 fitter).
* `npm run test:js` — **52 pass** (42 prior + 10 new), `pytest tests` —
  **198 pass**, `tools/verify_quality.py --changed --allow-legacy` —
  **0 fails** (120 pre-existing legacy warns).
* Fuzz (real code, user's layout): 4 seeds × 900 steps of drops/drags/
  close/open/minimize — after every step: sash rule, model validity, every
  visible window rendered with panel **and its controls not fit-hidden**.
  0 failures / 3600 steps.
* Fake DOM gained text-node support (`TextNode`, `childNodes`,
  `replaceChild`, computed `textContent`) so the wrap/fit code runs against
  a title structure matching index.html (grip, icon, bare text, spacer,
  secondary buttons/badges).

## Files touched

| File | Change |
|---|---|
| `app/ui/web/css/sash-layout.css` | `.win-name` truncation, `.fit-hidden`, `.win-title` overflow + padding, `.win-controls` margin |
| `app/ui/web/js/sash-grid-tree.js` | `_wrapTitleText` (called from `_createWindowControls`); `_fitTitleBars` + `_rightmostSecondary` |
| `app/ui/web/js/sash-grid.js` | `_applyStates`: + `_fitTitleBars()`; init: `window resize` listener |
| `app/ui/web/js/sash-grid-drag-resize.js` | `_resizeMove`: + `_fitTitleBars()` after flex updates |
| `tests/js/fake_dom.mjs` | `El`: `clientWidth`/`clientHeight`/`scrollWidth` accessors |
| `tests/js/test_title_fit.mjs` | new regression tests (structure, fitter, CSS contract) |
| `package.json` | `test:js` includes the new test file |
| `docs/current/SYSTEM_OF_RECORD.md`, `docs/README.md` | invariant row + archive pointer |
