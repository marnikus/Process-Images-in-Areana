# Design — Captcha Watcher isolation (2026-10-02)

## 1. Contract (the one sentence)

**The job pipeline never solves a captcha. The Captcha Watcher is the only
solver, it uses only the official 2Captcha SDK, and it runs only while the
Watcher is ON.**

* Watcher **ON** → the app scans its own pages every 4 s and solves visible
  reCAPTCHA challenges through `twocaptcha.AsyncTwoCaptcha`
  (pip `2captcha-python`), max 2 paid attempts per challenge per tab.
* Watcher **OFF** → the app only processes images. A captcha is the user's
  business: the job pauses (overlay + red pool row) until the dialog is gone.
* Either way the pipeline behaves identically: **detect → mark waiting →
  wait until cleared → cooldown penalty**. It cannot tell who cleared the
  dialog and does not need to (`SolveOutcome.method` is `watcher` when the
  loop was running, `manual` otherwise — a label, not a branch).

## 2. Architecture

```
Watcher window / Captcha window ──start_watcher/stop_watcher──┐
                                                             ▼
app/ui/panels/watcher_captcha.py  (passive observer: overlay + pause)  ── solver_follow(enabled) ──┐
app/ui/panels/watcher_solver.py   (WatcherSolverMixin, 6 slots)  ◄────────────────────────────────┘
        │  tabs = page-pool pages (app-owned only, RULE 20)
        │  evaluate = pool client .evaluate(js) per tab
        │  solver_factory = SdkSolver(key from config/2captcha.json)
        ▼
app/services/captcha_watcher/
   watcher.py    CaptchaWatcher.run_forever() on the bridge bg loop (schedule_coro)
                 tick: detect.js on every tab → solvable? → SdkSolver.solve → inject.js
   sdk_solver.py SdkSolver — AsyncTwoCaptcha.recaptcha(sitekey,url,enterprise,invisible) / balance()
   probes.py     detect_js()/inject_js(token,sitekey) → app/browser/captcha_probes builders (verified JS)
   signals.py    CaptchaSignal / SolveResult / WatcherStatus (pure data)

Job pipeline (unchanged call sites) → app/services/captcha/service.py handle_captcha()
   detect → stats → overlay("Captcha Watcher is solving it" | "solve in Chrome — or turn the Watcher ON")
   → cooldown_service.wait_captcha_cleared → penalty → CAPTCHA_SOLVE report (task fields empty)
```

Guards in the loop: `EVAL_TIMEOUT_SEC = 8` per page evaluation (a hung tab
cannot stall the loop), `MAX_SOLVE_ATTEMPTS = 2` per tab per encounter
(budget resets when the challenge disappears), one solve at a time
(sequential, observable), every failure fails open with a log line and a
`last_error` in the status payload. Tokens are counted, never logged; the
key never crosses the WebChannel unmasked (RULE 20).

## 3. Slots (frozen surface +7)

| Slot | Mixin | Reply |
|---|---|---|
| `watcher_start()` | `WatcherSolverMixin` | `{ok, running}` — `{ok:false, error:"no api key"}` when no key |
| `watcher_stop()` | | `{ok, running:false}` |
| `watcher_status()` | | `WatcherStatus` dict (`running, has_key, sdk_available, tabs_seen, ticks, solved_total, failed_total, solving_tab, last_error, balance…`) |
| `set_captcha_api_key(key)` | | `{ok, has_key, masked_key}`; `""` clears; `<16` chars rejected |
| `get_captcha_api_key()` | | `{ok, has_key, masked_key}` |
| `captcha_balance()` | | `{ok, pending:true}` — result lands in `watcher_status().balance` + log |
| `restore_default_blocks()` | `BlocksStackMixin` | `{ok, count, blocks}` (bugfix, see `bugfix-verification.md`) |

`start_watcher` / `stop_watcher` / `set_watcher_config` / `get_watcher_config`
(boot with Watcher ON) call `solver_follow` so **one switch** controls both
the passive observer and the solver. The legacy `set_captcha_settings` /
`get_captcha_status` / `get_captcha_stats` keep working (same key file);
their `enabled` flag is inert and always reported `false`.

Signal: `captcha_watcher_status(str)` → `CaptchaPanel.onStatusUpdate`.

## 4. Storage

`config/2captcha.json` — single key file, owned by
`app.services.captcha.key_store.CaptchaKeyStore` (0600 best effort, atomic
write). Shape stays `{enabled:false, api_key, solve_timeout_sec}`; the Watcher
reads `api_key` + `solve_timeout_sec`. No new files.

## 5. Removed

* `app/services/captcha/solver.py`, `app/services/captcha/api_client.py`
  (hand-rolled 2Captcha client + in-pipeline solver), `CaptchaService.solver /
  auto_enabled / refresh_balance`, the auto branches of `_resolve_captcha`
  (`_try_auto`, `_finish_auto`).
* `app/browser/captcha_js/continue_click.js` + `build_continue_js` (only the
  old solver clicked "Continue").
* Captcha window: "Enable auto-solve" checkbox + solve-timeout field.
* Tests of the removed code (`test_captcha_solver.py`, `test_captcha_api_client.py`,
  solver-hook milestones, continue-click JS cases).

## 6. Kept on purpose (deviations from the first draft of this design)

The supplied draft listed the whole `app/services/captcha/` package,
`captcha_recording/`, `captcha_probes.py` and the Records window as
"REMOVED". This round keeps them, for reasons that are about correctness,
not convenience:

| Kept | Why |
|---|---|
| `captcha_js/detect.js`, `inject.js`, `visible.js` + `captcha_probes.py` | They are the *verified* page contract (badge vs challenge, dialog-scoped sitekey, every-field inject + real callback chain). The draft's simplified probes would false-positive on the always-present `.grecaptcha-badge` and pay for a task per tick. The Watcher's `probes.py` delegates to the same builders so there is one source. |
| `app/services/captcha/service.py` (`handle_captcha`, wait-only) | The pipeline still needs detect → pause → penalty → `CAPTCHA_SOLVE`/`CAPTCHA_JOB` reporting. Cutting the solver out of it is the isolation; deleting the choke point would re-scatter that logic over five call sites. |
| `key_store.py`, `stats.py`, `signals.py` | Key file owner (shared with the Watcher), encounter counters shown in the Captcha window, report dataclasses. |
| `recovery.py` | Dead-generation revival — independent of captcha solving (round 6). |
| `captcha_recording/` + Records window + `captcha_recordings_bridge.py` | Evidence capture around an encounter; still meaningful with a wait-only pipeline. Removing ≈2,800 LOC + 13 test modules of observation code is a separate decision — tracked as follow-up F-1 below. |
| Passive `WatcherService` (`watcher.py`, `watcher_pkg/`) | The overlay/pause behaviour the Watcher window has always had; the solver composes with it. |

Other integration deviations: the solver slots live in a **second** mixin
(`watcher_solver.py`) because RULE 16 caps a class at 15 methods and
`WatcherCaptchaMixin` already has 10; the loop is scheduled with the
existing `run_state.schedule_coro` (bridge bg loop) instead of a private
`_run_async`; tabs come from the page pool snapshot (only pages the app
attached to), never from a raw `list_tabs` of the whole browser.

## 7. Follow-ups

* **F-1** decide the fate of `captcha_recording/` + the Records window (keep
  as evidence tool, or remove with its 13 test modules + `tools/analyze_captcha_recording.py`).
* **F-2** `stats.py` still has `auto_solved/auto_failed` counters that nothing
  increments; fold Watcher counters into it or drop the fields.
* **F-3** optional: let the Watcher also clear the passive watcher overlay on a
  successful inject (today the pipeline's own poll notices the dialog is gone
  within one cooldown tick).

## 8. Verification

* `pytest -n 4`: 1,393 passed, 1 skipped, 3 environmental failures that fail on
  `main` too (PySide6 shim import arc, CDP IPv6 connect message, none captcha-related).
* `npm run test:js`: 142 pass / 0 fail.
* `tools/verify_quality.py --js`: 0 fails (all new symbols within RULE 16 hard
  limits; JS lane clean); changed-file ratchet lane passes after the reviewed
  `--record-baseline` (why: `docs/current/QUALITY_RECHECK.md`); coverage
  85.64 % line / 81.32 % branch (floor was 84.47 / 80.27).
* Real SDK contract checked against `2captcha-python 2.1.1`:
  `AsyncTwoCaptcha(apiKey, defaultTimeout, recaptchaTimeout, pollingInterval)`,
  `await recaptcha(sitekey=, url=, version='v2', enterprise=, invisible=)` →
  `{'captchaId', 'code'}`, `await balance()` → float; exceptions
  `ApiException/NetworkException/TimeoutException/ValidationException` all map
  to `SolveResult(ok=False, error=…)`.
