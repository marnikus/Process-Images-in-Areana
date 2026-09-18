# Captcha auto-solve round 5: token delivered to the wrong place + dead generation never revived

Date: 2026-09-18 (continues `2026-09-18-captcha-token-callback/`).
Branch: `arena/01a0b3ea-process-images-in-areana`.
User report: "can not fix problem with capcha solving. still unable to path any
solved captcha. It looks like it starts sending captch to solve but it not send
it back or not quick enough."

## 1. Report (user log 11:36–11:40, 4 parallel tabs)

- 11:37:14 — captcha detected on all 4 tabs (`recaptcha_enterprise,
  sitekey=set`), 4 × `RecaptchaV2EnterpriseTaskProxyless` submitted.
- 11:38:14–11:38:30 — all 4 solved in 60–76 s, every one logged
  `token injected (scope=…, cb=not found in anchor)` then
  `2Captcha solved tab … (token accepted)`, then `Spinner gone`.
- 11:40:11 — every job `Wait New Output: failed — Timeout after 180000ms`.
  No output image on any tab. Balance decreased (tokens were paid for).
- Captcha window: `last error: dialog still visible after token injection`.

So: submit works, 2Captcha solves, injection "succeeds", verification passes —
and the job still dies with nothing. Three defects combine into this incident.

## 2. Diagnosis

### Defect A — the injected token never travels the real solve path (root cause)

The round-4 fix assumed the anchor iframe's `&cb=<name>` URL param is the
site's solve callback, invoked as `window[cb](token)` in the parent page.
The user's log disproves it: **4/4 injections `cb=not found in anchor`** — no
such global function exists at runtime (the saved-HTML "verification" could
never prove a live `window` function).

2Captcha's own docs define the real path, and it is never the anchor `cb=`
(which is recaptcha's internal iframe-loader param, not the site callback):

- `data-callback` attribute on the widget element → `window[name](token)`,
- or the `callback` passed to `grecaptcha.render()`,
- or `___grecaptcha_cfg.clients[N]…callback` ("aa.l may change and there can
  be multiple clients, check clients[1], clients[2] too")
  ([2captcha API](https://2captcha.com/2captcha-api),
  [invisible v2 guide](https://2captcha.com/h/how-to-bypass-recaptcha-v2-invisible),
  [CapSkip demo](https://capskip.com/captcha-demo/recaptcha-v2-callback/)).

Consequence: we set the hidden textarea but arena's handler never receives
the token, so the blocked generation never resumes — "starts sending captcha
to solve but it not send it back".

### Defect B — single-field injection can poison the badge's field

`inject.js` sets only the FIRST `g-recaptcha-response` field: dialog-scoped
when found, else the first page-wide match — which is the always-present
badge field `g-recaptcha-response-100000`, NOT the dialog's field. Log shows
3/4 tabs injected with `scope=document`. The dialog's real field may stay
empty while we report success.

### Defect C — the blocked generation dies and nothing revives it ("not quick enough")

Timeline per tab: spinner alive THROUGH the 60 s solve → dialog clears at
settle → `Spinner gone` → ~2 min of dead wait → timeout. The generation
request that the captcha blocked does not come back by itself: arena either
needs the token via its widget callback to resume/verify (Defect A), or the
failed attempt expects a fresh submit — a human would press Send again, the
app just waits out the remaining budget and fails.

60–76 s per enterprise solve is inherent worker latency (poll cadence 5 s per
docs, 4 tasks genuinely parallel — no serialization bug), so "faster" is not
available; the app must make a late token still produce a generation.

### Verified NOT broken (no change)

- `createTask` payload is docs-exact (`type` + `websiteURL` + `websiteKey` +
  enterprise-only `isInvisible`;
  [spec](https://2captcha.com/api-docs/recaptcha-v2-enterprise)).
  No `enterprisePayload.s` / `data-s` exists in arena's markup, `apiDomain`
  default `google.com` matches the iframe host — nothing to add.
- Per-tab parallelism, poll/timeout/verify-grace budgets, stats, gate
  predicate: all behave per the log.

## 3. Design

**Fix A — inject.js v3: all fields + the real callback chain.**
`(token, sitekey) => …` result
`{ok, scope, fields, len, cb, cbCalled, cbError, cbSource, clientsSeen}`:

1. Set EVERY `g-recaptcha-response` field (dialog fields first, then all
   document-level ones) with the React-safe setter + input/change events;
   `fields` = count set, `scope` = `dialog` if any dialog field was set.
2. Invoke the site callback, first hit wins (bounded, fail-open):
   a. `data-callback` on dialog widget containers
      (`.g-recaptcha`, `div.recaptcha-v2-container`, `[data-sitekey]`
      ancestors) then document-wide → `window[name](token)`
      (`cbSource: "data-callback:<name>"`);
   b. deep search of `window.___grecaptcha_cfg.clients` (≤10 clients,
      depth ≤6) for a function-valued `callback` property, preferring the
      client whose subtree contains the dialog sitekey
      (`cbSource: "grecaptcha-cfg"`, `clientsSeen` reported);
   c. legacy anchor `&cb=` attempt kept as last resort
      (`cbSource: "anchor-cb:<name>"`), else `cbSource: "none"`.
3. `build_inject_js(token, sitekey="")` (sole caller: `solver._inject`,
   which passes `signal.sitekey`); `solver._cb_desc` / `_reject_reason`
   report the source (`called <name> via <source>`; not-accepted reason
   names the tried chain). Class growth avoided via module helpers (RULE 16).

**Fix B — bounded generation revival after a mid-wait settle.**
New `app/services/captcha/recovery.py` (browser layer must never import the
captcha package — package docstring; the policy travels as a ctrl attribute,
same protocol as `security_settler`):

- `ResumePolicy(prompt, grace_sec=20, max_resubmits=1, …)` armed by
  `single_job_runner.wait_for_output` (owns the prompt + cancel predicate),
  cleared in `finally`; `note_settle(ctrl)` stamped by the settler wrapper
  ONLY when a dialog was actually visible-and-cleared.
- `maybe_resume(ctrl, diag)` called once per output poll from `check_fn`:
  pure observation, returns `diag` untouched unless ALL hold: policy armed,
  not ready, settle stamped, budget left, not cancelled, grace elapsed,
  `spinning` false AND `allNew == 0` (a live spinner or any new image =
  generation alive → marker cleared, no action). On fire: loud log,
  `insert_prompt(same prompt)` (idempotent: restores a cleared composer,
  overwrites a kept one with identical text incl. the same JOB-ID) +
  `submit()` once per wait, budget consumed even on failure. Any exception →
  fail open, `diag` unchanged (RULE 9).
- Touches to legacy files are minimal and import-free: `cdp_arena.check_fn`
  +1 line delegating to a module-level `_run_resume_gate` (~9 LOC, no new
  method on the 27-method class per RULE 16.5); `wait_for_output` arms/clears
  (+~5 lines) and installs `_settle_and_note` instead of the bare lambda.

Why 20 s grace: 10 consecutive dead polls at the 2 s cadence — far beyond
token-resume latency (seconds), far below the 180 s budget, leaving maximum
room for the fresh generation. Why `allNew == 0` required: any new image
(even JOB-ID-mismatched) proves a live generation — never resubmit over it.

**Rejected:** switching solver provider (latency is inherent; revival covers
lateness); `form.submit()` (double-submit risk); resubmit without prompt
re-insert (composer may be cleared → empty submit); sub-5 s polling (docs
cadence); touching `visible.js` (works; out of scope).

## 4. RULE 18 recheck (changed code)

- `inject.js`: 122 lines (self-contained probe leaf; single-purpose growth
  with `// ideal-size` reason comment; file ideal is 150–300, so no pressure).
- `recovery.py`: NEW ~140 lines, 10 functions à 4–14 lines, ≤4 params —
  inside ideals (radon max B(6)); dataclass policy, no class-LOC pressure.
- `solver.py`: `_cb_desc`/`_reject_reason` stay module-level (~8 LOC each);
  `CaptchaSolver` class LOC unchanged band (≤150 gate).
- `cdp_arena.py` (legacy baseline): +1 line in `check_fn`, +1 module helper
  (~9 LOC) — no new method, no new import, no metric worsening beyond the
  established [LEGACY] warn.
- `single_job_runner.py` (legacy baseline): +1 module helper (~7 LOC),
  +~5 lines arm/clear in `wait_for_output`.
- No new modules besides `recovery.py`; no signature change except the
  optional `sitekey=""` on `build_inject_js`.

## 5. Verification

- pytest: **299 passed** (was 284: updated 2 reason/log asserts to the new
  vocabulary; +2 solver tests — source-specific reason + log line,
  sitekey-in-probe wiring; NEW `tests/test_captcha_recovery.py`, 13 tests:
  fire-once-when-dead, skip when spinning/new-images/ready/pre-grace/
  cancelled/unarmed/no-policy, no-refire-after-second-settle,
  prompt-reinsert-then-submit order, gate attribute protocol, fail-open on
  ctrl errors, note/clear noops). New module coverage: `recovery.py` 88%
  line / **100% branch** (only `except: pass` scaffolding uncovered).
- node `test:js`: **92/92** (was 88: anchor-cb tests kept as the last-resort
  path with `cbSource` asserted; +4 inject tests — data-callback hit,
  cfg-clients fallthrough, sitekey-preferred client, multi-field set incl.
  badge field; `node --check` clean).
- `tools/verify_quality.py --changed --allow-legacy`: **PASSED, 0 code
  fails** (only pre-existing [LEGACY] warns on untouched hotspots);
  radon: new code max B(6) (`_resubmit`), everything else A — CC ≤10,
  nesting ≤4 on all new/edited functions.
