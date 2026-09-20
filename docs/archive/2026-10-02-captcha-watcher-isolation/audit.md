# Audit — captcha solving chain + UI bug inventory (2026-10-02)

Scope: everything in the repo that *detects*, *solves*, *records* or *reacts to* a
captcha, and the five UI defects reported with the same release. Read-only
findings; the decisions are in `design.md`, the fix evidence in
`bugfix-verification.md`.

## 1. Who solved captchas before this round

| Layer | Module | Role (before) | LOC |
|---|---|---|---|
| browser | `app/browser/captcha_probes.py` + `captcha_js/{detect,visible,inject,continue_click}.js` | probe builders (detect kind/sitekey, on-screen gate, token inject, "Continue" click) | ~420 |
| services | `app/services/captcha/service.py` — `handle_captcha(CaptchaCtx)` | the pipeline choke point: detect → stats → **auto-solve when `enabled`** → manual wait → penalty | 420 |
| services | `app/services/captcha/solver.py` + `api_client.py` | hand-rolled 2Captcha HTTP client (`createTask`/`getTaskResult` polling, per-tab inflight dedup, identity gate, inject + verify grace, continue click) | ~740 |
| services | `app/services/captcha/{key_store,stats,signals,recovery}.py` | key file `config/2captcha.json` (0600, masked), counters, dataclasses, post-settle generation revival | ~600 |
| services | `app/services/captcha_recording/` (17 files) | bounded redacted DOM/network recordings per encounter + labels/cohorts | ~1,900 |
| services | `app/services/single_job_runner.py` (`check_security`, `_run_security_captcha`, `_settle_and_note`, revival hooks) + `cooldown_service.wait_captcha_cleared/note_captcha_event` | pipeline call sites | — |
| services | `app/services/watcher.py` + `watcher_pkg/` | **passive** observer: overlay + `job_ctrl.pause()/resume()` while a captcha/generation is on screen — never solves | ~600 |
| ui | `app/ui/panels/watcher_captcha.py` (`set_captcha_settings`, `get_captcha_status`, `get_captcha_stats`) + `js/panels/captcha.js` | Captcha window: key, **"Enable auto-solve"** checkbox, timeout, balance, stats | ~330 |
| ui | `app/ui/services/captcha_recordings_bridge.py` + `js/panels/captcha-recordings*.js` | Session Records window | ~900 |

Total ≈ 4,100 LOC of production code, 27 test modules referencing the chain
(`tests/test_captcha_*`, `tests/characterization/*` goldens with a `captcha`
trace, `tests/js/test_captcha.mjs` executing the exact probe strings).

### Findings

* **F1 — two solving mechanics, one flag.** Solving lived inside the job
  pipeline (`handle_captcha` → `svc.solver.solve`), gated by
  `CaptchaSettings.enabled`. The passive Watcher only paused. So "Watcher ON"
  and "auto-solve ON" were unrelated switches, and a paid 2Captcha task could
  start from *any* pipeline call site (CHECK_SECURITY block, submit/download
  boundaries, generation-wait cycles, dispatcher path).
* **F2 — the HTTP client duplicated the vendor SDK.** `api_client.py` +
  `solver.py` re-implemented what `2captcha-python` (`AsyncTwoCaptcha`)
  ships: submit, poll, error mapping, balance.
* **F3 — Qt-thread `asyncio.create_task`.** `set_captcha_settings` /
  `get_captcha_status` scheduled balance refreshes with
  `asyncio.create_task(...)` from the Qt thread (no running loop) — the call
  raised, was swallowed, and the balance never refreshed.
* **F4 — the probes are the verified asset.** `detect.js` / `inject.js`
  encode the 2026-09-18 research (badge-vs-challenge discrimination, two
  sitekeys, dialog-scoped `sitekey`, every-field inject + real callback
  chain). A "simplified" replacement (`document.querySelector('.g-recaptcha')`
  style) would report the always-present badge as a challenge on every
  arena.ai tab and pay for a task per tick. They are kept verbatim.
* **F5 — `recovery.py` is not captcha solving.** It re-submits a generation
  that died while the page was blocked (round 6 "revival generalize"). It
  stays.
* **F6 — recordings are observation, not solving.** They start at detection
  and end at resolution; with the pipeline reduced to wait-only they still
  capture every encounter (manual or Watcher-cleared). Kept for this round;
  removal is a separate decision (see `design.md` §7).

## 2. UI defects (same release)

| # | Symptom | Root cause found in code |
|---|---|---|
| B1 | URL window: "Add" fired twice / `URL already exists` toast, table handlers stacked after a state restore | facade `url-list.js` bound `urlAddBtn`/`urlInput`/`urlTableBody` itself with plain `addEventListener`; a second `init()` (restore) re-bound. Edit used native `prompt()` (unavailable in QtWebEngine). Preset slots `add_url_preset`/`remove_url_preset`/`set_last_url_preset` returned `None` → QWebChannel never fired the JS callback. |
| B2 | Action Blocks: stack shrank to 9 blocks (no CHECK_SECURITY / observe / verify), "Reset" flaky | `ActionBlocksStore.load()` called `bridge.get_action_blocks()` **synchronously** — QWebChannel returns `undefined` without a callback, so the store never received data; an empty persisted list (`[]` from a preset import / undo snapshot) was loaded by the forgiving loader as *required-only* (9 blocks); `resetToDefault` invoked `reset_action_blocks` twice (sync attempt + callback attempt). |
| B3 | Arena Presets window: Save / Export / Import / prompt-preset Save dead, list empty | `arena-presets/actions.js` **injected** a second prompt bar into `#winPrompt` and a second arena bar into `#winSettings` whose ids (`promptPresetSaveBtn`, `arenaPresetSaveBtn`, `arenaPresetExportBtn`, `arenaPresetImportBtn`) collided with the static Arena Presets window. `getElementById` bound the first copy in DOM order; the static window's controls were never bound and `render` targeted the injected containers. |
| B4 | Folder window: "Browse" did nothing on some machines | `pick_folder` did `self.state.folder["root_path"] = …`; legacy `arena.json` / presets can carry `"folder": null` or a bare path string → `TypeError` inside the slot → no reply, no log. Native `confirm()` for New-Batch scan. |
| B5 | Boot ordering: one throwing `init()` killed every panel after it; slot typos were silent | `initApp()` looped `_PANEL_INITS` without isolation; no central "slot missing" report. |

## 3. Test surface touched

* Removed with the old solver: `tests/test_captcha_solver.py`,
  `tests/test_captcha_api_client.py`, the solver-hook section of
  `tests/test_captcha_milestones.py`, the continue-click cases of
  `tests/js/test_captcha.mjs`.
* Rewritten: `tests/test_captcha_service.py` (wait-only contract).
* Added: `tests/test_captcha_watcher.py`, `tests/test_sdk_solver.py`,
  `tests/test_watcher_solver_slots.py`, `tests/test_action_blocks_defaults.py`,
  `tests/test_queue_scan_folder.py`, `tests/test_url_queue_bugfixes.py`,
  `tests/js/test_boot.mjs`, `tests/js/test_url_list_listeners.mjs`,
  `tests/js/test_arena_presets_actions.mjs`, block-store cases in
  `tests/js/test_action_blocks.mjs`.
* Slot-surface guard (`tests/test_bridge_slots.py`): 127 → 134 frozen slots
  (+6 Watcher solver, +1 `restore_default_blocks`); packing
  `queue_scan` 12 → 10 + `queue_scan_folder` 2, `blocks_stack` 10 → 11,
  `watcher_solver` 6.
