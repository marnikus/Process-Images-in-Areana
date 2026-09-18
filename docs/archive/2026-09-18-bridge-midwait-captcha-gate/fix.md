# Fix — bridge inline wait never detected a mid-wait captcha

Date: 2026-09-18 · Status: root-caused → implemented
Companion evidence: user log 22:32 (`Submit Once → Wait New Output → Generating
spinner visible`, then silence — no `🛡️` line at all while the captcha was on
screen).

## Reported

"The app does not recognise the captcha on the web and does not start solving
it. No raise detection in log at all now."

## Root cause (verified in code, not conjecture)

`wait_for_new_output` consults `ctrl.security_settler` on every ~2 s poll via
`CDPArenaController._security_gate()` — that is the mid-wait detection the
2026-09-18 rounds added. But the attribute was armed by exactly ONE driver:
`single_job_runner.wait_for_output` (the dispatcher path).

The bridge **inline run loop** (single-run mode: `Submit Once → Wait New
Output`, the flow in the user's log) called `ctrl.wait_for_new_output(...)`
directly and armed nothing:

* its only captcha checks were (a) the submit-boundary settle (a point-in-time
  probe — the challenge typically appears seconds AFTER submit, during
  generation) and (b) one pre-wait check at the top of each 180 s wait cycle;
* inside the wait, `_security_gate()` returned immediately (settler is None)
  — a dialog appearing at any point in those 180 s produced **zero log lines**
  and the job burned the full timeout, then reloaded the page (which can even
  destroy the dialog).

Not caused by the provider change — the gate gap is structural and predates
it; the provider work only made the silence obvious.

## Fix

Dispatcher parity for the bridge inline loop (services-owned, same pattern):

* `app/services/captcha/recovery.py` — NEW `InlineWaitGates` (per-job bundle:
  prompt, image_path, cancelled, report, settle) + `arm_wait_gates` /
  `disarm_wait_gates` / `wait_with_gates(ctrl, gates, wait_fn)` (arms the
  security settler + revival policy for the duration of one wait, disarms in
  `finally`, fail-open on arming errors per RULE 9).
* `app/ui/bridge.py`:
  * builds `wait_gates` once per job iteration (settle lambda routes through
    `_settle_captcha_at(..., "gen-wait")` — the same choke point as every
    other site);
  * wraps **all five** inline `wait_for_new_output` call sites (WAIT_OUTPUT,
    JOB-ID-mismatch re-wait, and the three download-recovery waits) in
    `wait_with_gates(...)`;
  * `_settle_captcha_at` now returns `bool` (settled) so the settler stamps
    the revival policy only on a real settle (dispatcher `check_security`
    semantics);
  * the redundant 17-line pre-wait captcha check is deleted — the gate covers
    the dialog from the wait's first poll (net bridge delta ≈ +5 lines).

Behaviour after the fix: a dialog appearing at ANY moment of any generation /
re-wait is detected within ~2 s, logged (`🛡️ Captcha detected …` + FLAG
lines), settled (opt-in auto-solve or manual wait), and if the blocked
generation died, the bounded revival resubmits once — exactly the dispatcher
path's proven behaviour.

## Gates (RULE 16)

* NEW functions: `arm_wait_gates` 20/2, `disarm_wait_gates` 7/1,
  `wait_with_gates` 9/3, `Bridge._settle_captcha_at` 16/4 — all within
  LOC ≤30 / params ≤4; radon CC ≤5; recovery.py branches 32/34 (94%).
* Tests (+7): gates arm/disarm lifecycle, settle→stamp and settle-False→no
  stamp, fail-open arming, bridge `_settle_captcha_at` bool + choke-point
  routing (real `Bridge` method via `object.__new__`, package-level
  `handle_captcha` patched — the binding the bridge actually imports).
* Suite: 462 passed; `verify_quality.py --changed --allow-legacy` ✅.
