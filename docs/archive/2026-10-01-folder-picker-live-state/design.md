# Folder Picker "display nothing" — the pushed state never reached the panel

Owner report: *"it bring bug and folder picker display nothing now"*.
Date: 2026-10-01. Rules applied: 4, 8, 10, 16, 17, 18, 19.

## 1. Problem definition

The Folder Picker window (`#winFolder`) is the only panel that draws the folder
root **and** the scan counters (`#folderPathDisplay`, `#folderPathInput`,
`#folderStats`). After the app booted, nothing it showed ever changed again:

| owner sequence | Image Queue | Folder Picker (before the fix) |
|---|---|---|
| boot, saved folder `C:/imgs`, 2 images | 2 rows | `C:/imgs`, `2 images · 1 pending` ✔ |
| boot with no folder → Browse → Scan | rows appear | `C:/imgs`, **`0 images · 0 pending`** forever |
| Clear List / New Batch Scan | empties | keeps the **old** counters |
| workspace restore of another snapshot | new rows | keeps the **old** path |

Reproduced on the whole page (`tests/js/page_harness.mjs`, every `<script>` of
`index.html` in page order, fake QWebChannel):

```
fresh boot        : {"path":"No folder selected","input":"","stats":"…0 images…0 pending…"}
after Browse      : {"path":"C:/imgs","input":"C:/imgs","stats":"…0 images…0 pending…"}
after Scan push   : {"path":"C:/imgs","input":"C:/imgs","stats":"…0 images…0 pending…"}   ← queue has 2
after restore push: {"path":"C:/imgs","input":"C:/imgs","stats":"…0 images…0 pending…"}   ← state says D:/restored
```

So the panel is not blank — it is **frozen at whatever the boot pull delivered**,
which for a fresh profile is an empty path and `0 images`. That reads to the owner
as "displays nothing".

## 2. Root cause

One payload (`arena_to_js`), three hand-written lists of the panels that render
it — and the live one drifted (RULE 16.4 duplication):

| site | list | FolderPicker? |
|---|---|---|
| `js/arena-app.js::_restoreArenaPanels` (boot pull, `get_arena_state`) | UrlList, **FolderPicker**, ImageQueue, PromptEditor, ProgressPanel, SettingsPanel | yes |
| `js/panels/workspace.js::WS_LIVE_PANELS` (after a workspace restore) | UrlList, ImageQueue, ProgressPanel, SettingsPanel, PromptEditor, **FolderPicker** | yes |
| `js/arena-app/listeners.js::LIVE_STATE_PANELS` (every `arena_state_updated` push) | UrlList, ImageQueue, ProgressPanel | **no** |

`arena_state_updated` is how the app reports state after boot (I-39: every queue
mutation funnels into `commit_queue` → `_emit_arena_state`). A panel absent from
`LIVE_STATE_PANELS` therefore never hears about a scan, a clear, a new batch or a
restore — RULE 4 inverted: a real value was reported as "nothing".

Second, smaller bug found in the same file: `arena-app/listeners.js` ended with
`window.ArenaAppListeners = window.ArenaAppListeners;` — a no-op self-assignment
that grew the file past its frozen 193 lines and left `npm run test:js` red
(`195 !== 194` in `tests/js/test_live_debug_panel.mjs`).

## 3. Fix

1. `arena-app/listeners.js` (frozen at 193 lines, same-line edit only):
   `LIVE_STATE_PANELS: ['UrlList', 'FolderPicker', 'ImageQueue', 'ProgressPanel']`
   and the stray no-op line deleted (193 lines again).
2. `panels/folder-picker.js`: `_setDisplay` became `_showPath`, the ONE writer for
   the folder root — the read-only line always follows the state, the editable box
   follows too **unless it is `document.activeElement`**, so a debounced push can
   never eat what the owner is typing. Same guard `panels/watcher/render.js:68`
   already uses; no extra listener, no duplicated focus state.
   `restore()` keeps its two jobs (path + stats) and shrank by two lines.

PromptEditor and SettingsPanel stay **out** of the live list on purpose: they hold
inputs the owner types into for long periods, and a 250 ms-debounced push would
overwrite them mid-edit. FolderPicker can join because it guards its own box.

### Rejected

* **A shared constant for all three lists** — the three lists are not the same set
  (the live one is a deliberate subset); a shared constant would have to encode the
  "owner is typing here" exception anyway, and `listeners.js` may not grow a line.
* **`_focused` + `focus`/`blur` listeners** (the `url-list/interval.js` idiom) —
  same behaviour, but +2 listeners, +1 state field and +3 lines in a file whose
  baseline ratchet allows no growth; `document.activeElement` is the DOM's own
  truth and has in-repo precedent.
* **Rendering the stats from the Image Queue's own store** — would be a second
  reader of the same data (RULE 10).

## 4. Tests first (RULE 8 / RULE 16.6)

`tests/js/test_folder_picker_live_state.mjs` — 6 tests, whole page, real boot path,
written before the fix: **4 failed red**, then green.

| # | test | fails without |
|---|---|---|
| 1 | a pushed folder + scanned images reach the panel | the list entry |
| 2 | a restored folder replaces the stale path | the list entry |
| 3 | a push never eats what the owner is typing; read-only parts still update | the active-element guard |
| 4 | boot pull and live push render the panel identically (RULE 10) | the list entry |
| 5 | an emptied queue renders `0/0`, never stale counts (RULE 4) | — (regression guard) |
| 6 | an owner act writes the box it is not sitting in | the active-element guard |

Mutation-checked: removing `FolderPicker` from `LIVE_STATE_PANELS` → 4 fail;
removing `document.activeElement !== inp` → 2 fail (3 and 6). Registered in
`package.json` `test:js`.

## 5. Verification (commands + numbers)

| check | result |
|---|---|
| `npm run test:js` | **493 pass / 0 fail** (was 487 / 2 fail: the `.venv` ENOENT and the frozen `listeners.js` count) |
| `pytest tests -q -n 8` | 3226 passed, 8 failed — **the same 8 as before the change** (2 need PySide6, absent in this sandbox; 2 CDP-socket env; 2 stale expectations: `test_single_job_runner` 24 vs 20 handlers, `test_ui_wiring` main-window AST; 2 `test_verify_quality_tool` cases pass in isolation — xdist pollution) |
| `coverage run --branch --source=app -m pytest tests -q` (serial) | 3228 passed, 6 failed; **89.19 % line / 86.25 % branch** (floors 80 / 75) |
| `tools/verify_quality.py --changed-files <the 2 js files> --allow-legacy --js` | **PASSED — 0 fails** |
| `tools/js_metrics.js` | `folder-picker.js` 163 lines (= baseline), 30 funcs (= baseline), max func 14 LOC, CC 8, depth 3, params 3; `listeners.js` 194 ≤ 195 baseline |

`--changed` alone cannot gate here: the diff vs `origin/main` lists no *gated*
(app/…​.py) files, so the tool falls back to all 248 files and every stale
`max_cog: 0` baseline entry fails (documented in `docs/current/CODE_VERIFICATION.md`).

## 6. RULE 18 / 16 recheck

* RULE 18 — file 163 lines (ideal 150–300); every function 4–14 lines (ideal 4–20).
* RULE 16 — no growth on any ratcheted metric; no new function, no new params;
  CC 8 ≤ 10, depth 3 ≤ 4.
* RULE 19 order respected: nothing was split to reach a number — `restore` got
  *simpler* (one guard instead of two, one writer instead of two copies).
* RULE 17 — this archive doc + the I-39 row in `docs/current/SYSTEM_OF_RECORD.md`
  + the `docs/README.md` map line, same change.
