# Captcha during generation wait: the silent settle hook + observable detection

## 1. Report

User (2026-09-18, after the 12:49 run): "grid fixed but the captcha still not
solving. No log about the solve starting or any steps in log. Detecting
captcha on screen is not clear — do some steps to show up that it catches it.
Give steps to debug it now." The screenshot shows the Security Verification
dialog open on the page **while the Wait New Output block is running**; the
log shows the submit, the generation wait start, the spinner — and **zero
captcha lines**.

## 2. Research — where the 12:49 run could have seen the dialog

The 12:49 log (`▶ Block Submit Once (SUBMIT)` … `Block Wait New Output
(WAIT_OUTPUT)`) is the bridge block runner (`_do_run_batch`, bridge.py), not
`single_job_runner`. In that flow the captcha checks are:

| site | when it runs | 12:49 outcome |
|---|---|---|
| `CHECK_SECURITY` block | only if the user's block stack contains it | not in this stack |
| pre-check before each wait cycle (bridge.py:3056) | **once**, at wait start | ran 12:49:26 → dialog not yet open → `False`, no log |
| `_settle_boundary_captcha` (submit/download) | before those blocks | before submit only — no dialog |
| **`CDPArenaController._security_gate` (cdp_arena.py:337)** | **every 2 s poll inside `wait_for_new_output` — the only check during the 180 s wait** | **silent no-op — see below** |
| passive `WatcherService` | every 2 s, **when enabled** | `enabled=False` default; no `👁️ Watcher started` line in the log → off |

**ROOT CAUSE.** `CDPArenaController.wait_for_new_output` runs `_security_gate`
in its poll loop; `_security_gate` does:

```python
settler = getattr(self, "security_settler", None)
if settler is None:
    return                      # ← no log, no detection, every poll
if await self.is_security_dialog_visible():
    await settler()
```

`security_settler` is set **only by `single_job_runner.wait_for_output`** —
a different job flow. The bridge block runner never sets it, so for the whole
180 s generation wait the only live captcha check was a **silent no-op**.
The dialog opened *after* the single pre-check → nothing saw it → no log,
no solve attempt. (The solver itself logs every step — createTask, poll,
token, inject, continue — it just never got started.)

**SECONDARY GAP (the "detection is not clear" part).** The gate predicate is
a bare boolean (`build_visible_js`). Even when it works, there is no record
of WHAT was on the page — 0 dialogs? 1 iframe in the badge, hidden? — so the
user cannot tell a missed detection from "nothing there", and neither can
the app.

## 3. Design

1. **Arm the settle hook in the bridge wait path (the fix).** New
   `Bridge._arm_gen_wait_settler(ctrl, tab_id, corr_id, overlay_sec)` sets
   `ctrl.security_settler` to a closure that settles via
   `_settle_captcha_at(…, "gen-wait")` and restores the generation overlay.
   Called before the WAIT_OUTPUT wait-cycle loop and before the DOWNLOAD
   retry waits; every call replaces any stale closure (one `ctrl` per batch,
   re-armed per job with a fresh correlation id).
2. **Observable gate (cdp_arena.py).** New probe `captcha_js/diagnose.js`
   — superset of `visible.js` (identical verdict logic) + `detect.js`
   (kind/sitekey/anchor) + **evidence**: open dialog count with matched
   text, each reCAPTCHA iframe (in-badge / in-dialog / on-screen,
   w×h at x,y), and a one-line **reason** (which branch fired / why clear).
   `_security_gate` evaluates it once per poll (same CDP cost as the old
   boolean) and logs: verdict *changes* always
   (`🛡️ Security scan: challenge — …` / `✅ … clear — …`), a heartbeat every
   15th poll (~30 s) while clear, and a one-per-episode warning when a
   challenge is visible but no settler is armed (never silent again).
3. **On-demand scan ("debug it now").** "🔍 Scan now" button in the Captcha
   window → bridge slot `diagnose_captcha()` → one diagnose probe on the
   current tab + 2Captcha status → **numbered step-by-step report** in the
   log window (page → dialogs → iframes → verdict → auto-solve state →
   action). `build_scan_report` lives in `app/services/captcha/diagnose.py`.
4. **Debug steps for the user** (§6 below) — what to look for, and which
   evidence line to send back when the dialog is on screen but the scan
   says clear.

Out of scope (kept): the passive `WatcherService` (off by default, optional
backup — mentioned in §6), the Playwright `controller.py` predicate
(separate flow, unchanged).

## 4. RULE 18 recheck (changed code)

- `cdp_arena.py`: `_security_diagnose` 7, `_log_security_beat` 12,
  `_security_gate` 14 — 4–20 band, ≤3 params.
- `bridge.py`: `_arm_gen_wait_settler` 15 / 4 params,
  `diagnose_captcha` 6, `_run_captcha_scan` 13.
- new module `app/services/captcha/diagnose.py` (59 lines):
  `build_scan_report` 14, `_verdict_line` 7, `_action_line` 6,
  `_describe_frames` 10, `_describe_dialogs` 10.
- JS: `diagnose.js` self-contained IIFE (probe, no gate on size);
  `captcha.js` +1 handler + `scanNow()` (~9 lines).

## 5. Verification

- pytest **317** (was 305): gate clear verdict + ~30 s heartbeat, challenge
  without settler warns exactly once, challenge calls the settler then stops
  when clear, probe error fails open (RULE 9), settler exception is warned
  not raised, `_arm_gen_wait_settler` wiring (settle + overlay restore),
  scan report lines (challenge / clear + frame evidence), `diagnose_captcha`
  slot refuses without a browser.
- node **108/108** (was 100): `diagnose.js` on the stub DOM — badge-only →
  clear with badge reason; real dialog markup → challenge + DIALOG sitekey +
  geometry evidence; dialog+badge coexist → dialog wins; standalone
  on-screen iframe → challenge via iframe branch; closed dialog + hidden
  badge → clear; container-only dialog → sitekey from `data-sitekey`;
  **verdict parity with `visible.js` on all four canonical states**.
- gates: full pytest + node + `verify_quality.py --changed --allow-legacy`.
- live acceptance: during the generation wait the log shows `🔎 Security
  scan` heartbeats; when the dialog opens the verdict flips to `challenge`
  and the existing solve steps follow (`🛡️ Captcha detected …` →
  `🤖 FLAG CAPTCHA_AUTO` → createTask/poll/token/inject — or
  `🛡️ FLAG CAPTCHA_WAITING` with the reason). "🔍 Scan now" prints the
  numbered report on demand.

## 6. Debug steps (what the user runs)

1. Start the job; when the dialog appears, watch the log window —
   `🔎 Security scan: clear — …` heartbeats prove the gate is polling and say
   exactly what it sees; the moment the dialog opens, `🛡️ Security scan:
   challenge — …` plus the solve steps must follow.
2. If it doesn't follow: open the **Captcha window → "🔍 Scan now"** and
   read the numbered report — step 1/2 show the dialogs/iframes the page
   actually has (count, text, geometry), step 3 the verdict, step 4 whether
   auto-solve is ON with a key.
3. If the dialog is visible in the browser but step 3 says "no challenge",
   send back the report (steps 1–3) — the evidence lines show precisely
   which marker (dialog role/text/iframe title) the page lacks.
4. Optional extra coverage: enable the passive watcher in Settings (watcher
   panel) — it polls independently of the job flow.
