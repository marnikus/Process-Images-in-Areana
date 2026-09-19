# Quality re-check — 2026-10-02 (Captcha Watcher isolation + UI bugfixes)

Snapshot of the RULE 16 gates after the round. Re-run the commands before
every push (RULE 16 §16.6, `current/CODE_VERIFICATION.md`).

| Gate | Command | Result |
|---|---|---|
| Python tests | `python -m pytest -q -n 4` | 1,393 passed · 1 skipped · 3 environmental fails that also fail on `main` in this sandbox (`test_qt_shim_fallback::test_qt_widgets_import_success_arc` needs PySide6, `test_cdp_client_stub::test_connect_failure_emits_error` expects the IPv4-only connect message, `test_verify_quality_tool::…warns_loudly` xdist flake — passes alone) |
| JS tests | `npm run test:js` | 142 pass · 0 fail (was 141; −5 continue-click probe cases, +6 new suites/cases) |
| Size/complexity gate | `python tools/verify_quality.py --js` | **PASSED** — 0 fails. New symbols all inside the hard limits: `CaptchaWatcher` 14 methods / <150 LOC after extracting `_Encounter`; `Boot` as an object literal (the IIFE form tripped `js-max_cc`); `Dialog.promptEdit` instead of a 5th parameter; `render._renderRows(listId, names, handlers)` |
| Slot contract | `tests/test_bridge_slots.py` | 134 frozen slots (127 + 6 Watcher solver + `restore_default_blocks`); packing `queue_scan` 10 + `queue_scan_folder` 2, `blocks_stack` 11, `watcher_solver` 6 |
| Coverage | `coverage run --branch --source=app -m pytest` | **85.64 % line / 81.32 % branch** (floor was 84.47 / 80.27) — new modules: `captcha_watcher/` 93–100 %, `watcher_solver.py` 94 %, `queue_scan_folder.py` 97 %, `action_blocks_defaults.py` 100 %, `url_queue.py` 97 % |
| Changed-file ratchet | `tools/verify_quality.py --changed --base origin/main --allow-legacy --coverage-ratchet` (the pre-push hook lane) | **PASSED** after the integrator re-record (`--record-baseline`, see below) |

## What changed in the numbers

* −5 production modules/files: `captcha/solver.py`, `captcha/api_client.py`,
  `captcha_js/continue_click.js` (+ `build_continue_js`), the auto branches of
  `captcha/service.py`; −2 test modules.
* +5 modules `app/services/captcha_watcher/`, +`app/ui/panels/watcher_solver.py`,
  +`app/ui/panels/queue_scan_folder.py`, +`app/core/action_blocks_defaults.py`,
  +`js/core/boot.js`, +`js/panels/url-list/listeners.js`.
* `requirements.txt`: `2captcha-python>=1.5.0` (optional at runtime — lazy
  import; the app boots without it and the Watcher reports `sdk_available=false`).
* `tools/mutmut_scopes.txt` scope `captcha` now covers `app/services/captcha_watcher`.

## Baseline re-record (integrator step, reviewed)

`tools/quality_baseline.json` was re-recorded with `--record-baseline` in this
round because the per-file ratchet ("no growth, even inside the limits")
would otherwise reject legitimate additions: `BlocksStackMixin` 10 → 11 slots
(`restore_default_blocks`), `UrlQueueMixin` 9 → 11 methods (`_commit_urls`,
`_emit_url_presets`), `WatcherCaptchaMixin` +2 LOC (`solver_follow` calls),
`AppState.from_dict` nesting 1 → 2 (folder normalisation), and the JS
helpers in `dialog.js`, `block-store.js`, `arena-presets/*.js`,
`action-blocks.js`, `arena-app*.js`. Every value is inside the RULE 16 hard
limits (full-mode gate 0 fails); the per-file coverage floors moved to the
fresh run (`captcha/service.py` 91.1 → 89.6 % after deleting the covered
auto-solve branch, `queue_scan.py` 57.0 → 52.2 % after moving its two
best-covered slots to `queue_scan_folder.py` at 97 %), the global floor rose.
Removed files (`captcha/solver.py`, `captcha/api_client.py`) dropped out of
the baseline.

### 2026-10-03 follow-up re-record (B6 — global-name contract)

Re-recorded once more for the B6 fix (`bugfix-verification.md` §B6): 14
panel modules + `sash-grid.js` each grew by exactly the 3-line
`window.X = X` export, `boot.js` gained `panel(name)` (+21 LOC, 1 function),
`arena-app.js` gained `_panel()` + `window.App = App` (+10 LOC, 1 function).
All 20 rejected deltas were `file_lines` / `func_count` NO-GROWTH entries;
no symbol crossed a hard limit (`--js` full lane 0 fails). Fresh coverage
85.65 % line / 81.33 % branch — the floor 85.64 / 81.32 is kept.

## Known debt carried (tracked in `docs/archive/2026-10-02-captcha-watcher-isolation/design.md` §7)

* `captcha_recording/` + Records window kept (F-1).
* `captcha/stats.py` `auto_*` counters no longer incremented (F-2).
