# Grid layout persistence fix + 2Captcha API debug logging

Date: 2026-09-18 (round 5).

## 1. Reports

1. "still detect new captchas but not solving it autofailed — let get logs of
   what failed on the API solver side for debugging?"
   → Note: the 11:28 run had **no** captcha (all 4 security blocks passed in
   <1 s, all 4 jobs completed); the 4/0/3 stats were STALE (persisted from the
   11:19 run). But the solver API side is still under-logged for real failures.
2. "gride do not save the last presetting any more on close app. after restart
   it do not keep last changes of grid settings."

## 2. Diagnosis

**Grid persistence — two compounding defects:**

a) **Close-time flush is fire-and-forget.** `MainWindow.closeEvent` schedules
   `runJavaScript("SashGrid.flushPersistence()")` and immediately calls
   `super().closeEvent(event)` — the window (and the WebChannel) is destroyed
   before the flush's `save_grid_layout`/`save_window_states` calls can round-trip.
   The final layout state can never reach `session.json` on the close path.

b) **Startup restore race.** On boot the grid renders the **localStorage**
   tree first (freshest), then `_loadFromBackend()` asynchronously restores
   `session.json`. If the last close-flush was lost (a), the backend copy is
   STALE — and it overwrites the fresher in-memory tree on boot. Every restart
   regresses to the last backend save. Additionally, any `_save()` that runs
   before the restore callback lands (first user interaction after boot)
   writes the pre-restore tree to the backend, cementing the stale state.

Verified against the user's committed `config/session.json`: `grid_layout` is
a complete v4 tree with `sizes` (validator accepts it: `canonical_grid_payload`
OK), `window_states` present — i.e. mid-session saves DO reach disk
(`_resizeUp` → `_save()` → `save_grid_layout` on every drag commit, confirmed
by the user's "📏 Grid resized" log lines), and no "Grid layout rejected"
lines appear in their log. The loss is at the close/restore boundary.

**API solver logging** — createTask/poll currently log only coarse lines
(`task submitted`, `poll ended: {reason}`); the raw 2Captcha error
(errorId + message), task id, sitekey, and token arrival are invisible.

## 3. Design

**Grid:**
1. `closeEvent`: synchronous flush — `runJavaScript(script, onDone)` with a
   `QEventLoop` + 1.5 s `QTimer` timeout, so the WebChannel round-trip of the
   final `save_grid_layout`/`save_window_states` completes before teardown.
2. `sash-grid`: restore guard — `_restorePending` set in `init()`, cleared by
   `_finishRestore()` when the backend grid callback lands (or a 3 s timeout
   safety). While pending, `_save()` still writes localStorage but defers the
   bridge push (`_saveQueued`); `_finishRestore` flushes the queued save after
   the authoritative tree is in place. No state change, ~15 LOC.
3. Hardening: `save_grid_layout`/`get_grid_layout` wrap
   `canonical_grid_payload` in try/except (a validator exception must never
   cross the WebChannel into the JS catch → silent local-only fallback).

**2Captcha API debug logging** (visible in app log, never the key):
- createTask: task type + sitekey tail (last 6) + url host + **task id**.
- poll: first status, every status change, ready → "token received (…)…tail";
  failure → full `ApiError` (`reason (errorId=N): message`).
- Helper `_api_line(plan, …)` keeps `_poll_task`/`_create_task` inside RULE 18.

**Captcha window:** add a **Reset** title-bar action (clears stats +
last_error + re-checks balance) so stale cumulative stats (the source of the
"still failing" misread) can be wiped before a fresh test run.

## 4. RULE 18 recheck (2026-09-18)

- `solver.py`: poll loop moved to module level (`_poll_task_loop` 22 LOC,
  CC 10, 4 params; `_one_poll` 8 LOC; `_ready_token` 3 LOC) — CaptchaSolver
  class back under the 150-LOC hard gate; `_create_task` 15, `_poll_task`
  2 (delegation).
- `main_window.py`: +`_flush_sash_grid` (12 LOC, 1 param) — file in size
  baseline (legacy warns only).
- `bridge.py`: `reset_captcha_stats` slot (10 LOC); grid slots hardened
  (+try/except, legacy baseline file).
- `sash-grid*.js`: restore guard ~12 LOC across two files; `captcha.js`
  +`resetStats` (13 LOC).

## 5. Verification (2026-09-18)

- pytest: **289 passed** (+1 stats reset test; solver tests now assert the
  API trace lines: `createTask OK → task 101 … sitekey=…`, `token received
  (task 101, …)`, `getTaskResult FAILED (task …): no_credit (errorId=3)`).
- node `npm run test:js`: **88/88** (sash-grid JS is DOM-bound, not in the
  node suite — guard verified by review; `node --check` clean on all
  changed UI files).
- RULE 16: **0 code fails** (only the pre-existing coverage.json 29.3%
  threshold remains, documented in `2026-09-18-captcha-visual-await/design.md` §3).
- Grid fix is behavior-preserving: `_save()`/`_finishRestore()` are idempotent
  (timeout + callback both call it; double-restore no-ops).
