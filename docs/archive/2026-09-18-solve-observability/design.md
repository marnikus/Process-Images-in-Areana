# Round 8 — solve-pipeline observability + token evidence

## User asks (2026-09-18, 12:56 run)

1. More steps logged after captcha detect + solve attempt.
2. More solving-status info from the provider (2Captcha).
3. "Do we receive a real key from the API ever? Where is the evidence?"
   → track it in logs.
4. Split timing: time-to-TOKEN (provider) vs total solve time.
5. Failed-generation detection (screenshot: "Something went wrong while
   generating the response. Please try again. Trace ID: 484e8c47-14e3").

## Research findings

- Provider data available per poll but currently DROPPED: `taskId`
  (never logged), `errorCode`/`errorDescription` on `status=failed`
  (reason stays bare `task_failed`), the token itself (never evidenced).
  `ApiError.message` already carries the provider `errorCode` — the solver
  only reads `.reason`.
- "Solved in 71 s" conflates provider time + inject + verify. All three
  timestamps are measurable (`plan.start`, token arrival, verify end).
- The page gives up (~60 s: captcha at :44, error ~1 min later) BEFORE
  enterprise tokens arrive (61–101 s). So the token often lands on an
  already-dead page — the log must show this ordering, and one cheap
  pre-injection dialog probe answers "was the token even still needed".
- Fast-fail path verified end-to-end in code: `_poll_output_diag` →
  `match_page_error` → `PageErrorAbort` → `_reraise_abort` escapes the
  poll wrapper → `wait_for_new_output` returns `("failed", {"error": page
  text})`. Round 7's Trace-ID collector feeds the corpus — NOTHING more
  needed except a test on the new exact text. The 12:56 run predates
  round 7 (`87f9dda`): user must pull + restart the app.
- Tab-id mismatch in the pasted log (submit 59FA0C vs solved 154FBF) is
  a trimmed multi-tab paste, not a bug: both lines log `plan.tab_id`
  from the SAME plan object.
- Solver `stop` covers user-cancel/tab-abort only; a page error does not
  cancel an inflight poll (the solve runs inside `_security_gate` before
  the error check in the same poll). Restructuring that is risk > value:
  the token still arrives, inject is attempted, revival recovers.
  Documented limitation, not changed.

## Changes (`app/services/captcha/solver.py` only, + tests)

**S1. taskId in the submit line.** `🤖 2Captcha task <type> #<id> submitted
(tab …, key=****)` — provider job number, safe to log, helps tickets.

**S2. Poll heartbeat.** Every 30 s of `processing`:
`🤖 2Captcha task #<id> still processing (Ns elapsed)` (~2 lines per
enterprise solve). Helper `_maybe_heartbeat(plan, task_id, last)` —
no new branches in `_poll_task` (stays B).

**S3. Token evidence on arrival.** In `_run_task` after the poll:
`🤖 2Captcha task #<id> token received in Ns (len=1844 head=03AGdB25
tail=…xQ)`. `_token_fingerprint` logs length + head/tail ONLY — never
the token (RULE 20: `EMPTY` / `SUSPICIOUS len=N` flags for bad shapes).

**S4. Provider failure detail.** `status=failed` surfaces
`errorCode`/`errorDescription`; `ApiError` path surfaces `str(e)`
(the provider code). Reason PREFIXES unchanged (`task_failed`,
`no_credit`, … — existing assertions hold); detail rides the detail
slot into the log + `last_error`.

**S5. Pre-injection dialog probe.** `_note_preinject_state`: one
`is_security_dialog_visible()` read — "dialog still visible —
injecting" vs "dialog already gone (page moved on?) — injecting
anyway". Still injects (harmless, may matter); observability only.
Existing `visible_seq` fixtures gain one element where the test's
intent requires it (watch-close / never-close); sequences that rely
on the empty→False default are untouched.

**S6. Split solved line.** `SolvePlan.token_at` (defaulted field, no
signature change): `… solved tab X in 71s (token 68s, token accepted)`
— keeps the `token accepted` substring. `SolveOutcome` UNCHANGED
(no consumers for new fields — YAGNI/RULE 18).

**S7. Deletion log.** `_delete_task` gains the log callable (4 params):
`🤖 2Captcha task #<id> deleted (credit freed)` on success.

**S8. Fast-fail proof (tests only).** New screenshot text (Trace ID
`484e8c47-14e3`, a second real sample) + `_poll_check` abort-escape
test (`PageErrorAbort` re-raised, ordinary errors contained).

## Rejected alternatives

- Full token in logs: a credential-shaped secret — fingerprint only.
- Cancelling inflight polls on page errors: solve runs inside the
  security gate before the error check; rewiring risks the choke
  point for one task of cost. Revisit with data if billing bites.
- New `SolveOutcome` fields: zero consumers — logs only.

## RULE 18 recheck (design-time + as-built)

- Stateless helpers live at module level (file convention, like
  `_click_continue`/`_delete_task`): `_heartbeat`, `_note_preinject_state`,
  `_failed_detail`, `_token_fingerprint` (all A) plus `_verify_gone` moved
  out unchanged (B(6), zero instance state).
- As built: `_poll_task` B(9), class LOC under the 150 bar, quality gate
  0 fails. The first cut hit C(11) + class-LOC — fixed by moving the
  failure-detail read out of the loop (real split: transport cadence vs
  response interpretation), not by trimming.
- `SolvePlan` +1 defaulted field; `_delete_task` 4 params; no new Bridge
  methods; reason prefixes stable.

## Verification

- Extend `tests/test_captcha_solver.py`: heartbeat on slow poll;
  token fp + time-to-token logged; pre-inject gone-log; failed
  detail surfaced (`task_failed: …`); delete logged; split timing
  in the solved line; fixture updates for S5.
- Extend `tests/test_page_errors.py`: new screenshot text +
  `_poll_check` abort-escape fork.
- Full pytest + node + quality gate + radon (new code ≤ B).
- Live: one captcha run should read as a coherent story —
  submitted #id → heartbeat(s) → token received (fp) → inject →
  solved (split) — or end with the provider's own error text.
