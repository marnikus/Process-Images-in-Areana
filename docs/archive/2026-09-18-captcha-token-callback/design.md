# Captcha auto-solve: "dialog still visible after token injection" — the missing widget callback

Date: 2026-09-18 (round 4, continues `2026-09-18-captcha-why-not-solving/`).

## 1. Report

Captcha window: auto-solve ON, key `1d51****27d4` stored, balance $4.69.
Stats: **4 detected, 0 auto-solved, 3 auto-failed, 0% success, 0 manual** —
last error: `dialog still visible after token injection`.
Job log (11:19–11:22): Submit Once → spinner 11:19:16→11:20:16 →
`Wait New Output: failed — Timeout after 180000ms` at 11:22:13 — and **no
captcha service lines inside the visible job-log range**.

## 2. Diagnosis

**Root cause of the auto-fail — the dialog never sees the solve.**
arena.ai wires reCAPTCHA through a random-named **global callback** on
`window`: the enterprise anchor iframe src ends with `&cb=<name>`
(verified in the saved page state:
`.../recaptcha/enterprise/anchor?...&size=invisible...&cb=t3pnrgbyrriv` —
the challenge dialog's anchor carries its own `cb=`). When a real user solves
the widget, the anchor calls `window[cb](token)` **in the parent page**;
arena's handler then closes the dialog and resumes the blocked request.

Our inject probe only sets the hidden `g-recaptcha-response` textarea
(React-safe setter + input/change events). That is *half* of what a real
solve does — **the callback is never invoked**, so arena's dialog can never
recognize the token, the 20 s verify-grace expires, and the solver reports
`not_accepted: dialog still visible after token injection`. Token cost paid,
dialog untouched.

**Why the job still failed (even though detection + solve ran): the wait
loop is blind to the dialog.** `CDPArenaController.wait_for_new_output`
polls only for the output image; the captcha settle points (submit boundary,
download boundary, bridge settle sites) fire *around* the wait, not inside
it. The job therefore burned the full 180 s generation wait with the dialog
open, timed out, and only *then* hit a settle point — which is also why the
`🛡️ Captcha detected` / `🤖 FLAG CAPTCHA_AUTO` lines appear **after** the
job-failure lines in the log (they exist — the wiring `CaptchaCtx(log=…)` →
`bridge._log` is correct — but outside the pasted range).

## 3. Design

**Fix 1 — invoke the widget's registered callback on injection.**
`inject.js`: after setting the textarea (dialog-scoped first, as today),
parse `cb=([A-Za-z0-9_$][\w$]*)` from the **dialog's** anchor iframe src and,
if `typeof window[cb] === "function"`, call `window[cb](token)` — exactly
what the real widget does. Result grows to
`{ok, scope, tag, len, cb, cbCalled, cbError}`.
The solver `_inject` now returns the result dict, logs it
(`token injected (scope=dialog, cb called=…)`), and refines the
not-accepted reason by callback status:

| cb status | Failure reason (visible in log + Captcha window) |
|---|---|
| found + called, dialog persisted | `dialog still visible after token injection (callback called — token likely rejected server-side)` |
| not found in dialog anchor | `dialog still visible after token injection (no callback in dialog anchor)` |

**Fix 2 — security-aware wait loop (the job completes in one pass).**
`wait_for_new_output`'s `check_fn` first passes through
`await self._security_gate()`: if `is_security_dialog_visible()` and the
controller carries a `security_settler` (async callable attribute set by the
caller before the wait, cleared after), it settles the dialog inline —
auto-solve via 2Captcha or manual wait — blocking until the dialog clears,
then resumes output polling. `single_job_runner.wait_for_output` installs
`security_settler = lambda: check_security(ctx)` (job-corr logs, stop
honoured by `check_security`'s stop closure; a stop-raise is absorbed by the
loop's `_poll_check` and picked up by `cancel_check` on the next iteration).
The dialog is thus detected within ~2 s (poll cadence) of appearing, and the
solve time counts against the generation budget. Attribute (not parameter):
`wait_for_new_output` already has 4 params — RULE 16 hard limit.

**Follow-up (documented, not implemented):** if
"callback called — token likely rejected server-side" persists, the token is
rejected by Google (e.g. IP mismatch for enterprise) — the next step is the
IP-matched task type `RecaptchaV2EnterpriseTask` (proxy) per 2captcha docs.

## 4. RULE 18 recheck (changed code)

- `inject.js`: 41 lines (probe file, self-contained).
- `solver.py`: module helpers `_cb_desc` (7 LOC) + `_reject_reason` (5 LOC);
  class methods `_inject` 12, `_inject_and_verify` 15 — CaptchaSolver class
  stays ≤150 LOC (was pushed to 157 by the first cut; helpers moved to module
  level to respect the hard gate, service.py is NOT in the size baseline).
- `cdp_arena.py`: +`_security_gate` (9 LOC, 1 param); `wait_for_new_output`
  +1 line (legacy file, in size baseline → gate downgrades to [LEGACY] warn;
  param count stays 4 — the settler travels as an attribute, not a param).
- `single_job_runner.py`: `wait_for_output` +5 lines (legacy baseline file).
- No new modules.

## 5. Verification (2026-09-18)

- pytest: **288 passed** (+1: not-accepted with callback called → reason says
  "callback called", log line `token injected (scope=dialog, cb=called abc123)`
  asserted; existing not-accepted test now also asserts the specific
  "no callback in dialog anchor" reason).
- node `npm run test:js`: **88/88** (+3 inject cases: cb found+called with
  token delivery asserted / cb missing → `cb:null` / cb throws → `cbError`
  captured, injection still ok). Inject harness gains a `window` stub param.
- RULE 16 (`verify_quality.py --changed --allow-legacy`): **0 code fails**
  (only the pre-existing coverage.json 29.3% threshold fails remain,
  documented in `2026-09-18-captcha-visual-await/design.md` §3).
