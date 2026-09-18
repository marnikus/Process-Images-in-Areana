# Fix — provider aborts mid-solve; run flow needs the watcher's passive per-page principle

Date: 2026-09-18 · Status: implemented (see the Gates section appended below)

## Implementation outcome (measured after)

* Suite 481 passed (+18: monitor 8, solver liveness/rotation 6, wait_captcha_cleared 3, stamped_settle 2, wiring tripwires 1, minus refactors); quality gate `--changed --allow-legacy` PASS.
* Final numbers: `_poll_task` 29/CC 9 (legacy offender IMPROVED), `_dialog_liveness` 20/CC 6/1 param, `wait_captcha_cleared` 30/CC 10/4 params, `PageMonitor` class ~85 LOC/6 methods, `check_security` 19/CC 5, `Bridge._settle_captcha_at` 13 + `_settle_captcha_locked` 15 (guard split), `_run_image_job` 21/1 param.
* `monitor.py` 150 lines (leaf, one responsibility: SettleGuard + PageMonitor).
Evidence: user log 22:55–22:57 (`20260918-225545-KBJA`) — captcha detected at the
check-security boundary, CapMonster task created, 21 polls × 3 s (64.7 s), then
`dialog_gone_during_poll` → `auto_failed` → instant false "manual" (+15 m penalty).

## Reported

"Watcher detects it without a problem. Still one run web page does not catch the
captcha. It should do the same principle as watcher: check passively every 500 ms
per page (individual for each page). As it recognizes the captcha it calls the bot
solving provider. — Provider never solves the captcha now?"

## Root causes (verified in code)

1. **The provider DID start solving — then the solver killed its own task.**
   `_poll_task`'s H3 liveness check (`polls % 3 == 0`) aborts the paid task when
   `is_security_dialog_visible()` reads False once. `_dialog_visible` maps ANY probe
   exception to False ("fail closed"), and the site's dialog can legitimately close/
   reopen (challenge rotation — the report itself shows "recaptcha challenge expires
   in two minutes"). One glitch or one closed window at ~63 s ⇒ task abandoned,
   token never delivered (`dialog_gone_during_poll`), no retry (that reason is not
   in the retryable set).
2. **The manual fallback then lies.** `wait_captcha_cleared` returns True on a
   SINGLE not-visible probe AND on any exception (`except: return True`) — the same
   glitch/flicker becomes an instant "manual solved" + a 15 m penalty while the
   captcha is still on screen (`solve_total_s: 0.0` in the log).
3. **The run flow still samples boundaries + a 2 s in-wait gate** — not the watcher's
   passive recheck-every-tick principle. The watcher (500 ms per page, fail-open,
   never trusts one bad probe) is why it "detects it without a problem".

## Design

Watcher principle, ported to the run flow; provider task protected from one bad probe.

### 1. Solver: never trust one probe; confirm before aborting; retry on rotation

* `_dialog_state(plan) -> Optional[bool]` — tri-state: True/False, **None on probe
  error**. Errors never count as "gone" (the watcher's fail-open).
* `_dialog_liveness(plan) -> bool` — checks every `DIALOG_CHECK_EVERY_POLLS`-th poll
  AND every poll once a streak starts. False result increments
  `plan.dialog_gone_streak`; **two consecutive confirmed absences**
  (`DIALOG_GONE_CONFIRM_CHECKS = 2`, ≈6–9 s CapMonster / 10 s 2Captcha) abort as
  `dialog_gone_during_poll`; True or None resets the streak (logged when it turns
  back up). Flicker < the window keeps the same task alive.
* Rotation retries (`_retryable` extended, still capped by `MAX_SOLVE_ATTEMPTS=2`):
  `dialog_gone_during_poll` becomes retryable (a live dialog is verified by
  `_retry_with` before re-spending), and `token_stale:
  dialog_gone_before_token_injection` (token arrived during a closed window) becomes
  retryable the same way. A manual solve (dialog stays gone) still falls back to
  manual exactly as today.
* `_poll_task` net complexity DROPS (CC 10 → 9): the liveness decision moves whole
  into `_dialog_liveness`.

### 2. Run flow: per-page passive monitor (the watcher's twin, solver-calling)

NEW `app/services/captcha/monitor.py`:

* `PageMonitor` — per-page asyncio task, `PAGE_CHECK_INTERVAL_SEC = 0.5`, probing
  `is_security_dialog_visible` every tick; fail-open (probe errors counted, never
  acted on; self-terminates after 20 consecutive errors ≈ dead page/CDP — RULE 9).
* One settle per encounter: first visible tick calls `settle()` (→ provider); while
  the dialog stays visible no re-trigger; a cleared-then-visible-again dialog is a
  NEW encounter and re-triggers.
* `start_page_monitor(ctrl, settle, report)` / `stop_page_monitor(monitor)`; stored
  on the ctrl for defensive stops.
* `SettleGuard` — non-reentrant async guard keyed on the ctrl: while one encounter
  is being handled (solver running / manual wait), every other trigger (monitor,
  wait-loop settler, boundary check) no-ops instead of double-handling.
* Wiring: bridge single-run loop starts the monitor once per job (after the gates
  build) with the **stamped** settle (`stamped_settle(gates, ctrl)` in recovery —
  settle + revival stamp), stops it on the normal path, after the image loop, and
  in both batch exception handlers. Dispatcher: `_run_image_job` starts/stops a
  monitor around `run_blocks_for_image` (parallel pages each get their own —
  "individual for each page"); `check_security` gains the same SettleGuard.

### 3. Manual wait: cleared must STAY cleared

`wait_captcha_cleared`: the dialog must read not-visible continuously for
`CLEAR_HOLD_SEC = 3 s` before True; a visible-again or probe-glitch resets the
window; probe errors tolerated up to `MAX_PROBE_ERRORS = 10` then fail-open (dead
page must not hang the job). Stop still returns False immediately. This kills the
instant false "manual" + wrongful penalty.

## Measurements (targets)

| Unit | Now | Target |
|---|---|---|
| `_poll_task` (legacy at gate) | 29 LOC / CC 10 | ≤29 / **≤9** (improved) |
| `_dialog_liveness` (new) | — | ≤20 LOC / CC ≤5 / 1 param |
| `_dialog_state` (new) | — | ≤6 LOC / CC 2 |
| `_retryable` | 6 LOC / CC 4 | ≤9 / CC ≤6 |
| `wait_captcha_cleared` | 18 / CC 6 | ≤30 / CC ≤9 / 4 params |
| `PageMonitor` (new class) | — | ≤150 class-LOC, methods ≤10 |
| bridge `_settle_captcha_at` | 16 / CC 5 | ≤26 / CC ≤7 (guard added) |

Rejected designs: removing the dialog-gone abort entirely (burns spend after a
manual solve — keep it, just confirm it); making the monitor call the solver
directly (bypasses the `handle_captcha` choke point — RULE 9 surface); one shared
global monitor (watcher's lesson: cannot attribute a tab — per-page monitors only).

## Tests (RULE 8)

Solver: confirmation (one False ⇒ keeps polling; two ⇒ abort), flicker keeps the
same task and solves, probe errors never abort, rotation retry with a fresh task,
token-arrived-during-closed-window retry. Monitor: one settle per encounter,
re-arm after clear, fail-open on errors, guard blocks concurrent settle, stop.
`wait_captcha_cleared`: hold window, reset on re-visible, probe-error tolerance,
fail-open, stop. Wiring tripwires for bridge + dispatcher.
