# reCAPTCHA page mechanics research and implementation design

**Date:** 2026-09-18  
**Status:** research/design only; production implementation intentionally not started  
**Scope:** user-authorized Arena image-generation pages and the locally saved CAPTCHA-on state

## 1. Decision summary

The page does not have only one CAPTCHA signal. The saved page shows a layered flow:

1. Google reCAPTCHA Enterprise bootstrap and hidden badge/anchor state.
2. An interactive challenge frame (`bframe`) that is separate from the anchor frame.
3. A hidden, one-use response field (`g-recaptcha-response`).
4. A site-owned callback/grecaptcha configuration path.
5. The Arena generation request and its own success/error state after the CAPTCHA callback.

The current application observes layers 1–4 partially and currently treats “callback called + dialog gone” as solved. The live evidence proves that this is not sufficient: the generation request can fail after callback, and a late token can arrive after the page has already entered an error state.

The implementation target is therefore **not “find another CAPTCHA selector”**. It is a bounded, observable state machine that distinguishes:

- challenge detected;
- token issued;
- token injected/callback attempted;
- page accepted the challenge;
- generation request accepted;
- generation completed;
- page failed or token became stale.

No implementation should attempt to forge browser identity, bypass site controls, evade risk scoring, or interfere with Google telemetry. Work stays within the user-authorized browser session and the existing provider integration, consistent with AGENT_RULES RULE 20.

## 2. Evidence inspected

### 2.1 Requested artifact

The exact requested path, `arena webpages/state-captcha on/(12) Directly Chat with Frontier Image Generation AI -captcha Models.html`, was not present in the checkout under that name at research time. The repository does contain the corresponding saved page:

- `docs/research/Directly Chat with Frontier Image Generation AI Models.html`
- `arena webpages/state/Arena _ Benchmark & Compare the Best AI Models.html`
- `arena webpages/state/Arena _ Benchmark & Compare the Best AI Models_files/anchor.html`

The saved research page contains the same relevant mechanics: Enterprise bootstrap, a hidden `grecaptcha-badge`, an anchor iframe, a challenge iframe, and a hidden response textarea. If the user-provided state file becomes available under the exact path, repeat the evidence comparison before implementation and record any differences.

### 2.2 Local snapshot observations

The page contains:

- `recaptcha__en.js.download` and `enterprise.js.download`.
- A `recaptcha-enterprise-ready-shim` that initializes `grecaptcha.enterprise.ready` and references `___grecaptcha_cfg`.
- A hidden `.grecaptcha-badge` with an anchor iframe titled `reCAPTCHA`.
- A hidden textarea named `g-recaptcha-response` with an id like `g-recaptcha-response-100000`.
- A second iframe titled `recaptcha challenge expires in two minutes`, loaded from `bframe.html`, distinct from the anchor frame.
- A normal page form for the image prompt; the snapshot does not expose enough application code to infer server-side acceptance from DOM alone.

The existing live logs add decisive evidence:

- `cb=called ... via grecaptcha-cfg` only proves that a callback path was invoked.
- `dialog_at_token=visible` proves the challenge was still displayed when injection began, not that Arena accepted it.
- `CAPTCHA_SOLVE status=solved` currently means local dialog disappearance.
- `CAPTCHA_JOB job=failed` proves generation failed afterwards.
- A page error appeared at 60.8 seconds and a token arrived at 65.8 seconds; that token was late and must not be counted as a successful generation recovery.

## 3. External research findings

### 3.1 Google reCAPTCHA Enterprise

Google’s website assessment documentation says the backend assessment is the authoritative verification point. Relevant fields include:

- `tokenProperties.valid`;
- `tokenProperties.invalidReason`;
- `tokenProperties.hostname`;
- `tokenProperties.action`;
- expected action matching;
- risk score and reasons;
- challenge result where applicable.

Google also documents that a token is single-use and expires after approximately two minutes. The client-side callback and hidden textarea are transport mechanisms, not proof of a successful backend assessment.

Sources:

- https://cloud.google.com/recaptcha/docs/create-assessment-website
- https://docs.cloud.google.com/recaptcha/docs/interpret-assessment-website

### 3.2 Provider task contract

The 2Captcha documentation distinguishes regular v2 and Enterprise task types. Enterprise tasks support `websiteURL`, `websiteKey`, `isInvisible`, optional `enterprisePayload`, and optional browser identity parameters. The task type must match the page integration; the presence of an Enterprise script or an Enterprise-looking iframe should be verified against the actual request/anchor data before changing classification.

Sources:

- https://2captcha.com/api-docs/recaptcha-v2-enterprise
- https://2captcha.com/api-docs/recaptcha-v2

This design does not recommend adding proxy/cookie/user-agent spoofing. Those fields are security-sensitive, can change the verification context, and would require explicit approval and a separate compliance review.

## 4. Mechanics inventory

### M1 — Enterprise bootstrap

**Observed:** Enterprise script and ready shim.  
**Detect:** script/grecaptcha presence only as diagnostic evidence, never as a challenge trigger.  
**Use:** classify the integration and capture the page URL/sitekey; do not treat script presence as proof that the current challenge is active.

### M2 — Badge/anchor iframe

**Observed:** hidden `.grecaptcha-badge` and `iframe[title="reCAPTCHA"]`.  
**Detect:** distinguish a hidden badge from a visible challenge dialog. The existing detector intentionally excludes badge iframes.  
**Use:** retain as `anchor_present` evidence and capture the anchor source/query metadata in a privacy-safe form (host/path and parameter names, not tokens).

### M3 — Challenge/bframe iframe

**Observed:** iframe title contains `recaptcha challenge expires in two minutes`, loaded from `bframe.html`.  
**Detect:** distinguish challenge frame visibility/attachment from the anchor frame.  
**Use:** report challenge lifecycle: appeared, visible, detached, replaced, or still present after callback. Do not infer acceptance from detachment alone because page navigation/error can also detach it.

### M4 — Sitekey and integration mode

**Observed:** sitekey in the saved/live page and an Enterprise-style integration.  
**Detect:** collect key source (`iframe k`, data attribute, script fallback), iframe URL family, `size=invisible`, and any public action/enterprise payload names.  
**Use:** make task type a documented classification with evidence. If evidence conflicts, fail to a diagnostic/manual path rather than silently selecting a different provider product.

### M5 — Response fields

**Observed:** hidden `textarea[name="g-recaptcha-response"]`; live injection reported `fields=2` in the dialog and `fields=1` at document scope.  
**Detect:** count fields and record their scope, name/id shape, non-secret length, and whether values are cleared/replaced. Never log token contents.  
**Use:** field mutation is an injection signal only, not acceptance.

### M6 — Callback/configuration chain

**Observed:** callback invoked through `___grecaptcha_cfg` (`client:0`).  
**Detect:** report callback source, callback invocation result/error, and whether invocation threw.  
**Use:** callback invocation is a transition to `submitted_to_page`; it is not `accepted`.

### M7 — Page/application acceptance

**Observed:** the page can show a generation error after the callback, and a page error can predate a late token.  
**Detect:** page-error corpus, dialog state, submit/generation state, spinner state, network/page diagnostic where already available, output baseline, and navigation/document identity.  
**Use:** acceptance requires a bounded post-injection observation window with no fatal page error and evidence that the blocked operation resumed. If the page is already failed, classify the token as stale.

### M8 — Generation output

**Observed:** the existing runner uses baseline/output detection and `Wait New Output`.  
**Detect:** preserve the existing baseline and output verification gate.  
**Use:** final job success must come from output success, not from CAPTCHA disappearance.

### M9 — Token lifetime and single use

**Research:** Google documents one-use tokens with approximately two-minute expiry.  
**Detect:** token age from provider receipt to injection/submit; never retry the same token.  
**Use:** if the page is stale or generation has failed, abandon the token and request a fresh page/challenge only through normal user-authorized flow.

### M10 — Browser/page identity changes

**Risk:** navigation, new chat reset, document replacement, or a challenge from a prior request can make a token irrelevant.  
**Detect:** document URL, page/document identity if safely available, correlation id, sitekey, and challenge instance id at detection/injection.  
**Use:** reject injection when the page identity or challenge instance no longer matches, and record `stale_page`.

## 5. Proposed state machine

```text
NONE
  -> DETECTED
  -> TASK_SUBMITTED
  -> PROVIDER_PROCESSING
  -> TOKEN_READY
  -> INJECTION_ATTEMPTED
  -> CALLBACK_ATTEMPTED
  -> ACCEPTANCE_OBSERVING
  -> CAPTCHA_ACCEPTED
  -> GENERATION_OBSERVING
  -> OUTPUT_COMPLETED

Any active state -> PAGE_ERROR
Any active state -> PAGE_NAVIGATED_OR_STALE
TOKEN_READY + expired/identity mismatch -> TOKEN_STALE
CALLBACK_ATTEMPTED + dialog gone but page error -> PAGE_ERROR (not solved)
CALLBACK_ATTEMPTED + dialog persists -> NOT_ACCEPTED
```

Terminal outcomes must be separate:

- `output_completed` — whole job succeeded;
- `captcha_accepted_generation_pending` — challenge appears accepted, generation still running;
- `page_error` — page reported a generation/application error;
- `not_accepted` — callback attempted but challenge remains or site rejects it;
- `token_stale` — page/challenge changed or error preceded token;
- `provider_failed`, `stopped`, `manual`.

The existing `CAPTCHA_SOLVE` line should describe the CAPTCHA encounter. `CAPTCHA_JOB` should remain the authoritative joined line for the image job. A CAPTCHA line must never claim the whole image job succeeded.

## 6. Implementation plan

### Phase A — Evidence-only probe expansion

Add a small, pure probe result with:

- `integration`: `enterprise|v2|unknown` plus evidence source;
- `anchor_present`, `anchor_visible`;
- `challenge_present`, `challenge_visible`, challenge title/source family;
- response field count and scope;
- sitekey source;
- page URL/document identity;
- public action/payload key names only;
- semantic `dom` label retained.

Do not change solving behavior in Phase A. Add real-DOM harness tests for badge-only, challenge iframe, detached challenge, response field, and mixed dialog/page states (RULE 8, RULE 21).

### Phase B — Correct lifecycle semantics

- Rename/clarify local `solved` as `captcha_accepted_candidate` until post-injection observation completes.
- Make page errors terminal for the current solve.
- Stop polling and best-effort delete the provider task when a fatal page error appears.
- Prevent a token that arrives after `page_error_at` from being injected.
- Prevent a page-error path from applying the normal CAPTCHA penalty.
- Preserve the existing fail-open/manual behavior for probe failures.

### Phase C — Acceptance and recovery gate

- After injection/callback, observe for a bounded interval.
- Require no fatal page error, matching page identity, and either resumed generation or output progress.
- If the challenge disappears but generation fails, report `not_accepted` or `page_error`, not `solved`.
- Keep the existing baseline/output verification as the final success gate.
- Ensure recovery/new-chat reset cannot reuse the old token or encounter report.

### Phase D — Task-type verification

Using only public page evidence and the saved state, compare:

- Enterprise script and request family;
- anchor URL parameters;
- data-sitekey/iframe key;
- normal-v2 `/recaptcha/api2/` versus Enterprise request family;
- whether an action or Enterprise payload is present.

Add a diagnostic log such as `integration_evidence=...`; do not silently switch task types. A task-type change requires tests and a live controlled run.

### Phase E — Observability and metrics

Extend the existing two-line schema with bounded, non-secret fields:

```json
{
  "integration": "enterprise",
  "anchor": {"present": true, "visible": false},
  "challenge": {"present": true, "visible": true, "title": "..."},
  "response_fields": {"count": 2, "scope": "dialog"},
  "callback": {"attempted": true, "source": "grecaptcha-cfg", "called": true},
  "acceptance": {"state": "page_error", "at_s": 60.8},
  "stale": {"reason": "page_error_before_token", "at_s": 60.8}
}
```

Do not add token values, cookies, headers, IPs, full iframe URLs with secrets, or fingerprinting data to logs.

## 7. Required tests before production use

1. Badge-only page is not a challenge.
2. Challenge iframe and anchor iframe are distinguished.
3. Hidden response textarea is discovered without treating its presence as acceptance.
4. Callback called + dialog gone + no error remains an acceptance candidate, not whole-job success.
5. Callback called + page error becomes `page_error`, not `solved`.
6. Page error before token makes the token stale and prevents injection.
7. Page identity/navigation change prevents stale injection.
8. Dialog persists after callback becomes `not_accepted`.
9. Output success is required for `CAPTCHA_JOB job=completed`.
10. Provider task is stopped/deleted on page error.
11. Reused controller reports are cleared and drained exactly once.
12. Existing captcha, runner, node, quality-gate, and radon suites remain green.

## 8. RULE 18 / RULE 16 recheck

### RULE 18 — ideal sizes

Keep the implementation split by responsibility:

- probe extraction: one JS probe module;
- immutable signal dataclass;
- lifecycle transitions in a small solver/service layer;
- page/output acceptance in the existing runner/controller layer;
- report formatting in existing report helpers.

Do not put network polling, DOM extraction, acceptance policy, and JSON formatting into one function. Prefer a state object over adding parameters. Keep evidence fields grouped and bounded. Use comments only for invariants and security decisions.

### RULE 16 — quality gates

Every production phase must run:

```text
pytest tests/ -q -p no:cacheprovider --ignore=tests/integration
npm run test:js
python tools/verify_quality.py --changed --allow-legacy
python -m radon cc <changed-production-files> -s
```

Acceptance thresholds:

- zero quality-gate fails;
- new/changed production code no worse than B complexity;
- real probe tests execute the actual JS through the harness;
- lifecycle tests cover page error, stale token, callback-only, and output-success paths;
- docs/SYSTEM_OF_RECORD and docs map updated;
- final review checks RULES 8, 16, 18, 20, 21, and 22.

## 9. Rollout and live-run checklist

Before enabling behavior changes:

1. Save one fresh page state with the exact path supplied by the user.
2. Run Phase A in diagnostic-only mode.
3. Capture one normal run and one generated-page-error run.
4. Verify the report ordering: detect → token → callback → acceptance/page error → job.
5. Verify no late token is injected after page error.
6. Verify no CAPTCHA penalty is applied for a stale/page-failed token.
7. Only then enable Phase B/C behavior changes.

## 10. Open decisions requiring explicit approval

- Whether to add a new post-callback acceptance wait or rely on existing `Wait New Output` as the acceptance gate.
- Whether to change the Enterprise/regular-v2 classification when evidence conflicts.
- Whether to implement provider `reportIncorrect` for `not_accepted`; this affects money/refunds and remains intentionally out of scope until approved.
- Whether the saved exact user artifact should be copied into the repository for fixture testing; large HTML should remain outside Git unless needed by the test convention.

## 11. Research source notes

The page snapshot is local evidence, not a guarantee that every live session has the same DOM. Dynamic challenge frames, scripts, and application state must be probed in the live authorized tab. External findings above are used only for token lifecycle, assessment semantics, and provider task contract; they do not authorize bypassing or evading site controls.
