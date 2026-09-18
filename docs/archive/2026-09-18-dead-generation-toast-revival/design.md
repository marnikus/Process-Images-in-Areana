# Dead-generation toast revival — the layer after the captcha

**Date:** 2026-09-18
**Status:** design complete, implementation follows in the same session
**Evidence:** user live run 2026-09-18 15:24 (two tabs), after the pass-path round shipped

## 1. Problem

The captcha layer now passes cleanly (pass-path round verified in the same log:
`sitekey_source=dialog_iframe_k`, modal key used, token accepted, dialog gone,
`challenge.active=false`). Yet the job still dies one layer later, in BOTH tabs:

```
[15:24:01] 🤖 2Captcha solved tab 154FBF467AF2 in 46s (token accepted)
[15:24:01] ⏳ Generating Max spinner visible
[15:24:17] Wait failed: Page error: Something went wrong while generating
           the response. Please try again.
```

* Tab GSK1: solve finished, dialog closed, generation started, and **16 s later**
  the toast appeared → job failed instantly.
* Tab XYH2: the toast appeared at 60.9 s **while the captcha was still being
  solved** — the blocked generation request had already died server-side; the
  solve correctly aborted (`page_error`, task deleted, no penalty), and the job
  failed.

## 2. Root cause (verified in code)

The toast is the site's own **dead-request signature**: a generation request
held hostage by the captcha modal times out server-side (round-5 already proved
"the spinner stays alive through the ~60 s solve while the request is dead").
The site's remedy is in the toast itself: *"Please try again."* — a human presses
Send again. The app has exactly that behaviour: the bounded post-settle revival
(`app/services/captcha/recovery.py`, ONE resubmit per wait).

But the revival never gets consulted:

```
check_fn() → _poll_output_diag() → match_page_error hits "something went wrong"
          → raise PageErrorAbort → wait returns failed → job failed
          (_run_resume_gate is never reached)
```

Revival only triggers on *spinner loss matured 20 s* — the toast always kills the
wait first (tab GSK1) or the error-abort path runs instead of the gate (tab XYH2).

## 3. Is there another captcha mechanism? (the user's question)

No second captcha widget exists (the pass-path inventory stands: ONE modal gate
+ its escalation layer). What exists is a **consequence layer**: the request
blocked by the captcha is dead by the time the token is accepted. Passing the
path therefore requires, in order:

1. solve the modal (done — pass-path round);
2. survive the dead-request toast by doing what the site tells a human to do:
   resubmit once (this design);
3. keep the acceptance gate — only NEW output completes the job (unchanged).

## 4. Design (bounded, rule-conform)

### 4.1 `app/utils/page_errors.py` — dead-generation classification

* `DEAD_GENERATION_PATTERNS = (r"something\s+went\s+wrong\s+while\s+generating",)`
* `match_dead_generation(text) -> str` — non-empty when the matched page error is
  the dead-request toast (input = the `Page error: …` line). Pure leaf, no I/O.
* All other ERROR_PATTERNS (limits, quotas, trace ids…) stay terminal — they are
  NOT dead requests and must never be revived.

### 4.2 `app/browser/cdp_arena.py` — one conversion per wait

In `wait_for_new_output.check_fn`, catch `PageErrorAbort`:

* if `match_dead_generation(err)` AND a `resume_gate` is armed AND this wait has
  not converted yet → convert to a non-ready diag carrying
  `dead_generation_error`, re-baseline the error corpus (the lingering toast
  must not re-fire), mark the one-shot flag, fall through to the resume gate;
* otherwise re-raise — terminal failure exactly as today (RULE 4: honest broken).

The flag is reset at wait start. A toast that returns AFTER the one resubmit
raises again → honest FAILED. Browser layer stays services-free (gate rides as
an attribute, same protocol as `security_settler`).

### 4.3 `app/services/captcha/recovery.py` — toast = authoritative death proof

`_note_activity`: a diag carrying `dead_generation_error` marks the request dead
immediately (`spinner_seen=True`, death window matured) — the grace window exists
for the ambiguous spinner-loss case; the toast is unambiguous, so revival fires on
the same poll. Existing budget rules unchanged: ONE resubmit per wait, stop
honoured, re-attach + re-insert + Send.

### 4.4 `app/services/captcha/solver.py` — report honesty (observed bug)

Tab XYH2's report showed `"task_id": ""` with `"polls": 13` — the failure paths
of `_run_task` drop the task id (money-affecting traceability, RULE 22 spirit).
Fix: `SolvePlan.task_id` stamped at creation; `_failed` copies it to the outcome.

## 5. Behaviour matrix after the change

| Scenario | Before | After |
|---|---|---|
| Toast mid-wait, revival armed, budget left (tab XYH2/GSK1) | instant job FAILED | ONE resubmit, wait continues for new output |
| Toast returns after the one resubmit | FAILED | FAILED (flag spent → re-raise) — honest |
| Toast, no policy armed / gate missing | FAILED | FAILED (raise unchanged) |
| Limit/quota/trace-id error | FAILED | FAILED (not a dead-request pattern) |
| Wait succeeds without toast | completed | completed (path untouched) |
| Stop during wait | cancelled | cancelled (`_cancelled` unchanged) |

## 6. Test matrix (RULE 8)

1. `match_dead_generation` positive/negative/bounded (page_errors tests).
2. Recovery: `dead_generation_error` diag fires revival on the SAME poll
   (no grace wait); budget still once; ready diag never revived; cancel honoured.
3. Wait-loop conversion (controller-level fake): dead toast + armed gate →
   gate consulted, corpus re-baselined, one-shot; second toast re-raises;
   non-dead error re-raises even with gate armed; gate absent re-raises.
4. Solver: poll-failure outcomes carry the provider task id.
5. All existing suites stay green (equivalence gate for the raise path).

## 7. Compliance

* RULE 4 — empty vs broken: revival ≠ success; only output completes the job;
  exhausted budget fails loudly with the original error text.
* RULE 7 — stop honoured: conversion path re-checks nothing new; `maybe_resume`
  already consults `cancelled`; the wait loop's cancel_check unchanged.
* RULE 9 — fail-open: any exception in the conversion branch re-raises the
  original abort (never stalls, never fake-succeeds).
* RULE 16/18 — new functions ≤20 LOC, ≤3 params, CC ≤10; no class growth past
  fail lines; every new function gets a deletion-failing test.
* RULE 20 — no bypass: resubmitting the user's own prompt after the site's own
  "Please try again" is the normal user flow; no site control is evaded.

## 8. Measured at implementation end (same session)

| Gate | Result |
|---|---|
| `pytest tests -q --ignore=tests/integration` | **372 passed** (360 baseline + 12 new) |
| `npm run test:js` | **106 passed** (unchanged — probes not touched) |
| `tools/verify_quality.py --changed --allow-legacy` | **0 fails** |
| radon on touched files | only pre-existing `highlight_selector` C(13); all new fns A/B |
| New-function LOC | `_convert_dead_generation` 15, `_poll_diag_or_revive` 9, `match_dead_generation` 10, `wait_for_new_output` 29 (≤30) |
| Coverage line | 36.004% → **37.148% (+1.144pp)** — not decreased |
| Coverage branch | 26.580% → **27.683% (+1.103pp)** — not decreased |
| Changed-module coverage | page_errors.py 100%, recovery.py 90.9%, solver.py 87.4% |
| New functions with 0 hits | **0** |
