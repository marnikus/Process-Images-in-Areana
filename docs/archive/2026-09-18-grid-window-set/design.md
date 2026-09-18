# Grid save resets layout + preset load errors: 13-vs-14 window-set desync

Date: 2026-09-18. Branch: `arena/01a0b3ea-process-images-in-areana`.
User report: "fix grid save is not working! still move the win and close app
but win on restart is resetted" + "it also give error if save preset in grid
and try to load it".

## 1. Diagnosis (proven with `tools/repro_grid_save.py`, since removed)

**Root cause — Python/JS window-set desync.** `sash-core.js` `WINDOWS` has 14
entries (incl. `captcha` — added with the 2Captcha window); Python
`app/core/layout_service.py` `WINDOW_IDS` still has 13 (no `captcha`).

Failure chain for "reset on restart":

1. Every drag/resize calls `_save()` → `save_grid_layout(14-window tree)`.
2. Python `canonical_grid_payload` → `parse_grid_payload` → "window set
   mismatch" → `migrate_grid_tree` finds nothing missing (all 13 present +
   1 extra) → returns the tree unchanged → re-parse still fails → falls
   into `return default_payload(), None` — **success carrying the DEFAULT**.
3. `save_grid_layout` returns True and **stores the 13-window default**,
   discarding the user's arrangement. Close-time `flushPersistence` does
   the same on exit.
4. On restart the backend serves the 13-window default; JS `deserialize`
   migrates it (appends captcha to the DEFAULT tree) and overwrites the
   good localStorage tree → user sees the default grid. Reset, every time.

Same root cause also silently drops `captcha` from `closed`/`minimized`
(`save_window_states` filters by `WINDOW_IDS`).

Failure chain for "preset save → load error" (two defects):

1. `save_window_preset` canonicalizes the 14-window tree through the same
   path → stores a doc whose `grid.payload` is the stale 13-leaf default
   (tree/count stay 14 — inconsistent doc).
2. `load_window_preset` returns an `{ok, name, payload, window_states}`
   envelope, but JS `_showPreview` feeds it straight into
   `validatePortablePreset`, which requires the portable `format` field →
   "Preview unavailable: unsupported window preset format or schema
   version". Contract mismatch, independent of the window set.

Additionally, `load_window_preset` applies the layout server-side
(`set_state` + emit) the moment "load" is clicked — i.e. behind the
preview modal, before the user confirms. Redundant (the JS
preview→apply→`_save` flow owns the change) and premature; it becomes a
pure getter.

## 2. Design

**Fix 1 — sync the window set** (`layout_service.py` only):

- `WINDOW_IDS` += `"captcha"` (same position as JS: after `settings`);
  `WINDOWS` += `{"id": "captcha", "title": "Captcha — 2Captcha Control"}`
  (exact JS title).
- `default_grid_tree()` += captcha leaf mirroring `SashCore.defaultTree()`:
  `col[prompt, run, settings, captcha]` sizes `[40, 22, 26, 12]`.
- No version bump (`GRID_VERSION = 4` both sides); old 13-window payloads
  migrate (captcha appended, user structure preserved).

**Fix 2 — reject instead of silent default substitution** (RULE 13:
"REJECTED when invalid, leaving previously stored layout untouched" —
current code does the opposite on migration failure):

- `canonical_grid_payload`: migration failure / exception → `(None, err)`
  instead of `(default_payload(), None)`. All callers already handle
  `(None, err)`: save warns + keeps old, get returns `""` (JS keeps its
  localStorage tree — no clobber), preset save/load return explicit
  `{ok: False, error}`, undo push returns False, import rejects.
- This turns any future validation bug into a visible warning instead of
  silent layout loss.

**Fix 3 — preset load contract:**

- `load_window_preset` validates the doc's `grid.tree` and returns the
  stored portable doc JSON on success (in place edit, no new methods —
  Bridge is over the method limit, RULE 16.5); `{ok: False, error}` on
  failure (missing / non-portable / bad tree). No server-side apply.
- JS `_getDocument` handles `{ok: false}` (message + `callback(null)`).
- Old docs saved by the buggy code (14-leaf tree/count, stale 13-leaf
  payload) validate and apply via `grid.tree`, then self-heal on the
  apply's `_save`. No store migration needed.

**Rejected:** bumping `GRID_VERSION` (unnecessary — same version, fixed
set, migration covers old); migrating non-portable legacy docs on load
(no such docs exist in the wild — portable docs always had 14 `windows`);
fixing the close-time `runJavaScript` flush race (best-effort backstop;
continuous per-drag saves cover it — noted as known limitation).

## 3. RULE 18 recheck (changed code)

- `layout_service.py`: +2 list entries, +1 leaf, 2-line behavior change —
  file stays ~185 lines.
- `bridge.py`: `load_window_preset` rewritten in place (17 LOC, was 19 —
  no growth, RULE 16.5); no new methods, no new imports.
- `window-presets-actions.js` `_getDocument`: +5 lines.
- No new modules. Tests: new `tests/test_grid_layout.py` (~13 tests),
  new `tests/js/test_window_presets.mjs` (2 tests, registered in
  `package.json` `test:js`).

## 4. Verification

- pytest: full suite green incl. new layout tests (window-set parity
  Python↔JS, 14-leaf round-trip, 13→14 migration, unfixable-set rejection,
  preset save/load round-trip via fake bridge, no apply-on-load).
- node `test:js`: green incl. new `_getDocument` contract tests.
- `tools/verify_quality.py --changed --allow-legacy`: 0 code fails.
