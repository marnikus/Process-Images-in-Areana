# Grid save root cause + window preset restore: "unsupported window preset format or schema version"

## 1. Report

User (2026-09-18 12:34): "no. same erro if try to restore preset —
`Preview unavailable: unsupported window preset format or schema version`."
The grid still resets on restart despite the round-5/round-7 fixes, and
restoring a saved window preset (the workaround) fails at the preview step
for **every** preset.

## 2. Research — two independent bugs

**A. ROOT CAUSE of the grid reset: Python's window set lagged the UI.**
The UI (sash-core.js) has **14** windows — including `captcha` (added with
the 2Captcha window). Python's `layout_service.WINDOW_IDS` had **13** — no
`captcha`. Consequence for every save of a live grid:

1. JS saves the 14-leaf tree → `save_grid_layout` → `canonical_grid_payload`
2. `parse_grid_payload`: `got (14) != sorted(WINDOW_IDS) (13)` → "window set mismatch"
3. migration: `missing = []` (all 13 present — `captcha` is an *extra*, not missing)
   → `migrate_grid_tree` returns the tree **unchanged**
4. re-validate: still 14 ≠ 13 → "window set mismatch"
5. old fallback: **`return default_payload(), None`** — the user's layout is
   silently replaced on disk with the 13-window default.

**Proof:** the grid stored in `config/session.json` is byte-identical to
Python's `default_payload()` — the user's custom frame never actually
persisted. Every restart restored the default (JS migrate re-adds the
`captcha` leaf client-side, which masked the mismatch in the UI). This is why
rounds 5 and 7 (close-flush, boot restore) could not cure it: the restore
delivered a layout that had already been destroyed at save time.

**B. The 12:34 preset error: the load slot returned the wrong object.**
JS `load(name)` → `_getDocument` → `bridge.load_window_preset(name, cb)` —
but the slot answered an **envelope** `{"ok", "name", "payload",
"window_states"}`, not the stored document. `_showPreview` fed that envelope
to `validatePortablePreset`, whose first check is
`doc.format === "chat-v-bot.window-preset"` → envelope has no `format` →
"unsupported window preset format or schema version" for every preset.
Secondary bug in the same slot: it also called
`set_state(grid_layout=…, window_states=…)` + emitted `grid_layout_changed`,
so merely *previewing* silently rewrote the session's saved layout — and the
JS `grid_layout_changed` listener only logs, so the UI didn't change: a
cancelled preview still desynced backend and UI.

**Legacy risk.** Presets saved before the portable format (slim
`{name, grid:{payload,…}, window_states, app_version}`) would fail the same
validator even if returned as-is — they lack `format`, `windows[]`, `screen`.

## 3. Design

1. **Window-set sync (fixes A).** `WINDOW_IDS`/`WINDOWS` now carry all 14
   windows incl. `captcha` (comment pins the sync obligation to
   sash-core.js); `default_grid_tree()` mirrors the JS `defaultTree`
   (14 leaves, `[40,22,26,12]` for prompt/run/settings/captcha). The silent
   replacement in `canonical_grid_payload` is replaced by a **rejection with
   the reason** (`layout cannot be migrated: …`) — an unreconcilable layout
   must fail visibly (logged + `ok:false` to JS), never swap in the default.
2. **`load_window_preset` becomes a pure reader.** Returns
   `{"ok": true, "name", "document": <full portable document>}` — no
   `set_state`, no emit (previewing is side-effect free; applying is JS-side
   `applyPortablePreset`, which persists via the save path).
3. **`_upgrade_preset_doc`** — portable docs pass through; legacy slim docs
   upgrade to the full portable shape (shared `PRESET_FORMAT` /
   `PRESET_SCHEMA_VERSION` constants mirroring sash-grid.js, synthesized
   `windows[]` from `window_states`, `screen` flagged `synthetic: true`);
   un-canonicalizable grid → `None` → `{ok:false, error}`.
4. **JS `_getDocument`** — pure `_presetResponseDocument(raw)` accepts the
   new `{ok, document}` shape (tolerates a raw document from older builds;
   the old envelope now yields null + a visible message).
5. **JS preview** — `screen.synthetic` shows a legacy note instead of
   overlapping full-size tiles; the meta line says "legacy preset (no
   per-window positions)" instead of a fabricated source screen.
6. **`export_window_preset`** exports the upgraded document so exported
   legacy presets round-trip the strict file-import validation.

## 4. RULE 18 recheck (changed code)

- `layout_service.py`: `canonical_grid_payload` unchanged size (~20), data
  lists + comment; `default_grid_tree` +1 leaf.
- `bridge.py`: `_upgrade_preset_doc` ~24, `_grid_payload_from_doc` 12,
  `_legacy_window_entry` 5, `load_window_preset` 12 — 4–20 band, ≤2 params.
- `window-presets-actions.js`: pure `_presetResponseDocument` 11;
  `window-presets-preview.js`: `_previewMeta` 13, `_showPreview` tile branch
  guarded by `screen.synthetic`.

## 5. Verification (2026-09-18)

- pytest **308** (was 295): 14-window set parity; **live 14-window grid with
  a custom frame survives save→restart** (the regression test); unmigratable
  layout rejects with a reason (no default swap-in); `load_window_preset`
  returns the full document and leaves the session untouched; legacy upgrade
  (states dedup, unknown ids dropped, passthrough, rejects); export writes the
  upgraded document.
- node **100/100** (was 90): response-shape parsing (new envelope, raw-doc
  tolerance, old envelope → null, junk → null).
- gates: full pytest + node + `verify_quality.py --changed --allow-legacy`.
- live acceptance: saving a custom frame and restarting shows that exact
  frame (LogConsole: `🪟 Grid restored from session (14 windows)`); clicking a
  preset shows the preview and Apply restores it; cancelling the preview
  leaves the session untouched; legacy presets restore with the legacy note.
