# Quality re-check — 2026-10-02 (Captcha Watcher isolation + UI bugfixes)

Snapshot of the RULE 16 gates after the round. Re-run the commands before
every push (RULE 16 §16.6, `current/CODE_VERIFICATION.md`).

| Gate | Command | Result |
|---|---|---|
| Python tests | `python -m pytest -q -n 4` | 1,393 passed · 1 skipped · 3 environmental fails that also fail on `main` in this sandbox (`test_qt_shim_fallback::test_qt_widgets_import_success_arc` needs PySide6, `test_cdp_client_stub::test_connect_failure_emits_error` expects the IPv4-only connect message, `test_verify_quality_tool::…warns_loudly` xdist flake — passes alone) |
| JS tests | `npm run test:js` | 142 pass · 0 fail (was 141; −5 continue-click probe cases, +6 new suites/cases) |
| Size/complexity gate | `python tools/verify_quality.py --js` | **PASSED** — 0 fails. New symbols all inside the hard limits: `CaptchaWatcher` 14 methods / <150 LOC after extracting `_Encounter`; `Boot` as an object literal (the IIFE form tripped `js-max_cc`); `Dialog.promptEdit` instead of a 5th parameter; `render._renderRows(listId, names, handlers)` |
| Slot contract | `tests/test_bridge_slots.py` | 134 frozen slots (127 + 6 Watcher solver + `restore_default_blocks`); packing `queue_scan` 10 + `queue_scan_folder` 2, `blocks_stack` 11, `watcher_solver` 6 |
| Coverage | `coverage run --branch --source=app -m pytest` | not generated in this sandbox (gate warns, does not fail); new modules ship with dedicated suites: `captcha_watcher/*` (test_captcha_watcher 11, test_sdk_solver 5), `watcher_solver.py` (7), `action_blocks_defaults.py` (8), `queue_scan_folder.py` (8), URL queue (4) |

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

## Known debt carried (tracked in `docs/archive/2026-10-02-captcha-watcher-isolation/design.md` §7)

* `captcha_recording/` + Records window kept (F-1).
* `captcha/stats.py` `auto_*` counters no longer incremented (F-2).
* Coverage baseline (`tools/quality_baseline.json`) still lists the removed
  files; `verify_quality.py` ignores missing baseline entries, re-record with
  `--record-baseline` in the next integrator pass.
