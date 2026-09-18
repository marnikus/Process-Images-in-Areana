# Pass-path research — full "is the user real" inventory of the captcha-on saved state

**Date:** 2026-09-18
**Status:** research complete, implementation follows this document in the same session
**Artifact researched:** `arena webpages/state-captcha on/(12) Directly Chat with Frontier Image Generation AI -captcha Models.html` (exact user-provided path, now present in the checkout — closes the open item §2.1 of `docs/archive/2026-09-18-recaptcha-page-mechanics/research-design.md`)
**Companion fixture:** `arena webpages/state/Arena _ Benchmark & Compare the Best AI Models.html` (normal, badge-only state)

## 1. Decision summary

The page has **more than one "is the user real" mechanism**, but only ONE of them
gates the generation path. The rest are observational telemetry or server-side
consequences. Inventory (full detail in §3):

1. **GATE — reCAPTCHA Enterprise checkbox widget inside the "Security Verification" modal.**
   This is the only client-side mechanism that blocks the path. Solving it (token
   accepted server-side) is what opens the path.
2. **GATE layer 2 (escalation inside the same widget) — bframe image-selection
   challenge** (`rc-imageselect`), shown when the checkbox click does not reach the
   site's risk threshold. It is part of the same widget solve, not a second product.
3. **RISK FEED — always-present invisible badge widget** (different sitekey). It runs
   `execute()`-style risk scoring; its score is what makes the modal appear. It is
   never solved directly — it only *triggers* mechanism 1.
4. **SERVER GATE — Enterprise assessment** of the submitted token (valid / hostname /
   action / single-use / ~2-minute TTL). Invisible from DOM; only observable through
   page error vs generation proceeding.
5. **OBSERVATION ONLY — PostHog** (session recording, autocapture, dead-click capture,
   exception autocapture, web-vitals, surveys, heatmaps) **and Google Tag Manager**.
   These record human-likeness; they do not gate. Policy: leave untouched.
6. **CONSEQUENCE — rate limiting / cooldown** after captcha events (already modelled
   by the app's cooldown system).

Consequence for the implementation: "solving the path" = solving mechanism 1 (which
internally covers 2), with correct widget sitekey, then passing the acceptance gate
(4) without tripping (6). Mechanism 3 is never solved; mechanism 5 is never blocked
or spoofed.

Four concrete gaps were found by running the REAL probes against the saved page with
jsdom (§5). All four are small, bounded, testable changes (§6).

## 2. Research method

1. Static inspection of the saved HTML + all 40 saved asset files (iframes, scripts).
2. Grep sweep for third-party bot-detection products (Turnstile, hCaptcha, Cloudflare,
   DataDome, PerimeterX, Arkose, fingerprint.js, honeypots, webdriver checks) — none
   found; the only "bot"/"phantom" hits are CSS (`Roboto`, `sonner-toaster`) and AI
   model names (`phantom_brush`).
3. Execution of the REAL probes (`app/browser/captcha_js/detect.js`, `visible.js`)
   against the saved HTML under jsdom (one-off harness `.cache/research_page.mjs`;
   permanent version lands as `tests/js/test_captcha_saved_page.mjs`, §6).
4. External contract verification: 2Captcha `RecaptchaV2EnterpriseTaskProxyless`
   (`websiteKey` REQUIRED, `isInvisible` optional, `enterprisePayload` optional) and
   Google Enterprise token semantics (single use, two-minute expiry, backend
   assessment authoritative).

## 3. Mechanism inventory on the exact saved page

### G1 — Security Verification modal with reCAPTCHA Enterprise checkbox  [GATE]

* Radix dialog: `div[role="dialog"][data-state="open"]`, sr-only `h2` "Security
  Verification", visible heading + "Please complete this quick security check to
  continue. This helps us keep the platform safe for everyone."
* Widget container `#recaptcha-v2-container`, 304×78 checkbox iframe
  (`size=normal`, `theme=light`), footer "Protected by reCAPTCHA" with pulsing dot.
* Anchor URL (from saved iframe comment): `https://www.google.com/recaptcha/enterprise/anchor?ar=1&k=6Le3_cYsAAAAAGwWOK2RLDgNI15Bh8C0yLBOL1yL&co=aHR0cHM6Ly9hcmVuYS5haTo0NDM.&hl=en-GB&...`
  → **Enterprise** family (`/recaptcha/enterprise/`), **widget sitekey `6Le3_cYs…`**.
* Hidden response field inside the dialog: `textarea#g-recaptcha-response-12[name=g-recaptcha-response]`.
* The page closes the modal only after its own backend accepts the token — a
  client-side callback alone is not acceptance (live evidence in
  `2026-09-18-recaptcha-verification-architecture/design.md`).

### G2 — bframe image-selection challenge  [GATE layer 2, escalation of G1]

* 13 saved `bframe*.html` frames; DOM carries `rc-buttons` (undo/reload/audio/help),
  `rc-imageselect`, `rc-challenge-help` — the standard image-grid challenge.
* Lives in the bubble container (`visibility:hidden; top:-10000px` in this snapshot
  because the escalation was not active at save time). When risk is low enough the
  checkbox solve returns a token directly; when not, Google swaps in this frame.
* For the solver this is NOT a second integration: the provider worker interacts
  with the real widget (checkbox → images if escalated) and returns the resulting
  token. The app's only duty: *detect and report* the escalation, and give the solve
  enough time.

### G3 — Invisible badge widget  [RISK FEED, never solved]

* `div.grecaptcha-badge` — `position:fixed; visibility:hidden; right:-186px`
  (off-screen even when "display:block"), anchor `size=invisible`,
  `cfg['render'] = ['6LeTGMcsAAAAALuIlkVwIxaAuZA8VledA6d3Nnb0']`,
  `anchor-ms=20000`, `execute-ms=30000`, `enterprise:true`, `enterprise2fa:true`.
* **Different sitekey than G1** (`6LeTGMcs…` badge vs `6Le3_cYs…` modal). This is
  decisive: the solver's `websiteKey` must be the MODAL key. Submitting the badge
  key creates a task for the wrong widget.
* Its own response field `#g-recaptcha-response-100000` is the second of the two
  `g-recaptcha-response` fields on the page (evidence: `responseFields=2`).

### G4 — Server-side Enterprise assessment  [SERVER GATE]

* After the callback the site POSTs the generation request; the backend verifies the
  token via the Enterprise assessment API (`tokenProperties.valid`, hostname, action,
  single-use, ~2-minute TTL, `riskAnalysis` incl. `AUTOMATION`). Only "generation
  proceeds / output appears" proves acceptance. Already implemented as the
  acceptance gate + baseline/output verification.

### G5 — PostHog telemetry  [OBSERVATION ONLY]

* Remote-config project `phc_LG7IJbVJqBsk584rbcKca0D5lV2vHguiijDrVji7yDM`
  (`config.js.download`): `sessionRecording` v2, `autocaptureExceptions`,
  `capturePerformance.web_vitals`, heatmaps, surveys; plus
  `dead-clicks-autocapture.js`, `exception-autocapture.js`, `surveys.js`,
  `web-vitals.js` app modules.
* Records human-like interaction (clicks, dead clicks, timings). It can inform the
  site's risk decisions but is not itself a gate on this page.
* **Policy: do not block, intercept, or spoof.** Blocking it would itself be a
  detectable fingerprint change; RULE 20 forbids evading site controls.

### G6 — Google Tag Manager  [OBSERVATION ONLY]

* `js` asset = GTM container (`__ogt_cross_domain`, google.cz config). Analytics
  only. Same policy as G5.

### G7 — Cooldown / rate limiting  [CONSEQUENCE]

* Server-side pacing after captcha events; the app models it as stacked cooldown
  penalty (`cooldown_captcha_penalty_seconds`) and it already applies on solved
  edges. No new work.

### Not present on this page

Cloudflare/Turnstile, hCaptcha, DataDome, PerimeterX, Arkose/FunCaptcha,
proof-of-work, honeypot fields, `navigator.webdriver` probes, custom fingerprint
scripts — verified absent by grep across HTML and all saved JS.

## 4. Current-code coverage matrix (state of this checkout)

| Mechanism | Detection | Solving | Acceptance | Verdict |
|---|---|---|---|---|
| G1 modal checkbox | detect.js dialog walk ✓ | 2Captcha Enterprise task ✓ + inject + callback chain ✓ | page-error gate + dialog-gone verify ✓ | covered |
| G2 image escalation | partial (title/src family) | provider-side ✓ | same as G1 | **evidence gap** (§5 G-2) |
| G3 badge | excluded from triggers ✓ | never (correct) | n/a | **sitekey-leak gap** (§5 G-1) |
| G4 assessment | n/a (DOM-invisible) | n/a | output gate ✓ | covered |
| G5 PostHog | n/a | n/a (policy) | n/a | **documentation gap** (§5 G-4) |
| G6 GTM | n/a | n/a (policy) | n/a | same |
| G7 cooldown | n/a | n/a | cooldown stack ✓ | covered |

## 5. Gaps found by executing probes on the saved page

jsdom run of the CURRENT `detect.js` on the saved page returned:

```json
{ "visible": true, "kind": "recaptcha_enterprise",
  "sitekey": "6LeTGMcs…",        ← BADGE key — wrong widget!
  "sitekeySource": "script", "challengePresent": false, … }
```

### G-1 — Badge sitekey leaks into dialog solves (correctness, money-affecting)

When the dialog iframe `src` carries no parseable `k=` (widget re-rendered, src
rewritten, or the saved-state shape), the fallback chain walks the whole page and
grabs the badge key from the inline `enterprise.js` config. 2Captcha requires
`websiteKey`; a wrong key makes the worker render the wrong widget (or the backend
reject the token: hostname/action mismatch) → paid task wasted → `not_accepted`.

**Fix:** dialog-scoped sitekey preference. With an open dialog, accept ONLY
dialog-scoped sources: dialog iframe `k=` → dialog `[data-sitekey]`. Without a
dialog, keep the page chain. If nothing dialog-scoped is found, report no sitekey
(`solvable=false` → manual wait with the amber WHY line) instead of guessing the
badge key. Fail-open preserved.

### G-2 — Image-challenge escalation is invisible to the app (observability)

`challengePresent` only matched frames captured by the reCAPTCHA iframe selector;
the escalation state (bubble visible, image grid active) is never reported, so logs
cannot distinguish "worker is clicking a checkbox" from "worker is solving an image
grid" (very different solve times and failure modes).

**Fix:** capture bframe frames (`iframe[src*="bframe"]`) and compute
`challengeActive` = a challenge frame whose ancestor chain is actually visible
(bubble escalation flips `visibility`/`top`). Report-only: solver logs a
diagnostic line; no behaviour change.

### G-3 — No explicit token-TTL guard (contract hardening)

Google tokens are single-use and expire ~2 minutes after issue. The code already
injects immediately after receipt, but nothing ENCODES the contract: a future path
that delays injection (retry queue, refactor) would silently inject a dead token.

**Fix:** `TOKEN_MAX_AGE_SEC` guard at injection time: age beyond the limit →
`token_stale`, task deleted, manual fallback. Cheap, deterministic, testable.

### G-4 — Telemetry stack undocumented (agent-safety)

PostHog/GTM are not in any current doc. A future change might block them
("privacy") or misread them as gates.

**Fix:** this document + a SYSTEM_OF_RECORD note stating the observation-only
policy (leave untouched; never spoof).

## 6. Implementation plan (detailed structure)

### 6.1 `app/browser/captcha_js/detect.js`  (JS probe; single self-contained literal)

* Output gains: `challengeActive: bool`; `sitekeySource` values extended to
  `dialog_iframe_k | dialog_data_sitekey | iframe_k | data-sitekey | script | none`.
* Sitekey chain becomes dialog-scoped first (§5 G-1); script-page fallback only when
  no dialog is present.
* Challenge capture gains `iframe[src*="bframe"]`; `challengeActive` via an
  ancestor visibility walk (try/catch, jsdom+harness safe).
* Size note: one JS literal, RULE 16.1.5 embedded-JS exception; Python wrapper
  `build_detect_js` unchanged.

### 6.2 `app/services/captcha/signals.py`

* `CaptchaSignal.challenge_active: bool = False`; `_evidence_kwargs` maps
  `challengeActive`. Pure data, no new methods.

### 6.3 `app/services/captcha/solver.py`

* `TOKEN_MAX_AGE_SEC = 100.0` (well inside Google's 120 s, large enough that a
  normal solve never trips it).
* `_stale_token_reason(plan)` helper (~4 LOC): returns reason string when
  `monotonic() - plan.token_at > TOKEN_MAX_AGE_SEC`.
* `_inject_and_verify`: first check staleness → delete task + `_failed("token_stale")`.
* `_run_task`: after detect evidence, if `signal.challenge_active` log a one-line
  escalation diagnostic ("image-challenge escalation visible — the provider solves
  the selection on its side; expect a longer solve").
* Budgets after change: every touched function stays ≤30 LOC, CC ≤10, nesting ≤4
  (verified with radon post-change, §8).

### 6.4 `app/services/captcha/service.py`

* `_signal_evidence`: add `"active": signal.challenge_active` to the challenge
  object (bounded, non-secret).

### 6.5 Tests (RULE 8 — real things run)

* `tests/js/test_captcha.mjs` (stub DOM): dialog iframe key beats page script key;
  dialog without key reports empty sitekey (no badge leak); `challengeActive`
  true/false by bubble visibility; bframe-src capture.
* NEW `tests/js/test_captcha_saved_page.mjs` (jsdom, REAL saved artifacts):
  * captcha-on page → `visible=true`, `kind=recaptcha_enterprise`,
    `dom=dialog:recaptcha-iframe`, `responseScope=dialog`, `responseFields=2`,
    `integration=enterprise`, `challengeActive=false`, and sitekey EMPTY
    (dialog-scoped rule — fixture iframe src is a local path; live pages carry
    `k=` in the src, covered by the stub test);
  * normal page → `visible=false` (badge-only never triggers).
  Registered in `package.json` `test:js`.
* `tests/test_captcha_solver.py`: stale-token guard refuses injection + deletes the
  task; challenge-active diagnostic logged.
* Evidence assertion added to the existing service evidence test.

### 6.6 Docs (RULE 17)

* This archive doc; SYSTEM_OF_RECORD row 12 note (dialog-scoped sitekey preference,
  escalation evidence, TTL guard, telemetry policy); DOM_SELECTORS evidence row for
  the captcha-on state; docs/README archive entry.

### 6.7 Explicitly OUT of scope (RULE 20)

No fingerprint/UA/cookie spoofing, no telemetry blocking, no
`reportIncorrect` automation, no second provider, no badge solving, no change to
manual-default policy. Provider credentials handling unchanged (masked-only).

## 7. State machine impact

No new states. `token_stale` gains one more entry edge (TTL guard). Report schema
`challenge` object gains `active: bool` (v1 report stays backward compatible —
consumers tolerate extra keys).

## 8. RULE 16 / RULE 18 compliance — design plan + measured results

Design constraints (as planned):

* detect.js change stays ONE JS literal (16.1.5); no new Python params.
* Every new/edited Python function ≤30 LOC, ≤4 params, CC ≤10, nesting ≤4.
* `CaptchaSignal` stays a pure dataclass ≤150 LOC (adds 1 field + 1 mapping line).
* Every new function has a test that fails if the function is deleted
  (stale guard, challenge_active mapping, saved-page probe assertions).
* Empty vs broken kept distinct: missing dialog sitekey → manual wait with WHY
  (not a fake solve); stale token → `token_stale` (not `auto_failed`).
* Stop honoured: staleness check sits before injection in the existing
  stop-aware path; no new loops introduced.
* Selectors: semantic (`role=dialog`, `title`, `name`) before fragment
  (`bframe` substring is a last-resort src family marker, RULE 21).

Measured at implementation end (2026-09-18, same session):

| Gate | Result |
|---|---|
| `pytest tests -q --ignore=tests/integration` | **360 passed** (354 baseline + 6 new) |
| `npm run test:js` | **106 passed** (98 baseline + 8 new: 4 stub + 4 real-artifact jsdom) |
| `tools/verify_quality.py --changed --allow-legacy` | **0 fails** (148 pre-existing legacy warns, all in baseline) |
| radon CC on changed files | worst `_poll_task` B(10) pre-existing; new code ≤ B(7) |
| Class LOC `CaptchaSolver` | 150 ≤ 150 (escalation + stale-refusal extracted to module helpers by real responsibility, RULE 19 step 4) |
| Coverage, line (repo total, fast tier) | 35.868% → **36.004% (+0.136pp)** — not decreased |
| Coverage, branch (repo total, fast tier) | 26.377% → **26.580% (+0.202pp)** — not decreased |
| New functions with 0 hits | **0** — `_stale_token_reason` 5/5, `_refuse_stale_token` 7/7, `_note_escalation` 3/3 lines hit |
| Changed-module coverage | solver.py 87.3%/88.6%, signals.py 94.2%, service.py 92.3%, captcha_probes.py 100% |

Note on the 80%/75% absolute targets: they describe the full CI tier matrix
(incl. Qt/e2e lanes); on the sandbox fast tier the repo steady state is the
35.9% line above, so the binding constraints for this change are
*never decrease* and *every new function tested* — both proven.

## 9. Live-run verification checklist (user session)

1. Run one job with CAPTCHA_AUTO ON; expect detect log line with
   `sitekeySource=dialog_iframe_k` and the MODAL key (`6Le3_cYs…`).
2. If the image challenge appears, expect the escalation diagnostic line and a
   longer solve; token still injected through the same callback chain.
3. `CAPTCHA_SOLVE` report: `challenge.active` true/false matches what was on screen.
4. Generation completes → `CAPTCHA_JOB job=completed` (output gate, not captcha).
5. Cooldown penalty stacks exactly once per solved edge.

## 10. Sources

* Saved artifact + 40 asset files (this checkout, `arena webpages/state-captcha on/`).
* Google: https://docs.cloud.google.com/recaptcha/docs/create-assessment-website
  (single-use token, two-minute expiry, backend assessment authoritative).
* Google: https://developers.google.com/recaptcha/docs/verify (token TTL/single use).
* 2Captcha: https://2captcha.com/api-docs/recaptcha-v2-enterprise
  (`websiteKey` required, `isInvisible`, `enterprisePayload`).
* Prior rounds: `docs/archive/2026-09-18-recaptcha-page-mechanics/research-design.md`,
  `docs/archive/2026-09-18-recaptcha-verification-architecture/design.md`,
  `docs/archive/2026-09-18-captcha-delivery-recovery/design.md`.
