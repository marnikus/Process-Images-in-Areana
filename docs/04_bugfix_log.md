# 04 — Bug Fix Log

One row per reported bug: symptom → root cause (with the line that proves
it) → fix → how to verify.

---

## BUG 03.1 — URL window: cannot add new pages

**Symptom** Typing a URL and pressing *Add* does nothing.

**Root cause** three layers of silence:

```js
// url-list/actions.js
if (b && b.add_url) b.add_url(val, (res) => this._onAdd(input, val, res));  // slot missing -> no-op
_onAdd() { try { … } catch {} }                                            // rejection swallowed

// url-list.js
if (!addBtn || !input || !tableBody) return;   // #urlTableBody late -> Add never bound
```

Python `add_url` itself is correct; it rejects duplicates and non-http URLs,
but the reason never reached the user.

**Fix** `js/panels/url-list/add-url.js`
* binds via `BridgeCall.invoke` → direct slot, `invoke()` fallback, or a
  visible `❌ Action unavailable` message;
* client-side validation mirroring `_valid_new_url` (empty / scheme /
  malformed / duplicate) with inline red hint;
* busy state on the button; list refreshed from `get_arena_state` instead of
  trusting a signal.

**Verify** add a valid URL → row + `✅ URL added`. Add it twice → inline
"already in the list". Add `foo.com` → "must start with http:// or https://".

---

## BUG 03.2 / 03.3 — Action blocks disappeared, defaults not restorable

**Symptom** The Action Blocks window is empty; nothing brings the defaults
back. The image-processing chain is unreachable.

**Root cause** two independent defects:

```python
# app/ui/panels/blocks_stack.py
raw = bridge.config.get_state("action_blocks", None)
if raw is None:            return default_stack()
if isinstance(raw, list):  return load_stack_from_dicts(raw)   # [] -> [] forever
```

and `reset_action_blocks` exists as a slot but **no JS calls it** — plus the
panel renders into `#panel-action-blocks`, an id that does not exist
(markup ships `#winActionBlocks` / `#actionBlocksStack`).

**Fix**
* `app/ui/panels/blocks_defaults.py` — `load_blocks()` treats empty/corrupt
  state as "restore defaults"; `REQUIRED_BLOCK_IDS` (the image-processing
  chain) are re-inserted in canonical order; `restore_default_blocks(
  merge_missing)` is a first-class slot.
* `js/panels/action-blocks/block-defaults.js` — resolves the container with
  a fallback, renders an explicit empty state, and mounts **Restore
  defaults** + **Re-add missing** with a live "N required block(s) missing"
  hint.

**Verify** delete every block → empty state with the button → *Restore
defaults* → 16 blocks in canonical order. Restart the app → still there.

---

## BUG 03.4 — Browse folder button does not open a dialog

**Symptom** *Browse* does nothing; no window appears.

**Root cause**

```python
QFileDialog.getExistingDirectory(None, "Select image folder", start)
```

`parent=None` with a focused `QWebEngineView` can open the modal behind the
main window; when the PySide6 import failed, `qt_compat.QFileDialog` is
`None` and the slot returned `{"ok": false, "error": "No file dialog"}`,
which the JS only wrote to the log console.

**Fix**
* `app/ui/panels/folder_browse.py` — resolves a real parent
  (`activeWindow()` → visible top-level), then an ordered strategy chain
  native → `DontUseNativeDialog` → explicit error; typed paths share the
  same persistence path.
* `js/panels/folder-picker-browse.js` — busy state, inline status line next
  to the button (visible with the Log window closed), Enter on the path
  field as a keyboard-only fallback.

**Verify** click *Browse* → dialog in front. Cancel → "Cancelled". Type a
bad path + Enter → "Folder does not exist: …".

---

## BUG 03.5 — Many buttons do nothing / dialogs never open

**Symptom** Scattered dead controls across windows.

**Root cause** a single line:

```js
// arena-app.js
_PANEL_INITS.forEach(_initIfExists);
```

`ArenaPresets.init()` calls `this._actions.bindSettingsPresets()` with no
guard; when the part global is missing it throws, `forEach` unwinds, and
**every panel after it never initialises** — `ActionBlocksPanel` is the next
entry in the list. Add the 14 dead DOM ids (`docs/01` §2.1) and the missing
meta-object slots (§2.2) and whole windows go inert with no error anywhere.

**Fix**
* `js/core/panel-boot.js` — per-panel try/catch, `requires: [ids]` with
  bounded retry for late DOM, `PanelBoot.report()` diagnostics, boot summary
  in the log.
* `js/core/bridge-call.js` — direct slot → `invoke()` fallback → visible
  error; never a silent return.
* `app/ui/bridge_slots.py` — `REQUIRED_SLOTS` contract, `audit_slots()`
  startup banner, generic `invoke` declared in the Bridge class body.

**Verify** boot log shows `✅ N panels started` and `✅ Bridge contract OK`.
Break one panel on purpose → only that panel reports `failed`, the rest work.

---

## BUG 03.6 — Prompt window: save / restore / remove preset buttons gone

**Symptom** The prompt preset controls are missing or inert.

**Root cause** `arena-presets/actions.js` injects a preset bar into
`#winPrompt`:

```js
bar.innerHTML = `<input id="promptPresetName" …>
                 <button id="promptPresetSaveBtn" …>Save</button>
                 <select id="promptPresetSelect" …></select>`;
```

while `index.html` already ships `promptPresetNameInput`,
`promptPresetSaveBtn` and `promptPresetsList` inside `#winArenaPresets`.
Result: a **duplicate id** — `getElementById('promptPresetSaveBtn')` returns
the static button, which has no listener — and Restore/Remove exist only in
the injected copy, in a different window.

**Fix** `js/panels/arena-presets/prompt-presets.js` binds the static markup,
injects nothing, renders the list into `#promptPresetsList` with per-row
**Restore** / **Remove**, confirms removal through `Dialog.confirm`, and
routes all three actions through `BridgeCall`.

**Verify** Save → row appears. Restore → textarea filled, `input` event
fired. Remove → confirm → row gone. All three log a line.

---

## Cross-cutting fixes

| Change | Why |
|---|---|
| `BridgeCall` everywhere | a missing slot is now an error, not silence |
| `PanelBoot` fault isolation | one bad panel cannot disable the app |
| `requires: [...]` per panel | late-mounted DOM retried instead of unbound |
| Inline status next to controls | errors visible with the Log window closed |
| `bridge_slots.REQUIRED_SLOTS` | drift between JS and Python fails loudly at boot |
