# Captcha auto-solve: token accepted, dialog closed — but the generation never resumes

## 1. Report

Run of 2026-09-18 11:37 (4 pages, auto-solve ON, key …27d4, balance $4.69):

| t | event (all 4 tabs) |
|---|---|
| 11:37:09–10 | `Submit: success Clicked (button[aria-label="Send message"])` |
| 11:37:12 | spinner up (generation started) |
| 11:37:14 | `🛡️ Captcha detected (recaptcha_enterprise, sitekey=set) via check-security` → `FLAG CAPTCHA_AUTO` |
| 11:38:10–30 | `🤖 2Captcha solved … in 60/61/61/76s (token accepted)` — 4/4 solved |
| ~11:38:14 | injection (`cb=not found in anchor`, 1× scope=dialog, 3× scope=document), dialog closed ≤4 s after injection |
| 11:38:14 | **spinner gone** — same second the first dialog closed; never comes back |
| 11:40:11 | all 4 jobs `Wait New Output: Timeout after 180000ms` → New-Chat reset |

So the solve pipeline now works end-to-end on the page side — the dialog is closed by our
token in 4 s. What is missing: **arena does not resume the generation request afterwards.**
A captcha only counts as solved when the gated generation completes; "token accepted"
(dialog closed) is an intermediate state.

## 2. Diagnosis

**What the dialog close proves.** The page-side UI accepted the token (field change /
continue-click path works). It does NOT prove the generation request was re-triggered.

**How arena resumes after a challenge.** From the saved badge snapshot, the enterprise anchor
src carries `cb=<randomGlobalName>` — the widget's solved-callback is a random-named global
on the parent window. A real (human) solve inside the iframe makes the widget call
`window[cb](token)` — that callback is arena's token-consumption + request-resume path.
The user's historical manual solves always led to completed generations with no re-click:
the app just waits for the image because the callback does the resuming.

**Why our solve does not resume.** Our inject probe found **no `cb=` in the dialog anchor
(4/4 tabs, "cb=not found in anchor")** — the dialog wires its callback by JS, not URL param,
so we cannot invoke it. The continue-click result was not even logged (blind spot). The
11:37 outcome — no spinner re-appearance, no fresh challenge, no page error, 100 s of
silence — is exactly "UI accepted the token, request was never re-sent".

**The asymmetry (root cause):** a human solve fires the widget callback → arena auto-resumes.
An auto-solve delivers the token to the field/button but the callback never fires → the
aborted request is never re-submitted → the wait loop polls for an image that will never
arrive → 180 s timeout. A human facing this exact state would do one thing: **click Send
again.** The pipeline has no such step.

**Why a re-click is safe (guards).** `JS_VERIFY_PROMPT` reads the composer
`textarea[name="message"]` — cleared after a successful send. So:

1. `is_generating()` (spinner) true → the request is alive → never re-send.
2. composer no longer holds our exact prompt → the send was consumed → never re-send.
3. only then: one `submit()` via the same `JS_CLICK_SEND` probe the SUBMIT block uses.

**Token expiry.** Google reCAPTCHA tokens live 120 s. Solve 60–76 s + inject + 5 s settle +
re-send ⇒ token age at re-send ≈ 65–85 s — inside the TTL. If the re-send is challenged
again, the gate naturally solves a fresh token (self-healing).

## 3. Design

1. **Post-solve re-submit (the fix).** `single_job_runner.wait_for_output` swaps the gate
   closure from `check_security` to `_security_gate`, which calls `check_security` and then
   `_post_solve_resubmit`:
   - `check_security` records `ctx.captcha_solved = status` on a settled captcha
     (`solved` | `manual`) — also covers the F4 pre-wait solve in `_handle_submit`.
   - `_post_solve_resubmit` consumes the flag (one re-send per solve), waits
     `POST_SOLVE_SETTLE_SEC = 5.0` (a live request shows its spinner by ~2 s), then applies
     guards 1–2 above and re-sends once. Every decision is logged with the `[corr]` prefix.
   - No dialog → flag unset → the gate is a no-op (zero cost in the common path).
2. **Diagnostics (next failure must be explainable from the log):**
   - detect probe adds `anchor: {cb, size, ams, ems}` from the anchor src; `CaptchaSignal`
     carries it; the "Captcha detected" line prints it (proves whether the dialog exposes a
     callable `cb=` in its URL).
   - `solver._click_continue` logs the result: which button closed the dialog
     (`button: <label>`) or `no action button` (field-change closed it).
   - post-solve decision lines: `request alive (spinner) — no re-send` /
     `prompt not in composer — no re-send` / `♻️ post-solve (auto): request was dead — re-sent prompt`.
3. **Not changed:** solver API/billing flow, detect predicate, badge exclusion, overlay
   states, stats, SOR invariants. Auto-solve remains opt-in; a manual solve that auto-resumed
   (spinner up) is left alone by guard 1.

## 4. RULE 18 recheck (changed code)

- `single_job_runner.py`: `_post_solve_resubmit` 19 body LOC, `_security_gate` 2,
  `_job_log` 4, `check_security` +2 (25 body) — all in the 4–20 band (≤30 hard fail);
  file stays one block-runner (~540 LOC, ideal-size header, RULE 18.2).
- `solver.py`: `_click_continue` 11 body LOC (now logs the result); class unchanged.
- `service.py`: `_anchor_desc` 3 body LOC helper.
- `signals.py`: `CaptchaSignal` +1 field (dataclass, no LOC pressure).
- params: all new functions ≤2; CC: `_post_solve_resubmit` 5, `check_security` 6; gate
  `--changed --allow-legacy` reports 0 fails on these files.

## 5. Verification (2026-09-18)

- unit (`tests/test_captcha_boundaries.py`, 6 new): resubmit guards — dead+prompt → one
  submit; alive (spinner) → skip; composer cleared → skip; no flag → zero probes;
  gate end-to-end (settled captcha → one re-send); `check_security` records the settled
  status; flag consumed (one re-send per solve).
- unit (`tests/test_captcha_service.py`): anchor passthrough in `CaptchaSignal.from_result`
  (dict kept, bad shape → `{}`).
- node (`tests/js/test_captcha.mjs`, 2 new): detect anchor diagnostics — cb/size/ams/ems
  parsed when present, false/empty when absent.
- gates: pytest **295** (was 289), node **90/90** (was 88),
  `verify_quality.py --changed --allow-legacy` **0 fails**; app-wide coverage 29.7 %
  (baseline 29.3 % — pre-existing gap, improved by the new tests).
- live acceptance: next challenged run must log the post-solve decision line and — for a
  dead request — `♻️ post-solve (auto): request was dead — re-sent prompt` followed by
  spinner + new output (generation completes).
