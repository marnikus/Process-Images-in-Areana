# 01 — Audit Report

Repository: `marnikus/Process-Images-in-Areana` (branch `main`)
Scope: captcha architecture + the six reported UI regressions
Method: static cross-check of the QWebChannel contract (JS ⇄ Python) and of
the DOM id contract (JS ⇄ `index.html`), plus a read of every call site that
reaches the captcha package.

---

## 1. What the app is

PySide6 shell hosting a `QWebEngineView`. The whole UI is
`app/ui/web/index.html` + ~90 JS modules, talking to Python through one
`QObject` (`app/ui/bridge.py`) over QWebChannel. Python is split into
`core/` (models, action blocks), `browser/` (CDP), `services/` (runner,
watcher, captcha, cooldown), `ui/panels/*` (bridge mix-ins).

Size signals that matter for RULE 18:

| File | Bytes | Note |
|---|---|---|
| `app/ui/web/index.html` | 55 835 | single page, 224 ids |
| `app/core/action_blocks.py` | 31 513 | block catalog + defaults |
| `app/services/single_job_runner.py` | 32 586 | full chain |
| `app/services/captcha/solver.py` | 28 604 | hand-rolled 2captcha protocol |
| `app/services/cooldown_service.py` | 26 729 | captcha penalties |

## 2. The reproducible defect: two broken contracts

### 2.1 DOM id contract — 14 dead ids

Every `getElementById()` in `app/ui/web/js/**` was compared against the ids
present in `index.html`. 14 ids are referenced by JS and **do not exist**:

| Missing id | Referenced by | User-visible effect |
|---|---|---|
| `promptPresetName`, `promptPresetSelect` | `arena-presets/actions.js`, `render.js` | prompt preset Save/Restore/Remove dead |
| `arenaPresetBar`, `arenaPresetChips`, `arenaPresetList`, `arenaPresetName`, `arenaPresetImportFile` | `arena-presets/*` | whole preset bar dead |
| `panel-action-blocks` | `action-blocks.js`, `block-config.js` | block stack never renders |
| `pauseCornerOverlay`, `pauseCornerReason` | `block-status.js`, `block-ui.js` | pause indicator missing |
| `settingsSavePresetBtn` | `arena-presets/actions.js` | settings preset save missing |
| `highlightOverlay` | `highlight.js` | highlight rect never drawn |
| `diagnoseChromeBtn` | `cdp.js` | diagnose button dead |
| `sashMinDock` | `sash-grid-windows/menus.js` | minimised windows unreachable |

`index.html` actually ships `promptPresetNameInput`, `promptPresetSaveBtn`,
`promptPresetsList`, `arenaPresetNameInput`, `arenaPresetSaveBtn`,
`arenaPresetsList`, `arenaPresetFileInput`, `winActionBlocks`,
`actionBlocksStack`. The JS was refactored, the markup was not.

Worse, `bindPromptPresets()` *injects* a second bar into `#winPrompt`
containing a **duplicate `promptPresetSaveBtn` id**. `getElementById`
returns the static, unbound button — the user clicks the one that has no
listener.

### 2.2 QWebChannel slot contract

All JS-facing slots were moved into plain mix-ins
(`UrlQueueMixin`, `QueueScanMixin`, `BlocksStackMixin`, …). PySide6 builds
the QMetaObject from the namespace of the `QObject` subclass, so a `@Slot`
that exists only on a non-QObject base can be absent from the meta-object
and therefore never reach JS. The JS side hides it:

```js
if (b && b.add_url) b.add_url(val, cb);      // slot missing -> nothing at all
if (!App.bridge?.pick_folder) return;        // no dialog, no error, no log
```

That is the mechanism behind "many buttons do nothing".

## 3. Findings

| ID | Sev | Area | Finding |
|---|---|---|---|
| F-01 | P0 | UI | 14 dead DOM ids (§2.1) |
| F-02 | P0 | UI boot | `_PANEL_INITS.forEach(_initIfExists)` has no try/catch — one throwing `init()` kills every later panel |
| F-03 | P0 | UI boot | `ArenaPresets.init()` calls `this._actions.bindSettingsPresets()` unguarded → throws → triggers F-02 → `ActionBlocksPanel` never starts |
| F-04 | P0 | presets | duplicate `promptPresetSaveBtn`; Load/Delete only exist in injected markup |
| F-05 | P0 | blocks | `get_action_blocks()` maps a persisted `[]` to an empty stack; `reset_action_blocks` exists in Python but no UI calls it → blocks gone, unrestorable |
| F-06 | P0 | bridge | mix-in slots may be missing from the meta-object; JS no-ops silently (§2.2) |
| F-07 | P1 | folder | `QFileDialog.getExistingDirectory(None, …)` — parentless modal, `QFileDialog is None` path returns an error only to the log |
| F-08 | P1 | UI | silent-failure idiom (`catch {}`, `?.` guards) across ~40 call sites |
| F-09 | P0 | captcha | solving reachable from the whole chain: `single_job_runner` (`CHECK_SECURITY`, `arm_resume`/`clear_resume`/`note_settle`), `cooldown_service`, `page_pool`, `captcha_recording/*` — not watcher-scoped |
| F-10 | P1 | captcha | `api_client.py` + `solver.py` re-implement the 2captcha protocol (~1 100 LOC) instead of the official SDK |
| F-11 | P2 | quality | `UrlList.init()` early-returns when `#urlTableBody` is absent, unbinding Add for the session |

## 4. Captcha reach (F-09 detail)

Modules that currently reference captcha state or solving outside the
watcher: `single_job_runner.py`, `cooldown_service.py`, `cooldown.py`,
`page_pool.py`, `page_status.py`, `site_adapter.py`, `dom_highlight.py`,
`action_blocks.py` (`CHECK_SECURITY`), `recording/*`,
`captcha_recording/*`, `ui/panels/watcher_captcha.py`, `ui/main_window.py`.

Effect: turning the Watcher off does **not** stop captcha work; recovery
timers, cooldown penalties and the `CHECK_SECURITY` block keep running.

## 5. Conclusion

All six reported bugs reduce to three structural causes:

1. **Contract drift** — JS refactored away from the markup and from the slot
   surface, with no check that the two sides still agree.
2. **Fail-silent by default** — guards that return instead of reporting.
3. **No fault isolation at boot** — one panel throwing disables the rest.

The fix set therefore adds two *contracts with self-checks*
(`bridge_slots.audit_slots`, `PanelBoot.report`) rather than only patching
the six symptoms.
