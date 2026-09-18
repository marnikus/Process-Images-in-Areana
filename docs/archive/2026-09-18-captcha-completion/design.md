# Captcha completion: the token is injected but the dialog never resumes — force-complete + re-send

## 1. Report

User (2026-09-18 13:08 run): "nothing starts. no fix." The log now shows the
full pipeline working — heartbeat, verdict flip, **2Captcha solve in 25 s,
token injected** (`scope=dialog, cb=not found in anchor`) — and then the end:
`🤖 dialog continue: no action button found`. The dialog stays open, the
generation never resumes, and the scan's last error is "dialog still visible
after token injection".

## 2. Research — what a real solve does that injection doesn't

From the saved dialog markup (2026-09-18 round 2) + this run's evidence:

1. The dialog's anchor iframe has **no `cb=`** param (the BADGE anchor does —
   that's the invisible widget's consumption path). So inject.js step (2),
   `window[cb](token)`, can never fire for the dialog — "cb=not found in
   anchor" is *expected*, not a bug.
2. The dialog widget is a **visible size=normal checkbox** rendered via
   `grecaptcha.render(...)` — its sitecallback is a **JS closure** in
   arena's bundle, not a URL parameter. When a human checks the box,
   Google's widget calls that closure with the token; **the closure is what
   closes the dialog and resumes the request**. Writing the token into
   `#g-recaptcha-response` (what inject.js does) does not invoke that
   closure — and there is no Continue button to click (confirmed by the
   probe: "no action button found").
3. Consequence: after injection the dialog is **stuck by design** — the
   current 20 s grace (`VERIFY_GRACE_SEC`) always expires, the solve is
   reported `not_accepted`, and the flow degrades to manual wait even though
   the token IS on the page (in the textarea) and fresh (120 s validity).
4. The 13:08 run also proves the round-9 fix works end-to-end: detection,
   verdict, per-tab parallel solves, token receipt. The ONLY missing link is
   **completing the flow with the token we already have** — and, in the
   bridge block flow, re-sending the prompt afterwards (round-6
   `_post_solve_resubmit` exists only in `single_job_runner`).

**Open unknown (why the deep scan, §3.4):** does arena's submit handler read
the token from the `#g-recaptcha-response` field or from
`grecaptcha.getResponse()` at send time? Both are covered by the fix below;
the deep scan (bundle source search) tells us which, so the loop can be
closed if the re-send still challenges.

## 3. Design

1. **Complete the injection (inject.js, extended).** After setting the
   field and trying `cb`: **patch `window.grecaptcha.getResponse` to return
   the solved token** (widget-internal state is the other consumption
   path; the patch is scoped to the page, best effort, reported in the
   inject result).
2. **Force-close when stuck (new `close_dialog.js`).** After a SHORT 3 s
   grace (instead of 20 s — the dialog cannot close itself on an injected
   token, so the long grace only burns token validity):
   1. Esc keydown dispatch (Radix Dialog closes natively on Escape — the
      React-proper path),
   2. click the Radix close control (`[data-radix-dialog-close]`,
      aria-label close / "X"),
   3. nuclear: remove the open dialog node + focus guards + backdrop.
   If the dialog is gone → the solve counts as **solved** (token remains in
   the field for the re-send). Only a page where even the nuclear close
   fails falls back to manual wait.
3. **Re-send in the bridge flow (round-6 parity).** New
   `Bridge._post_genwait_resubmit(ctrl, corr_id)`: 5 s settle →
   `is_generating()`? request alive → skip; composer has a prompt?
   no → skip; else `submit()` once, logged `♻️ post-solve: request was
   dead — re-sent prompt`. Called from the per-poll settle closure
   (`_arm_gen_wait_settler`) and the pre-wait check settle — the two places
   a captcha settles during the bridge wait.
4. **Deep scan (research channel, "debug steps" on demand).** "🔍 Scan now"
   gains steps 6–8: open-dialog outerHTML excerpt, `window.grecaptcha`
   API surface, and a **same-origin bundle source search** for
   `recaptcha-v2-container` / `Security Verification` with context — the
   dialog component + its callback logic, from the user's own page.
   `app/browser/captcha_js/scan_deep.js` (async IIFE), executed with
   `await_promise`.

Out of scope: clicking the Google checkbox via the iframe's own CDP target
(a separate solve path, big new subsystem — only if the re-send still
challenges).

## 4. RULE 18 recheck (changed code)

- `inject.js` patch block 8 lines; `close_dialog.js` step-function probe
  (~55 lines JS, no LOC gate on JS); `scan_deep.js` async IIFE probe.
- `solver.py`: `_inject_and_verify` 20 / 4 params, `_force_close` 20;
  `VERIFY_GRACE_SEC 20 → 3` (+ `FORCE_CLOSE_STEP_WAIT 0.8`).
- `bridge.py`: `_post_genwait_resubmit` 17, `_composer_has_prompt` 7,
  `_run_captcha_scan` 16, `_captcha_scan_deep` 7.
- `diagnose.py`: `deep_scan_lines` 18.

## 5. Verification

- pytest **325** (was 305): solver force-close paths (esc rescue, nuclear
  after failed steps, already-closed, uncloseable → not_accepted with
  specific reason), `_post_genwait_resubmit` (alive → skip / no prompt →
  skip / dead + prompt → one re-send on the corr line), `deep_scan_lines`
  (evidence + empty-safe).
- node **117/117** (was 100): inject `getResponse` patch (patched → returns
  token / absent → not patched / no-getResponse → no crash); close probe
  (no-dialog none, esc, close-button click, no-control reason, nuclear
  removes dialog + overlay + focus guards, unknown step).
- gates: full pytest + node + `verify_quality.py --changed --allow-legacy`.
- live acceptance: token injected → `🤖 dialog force-closed (esc)` (or
  close-btn / nuclear) → `🤖 2Captcha solved … (token accepted)` →
  `♻️ post-solve: request was dead — re-sent prompt` → spinner returns,
  output arrives. If arena still challenges the re-send, "🔍 Scan now"
  steps 6–8 (dialog markup, grecaptcha surface, bundle source around the
  dialog markers) show the callback logic to finish the loop.
