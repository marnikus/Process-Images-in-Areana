# S2 — captcha scope predicate (landed 2026-09-21)

**Plan step:** design.md §9 S2 · **Adaptation notes vs the plan's quotes:** this tree is newer
than the plan's base (2026-10-02 watcher isolation landed): `_manual_wait` already takes the
`reason`, `wait_captcha_cleared(ctrl, stop, timeout_sec, log)` is the real 4-arg wait, and
`CaptchaKeyStore` exposes `load().api_key` (no `has_key()`). The decisions are unchanged.

## Production

* new `app/services/captcha/policy.py` — `watcher_enabled` / `solver_running` / `has_solver_key` /
  `captcha_in_scope` / `out_of_scope`; the switch and nothing else; every reader fail-closed.
* `app/services/captcha/service.py` — `handle_captcha` split into the scope gate +
  `_handle_captcha_scoped` (D-26: a split, not a branch — the gate adds no CC to the CC-6 body);
  `_watcher_running` delegates to `policy.solver_running` (one owner of the getattr dance);
  `SolveOutcome.status` is a free-form str, so `out_of_scope` needs no enum change.
* `app/services/single_job_runner.py` — three gates on the one predicate: `check_security`
  (kills probe+wait+overlay+penalty+stats), `_handle_security` (`Skipped (Watcher off)`, RULE 9),
  `wait_for_output` installs `security_settler` only in scope (the OFF silence is structural).
  `_handle_captcha_outcome` needs no `out_of_scope` branch: it raises only on
  stopped/page_error/token_stale, so the new status falls through as "no failure".

## Tests

* new `tests/test_captcha_scope.py`, `tests/test_watcher_off_zero_activity.py` — counting test
  (0 probes/marks/stats/penalties/log lines with OFF) + positive controls (same spies count > 0
  with ON); settler installation proven inside a real `wait_for_output` run.
* Existing tests armed explicitly (they test captcha, so they flip the switch ON — named):
  `tests/test_captcha_service.py` (config dict; its chaos test keeps the switch legible so the
  boom paths still run in scope), `tests/test_captcha_boundaries.py` (state dict),
  `tests/test_single_job_runner.py` (get_state map),
  `tests/characterization/harness.py` (`build_bridge(..., watcher_on=False)` — new keyword with a
  default; all 10 existing callers untouched) and
  `tests/characterization/test_batch_goldens.py` (the captcha golden passes `watcher_on=True` —
  all 14 goldens byte-identical, verified).

## Docs (same commit, RULE 17)

`docs/current/AGENT_RULES.md` RULE 20: appended "Watcher OFF = zero captcha activity" amendment.
`docs/current/SYSTEM_OF_RECORD.md` row 12 + I-19/I-34.

## Gate

`radon cc -s app/services/captcha/policy.py` ⇒ all A. `captcha/service.py`: max_func_loc 27,
max_cc 7 unchanged (the body kept its complexity under the new name). `single_job_runner.py`:
check_security CC 4 ≤ 9; no function grew past its recorded span.
