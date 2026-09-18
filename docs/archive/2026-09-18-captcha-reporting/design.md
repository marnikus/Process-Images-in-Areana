# Round 10 — structured captcha reporting (`CAPTCHA_SOLVE` + `CAPTCHA_JOB`)

## Goal (user spec 01–05)

One machine-readable JSON line per captcha encounter (detection → solve
lifecycle → edge cases) plus one join line per encounter at job end
(job outcome + page error). Correlate by `eid` (8-hex encounter id).

## Schema

`🧾 CAPTCHA_SOLVE {v:1, eid, tab, source, kind, url, dom, sitekey(FULL —
public page data), invisible, ts(ISO UTC at detect), detect_to_solve_s,
task_type("" when no task), task_id, polls, poll_interval_s,
token: null|{at_s(detect→token), fp}, dialog_at_token(""/visible/gone),
inject("" or "scope=.. fields=.. cb=.."),
page_error: null|{at_s(detect→error), text},
status, reason, method, penalty_s(0|configured), solve_total_s}`

`🧾 CAPTCHA_JOB {v:1, eid, corr, tab, image, job: completed|failed,
error(trunc 200), page_error("" or text)}`

## Data flow (each datum emitted where it is known)

- **detect.js**: +`dom` label (`dialog|page` + `recaptcha-iframe|image|
  no-widget`, ~2 lines, semantic per RULE 21). `CaptchaSignal.dom` +
  `from_result` passthrough.
- **solver**: `SolvePlan` +`polls, token_fp, dialog_at_token, inject,
  page_error_at, page_error`; `SolveOutcome` +`polls, token_sec,
  token_fp, dialog_at_token, inject, page_error_at_s, page_error`
  (all defaulted — every construction site uses keywords).
  `_failed(reason, detail, plan=None)` fills from plan when present;
  `_solved` fills directly; `_poll_task` counts rounds at loop top;
  `_note_page_error` stamps plan on hit; `_note_preinject_state`
  takes `plan` (was `ctrl`) and stamps `dialog_at_token`.
  (Round-8 "no outcome fields" reversed: the report IS the consumer.)
- **service**: `_new_encounter(ctx, signal)` → rep dict (eid, stamps);
  `_try_auto(..., rep)` fills attempt fields, emits on solved;
  `_manual_wait(..., rep)` fills resolution, always emits once
  (solved/manual/stopped all emit — edge data, never silent).
  Penalty derived: `status∈{solved,manual}` → configured
  `cooldown_captcha_penalty_seconds` (fail-open, `DEFAULT_PENALTY_SECONDS`
  fallback — `app/core/cooldown.py` is stdlib-only, top import safe).
- **stash**: `_stash_encounter` appends `{eid, tab}` to
  `ctrl._captcha_reports` (fail-open). Runner `run_blocks_for_image`:
  clear at start (crashed-job entries must not leak across images on a
  reused ctrl) → drain + emit `CAPTCHA_JOB` per entry at end
  (has failed/error/corr/img — the exact funnel).
- Metrics (05): per-event durations in the report; aggregates stay in
  `CaptchaStatsStore` + Captcha window (existing, no duplication).

## Best practices (external)

2Captcha v2 API offers `reportCorrect`/`reportIncorrect`: report back
when the target site declines a token; they analyze workers and refund
([1](https://2captcha.com/api-docs/report-incorrect)). Our
`not_accepted`+cb-called case is exactly that signal. FOLLOW-UP ONLY —
money-affecting, needs explicit user approval; this round builds the
evidence lines it would key on.

## Rejected alternatives

- Single line at job end only: loses prompt mid-run visibility; crash
  loses all encounter data.
- `job_outcome` inside CAPTCHA_SOLVE: unknown at encounter end —
  honest two-line join instead.
- Full token in report: RULE 20 — fingerprint only (round 8).

## RULE 18 recheck (design-time)

- service: 5 helpers (`_new_encounter`, `_finish_auto`,
  `_finish_resolution`, `_emit_report`, `_stash_encounter`), each ≤4
  params / ≤ ~15 lines; `handle_captcha` grows ~4 lines.
- solver: 2 plan/outcome field groups (data, no logic); `_failed` +1
  defaulted param (CC 3); `_note_preinject_state` signature
  ctrl→plan (same arity).
- runner: 2 helpers (`_reset/_emit_captcha_job_lines`), ≤4 params.
- detect.js +2 lines; signals +2 lines. No new Bridge methods.

## Verification

- pytest: signals dom passthrough; solver outcome fields (polls,
  fp, dialog, inject, page_error_*); service report JSON parsed from
  bridge logs (auto/manual/unsolvable: eid, full sitekey, task data,
  penalty 900, status); runner emit helper with stub ctx
  (drain-once, page_error split, corr tag); fixtures for the
  `rep` threading.
- node: detect.js `dom` asserts (dialog-iframe / page-iframe / image /
  none) on the real file.
- Full pytest + node + quality gate + radon (new code ≤ B).
- Live: one captcha run must print exactly one SOLVE + one JOB line
  with matching eid.
