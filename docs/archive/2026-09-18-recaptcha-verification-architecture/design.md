# CAPTCHA verification architecture — acceptance-gated generation

**Date:** 2026-09-18  
**Status:** design complete; implementation follows this document in the same work session  
**Supersedes for implementation detail:** `2026-09-18-recaptcha-page-mechanics/research-design.md`  
**Scope:** user-authorized Arena image generation pages, existing 2Captcha opt-in path, and the existing baseline/output runner

## 1. Problem statement

The current flow labels an automatic solve `solved` when:

1. a provider token arrives;
2. response fields are filled;
3. a site callback is called; and
4. the CAPTCHA dialog disappears.

The live run disproved that as a success definition. Arena showed:

- generation error at 60.8 seconds;
- token arrival at 65.8 seconds;
- dialog already gone;
- late token injected anyway;
- local CAPTCHA status reported `solved`;
- final job reported `failed`.

The architecture must separate CAPTCHA mechanics from page/application acceptance and from final image-generation success. A callback is an attempt, not proof of server acceptance.

## 2. Design goals and non-goals

### Goals

- Observe all relevant page layers without relying on one selector.
- Stop a solve when the page enters a fatal generation error.
- Never inject a token after its challenge/page is stale.
- Report a CAPTCHA attempt honestly and report the final job separately.
- Apply CAPTCHA cooldown penalty only for an accepted CAPTCHA/manual resolution, not a stale or page-failed attempt.
- Preserve the existing manual fallback, stop semantics, baseline/output gate, and recovery behavior.
- Keep all token/cookie/header/identity secrets out of logs.
- Use small, testable components compatible with RULES 8, 16, 18, 20, 21, and 22.

### Non-goals

- No browser fingerprint spoofing.
- No proxy/cookie/user-agent impersonation.
- No attempt to evade Google/Arena risk controls.
- No automatic `reportIncorrect` provider feedback in this change; that remains money-affecting and requires explicit approval.
- No claim that DOM disappearance proves backend acceptance.

## 3. Architecture

### 3.1 Four boundaries

```text
PageProbe       -> CaptchaSignal / PageEvidence
ProviderSolver  -> SolveOutcome (token and callback lifecycle)
AcceptanceGate  -> VerificationOutcome (page acceptance vs error/stale)
JobRunner       -> CAPTCHA_JOB (final generation result/output)
```

Each boundary has one responsibility:

- **PageProbe:** read public, non-secret DOM/page evidence.
- **ProviderSolver:** create/poll/delete the provider task and perform one browser injection attempt.
- **AcceptanceGate:** observe page state after/during solving and decide `accepted_candidate`, `page_error`, `stale`, or `not_accepted`.
- **JobRunner:** decide whether the image job completed from its existing output/baseline result.

JSON formatting remains in service/runner report helpers, not in probe or solver.

### 3.2 State model

```text
NONE
  -> DETECTED
  -> TASK_SUBMITTED
  -> PROVIDER_PROCESSING
  -> TOKEN_READY
  -> INJECTION_ATTEMPTED
  -> CALLBACK_ATTEMPTED
  -> ACCEPTANCE_OBSERVING
  -> CAPTCHA_ACCEPTED_CANDIDATE
  -> GENERATION_OBSERVING
  -> OUTPUT_COMPLETED

Any active state -> PAGE_ERROR
Any active state -> PAGE_STALE
TOKEN_READY + page error/identity mismatch -> TOKEN_STALE
CALLBACK_ATTEMPTED + dialog persists -> NOT_ACCEPTED
CALLBACK_ATTEMPTED + dialog gone + page error -> PAGE_ERROR
```

`CAPTCHA_ACCEPTED_CANDIDATE` is deliberately not `job completed`. Only output verification can produce `OUTPUT_COMPLETED`.

### 3.3 Terminal outcome vocabulary

`SolveOutcome.status` will use these stable values:

- `none`: no challenge;
- `solved`: CAPTCHA acceptance candidate, with no observed page error during the bounded solve;
- `auto_failed`: provider/injection/not-accepted failure, manual fallback may continue;
- `page_error`: fatal page/application error appeared while solving;
- `token_stale`: token arrived after page error or page/challenge identity changed;
- `stopped`: operator/job stop;
- `manual`: user cleared the challenge.

The report `status=solved` must be understood as CAPTCHA-layer success candidate only. `CAPTCHA_JOB.job=completed` remains the whole-job success.

## 4. Evidence contract

### 4.1 `CaptchaSignal` additions

Add bounded evidence fields:

```python
integration: str                 # enterprise | v2 | unknown
anchor_present: bool
anchor_visible: bool
challenge_present: bool
challenge_visible: bool
challenge_title: str              # bounded, diagnostic text only
challenge_src: str                # host/path or safe classification, not full query
response_fields: int
response_scope: str               # dialog | document | none
sitekey_source: str               # iframe_k | data-sitekey | script | none
page_identity: str                # stable non-secret document/navigation fingerprint
```

Keep `dom`, `kind`, `sitekey`, and `is_invisible`. Public sitekey remains allowed as existing behavior; token values remain prohibited.

### 4.2 Probe behavior

The real JS probe must:

1. find candidate dialog and page-level iframe independently;
2. exclude the always-present hidden badge from challenge visibility;
3. distinguish anchor iframe from challenge iframe;
4. find response textareas and report count/scope only;
5. classify Enterprise/v2 from observable request/frame/script evidence;
6. return safe URL classifications, not query secrets;
7. return page identity based on URL/document state available to the page;
8. never click, submit, mutate fields, or call callbacks.

Probe failure remains fail-open (`probe_error`), per RULE 9. A field’s presence is evidence, never acceptance.

## 5. Lifecycle ownership

### 5.1 `SolvePlan`

`SolvePlan` owns one provider attempt and keeps all mutable timestamps/evidence:

- detection/solve start monotonic time;
- baseline page-error corpus and first error timestamp/text;
- token timestamp/fingerprint;
- pre-injection dialog state;
- page identity at detection and token receipt;
- injection result/callback summary;
- polls/task id;
- cancellation/staleness reason.

Keep it as the parameter bundle to satisfy RULE 16 and RULE 18.

### 5.2 Page-error watcher

The existing `_note_page_error` is upgraded from telemetry to a terminal signal:

- baseline is captured on the first scan;
- a new matching fatal error stamps `page_error_at` and `page_error`;
- the poll loop returns `page_error` immediately;
- the provider task is deleted best effort;
- no token is injected after this point;
- the service falls back only when manual recovery is meaningful; otherwise the runner preserves the page-error result.

The error watcher must not treat an error already present before this solve as a new mid-solve error.

### 5.3 Identity/staleness watcher

At detection and token receipt, compare:

- page URL;
- page identity/document marker;
- sitekey and integration classification;
- challenge evidence where available.

Mismatch returns `token_stale` and deletes the provider task. A vanished dialog alone is not a mismatch because a successful callback can close it; it becomes stale when combined with page error/navigation/identity mismatch.

### 5.4 Acceptance gate

After injection:

1. re-read evidence and page-error state;
2. invoke the existing continue path only as a best-effort page action;
3. observe for a bounded grace period;
4. if page error appears, return `page_error`;
5. if identity changes, return `token_stale`;
6. if dialog remains, return `auto_failed/not_accepted`;
7. if dialog disappears with no error, return `solved` as CAPTCHA candidate only.

The gate does not wait for the full image output; `WAIT_OUTPUT` and the existing baseline/output detector remain the final job acceptance gate. This avoids coupling the CAPTCHA solver to a long generation timeout.

## 6. Service and runner behavior

### Auto path

- `_try_auto` emits one `CAPTCHA_SOLVE` for every terminal solver outcome.
- Penalty is applied only for `solved` or successful `manual`, never `page_error` or `token_stale`.
- `page_error` is returned to the runner as a meaningful failure, not silently converted into a manual wait against a dead page.
- `token_stale` may use existing bounded recovery only when the page is still usable; otherwise the job fails with the original page error.

### Manual path

- A user-cleared challenge remains `manual`.
- A page error while manual waiting becomes `page_error`, not manual success.
- Manual penalty applies only when the dialog was actually cleared and the page did not enter an error state.

### Job path

`CAPTCHA_JOB` remains the final join line:

```json
{
  "job": "completed|failed|stopped",
  "error": "...",
  "page_error": "..."
}
```

`CAPTCHA_SOLVE.status=solved` must never force `CAPTCHA_JOB.job=completed`. Existing output/baseline verification is authoritative.

## 7. Report schema additions

Preserve the two-line schema and add bounded evidence:

```json
{
  "integration": "enterprise",
  "anchor": {"present": true, "visible": false},
  "challenge": {"present": true, "visible": true, "title": "recaptcha challenge expires in two minutes"},
  "response_fields": {"count": 2, "scope": "dialog"},
  "sitekey_source": "iframe_k",
  "page_identity": "safe-short-fingerprint",
  "callback": {"attempted": true, "source": "grecaptcha-cfg", "called": true},
  "acceptance": {"state": "page_error", "at_s": 60.8},
  "stale": {"reason": "page_error_before_token", "at_s": 60.8}
}
```

Never log tokens, cookies, full query strings, headers, IPs, or provider credentials. Truncate diagnostic text and URL components.

## 8. Implementation steps, in order

### Step 1 — Data contracts

- Extend `CaptchaSignal` and `SolveOutcome` with grouped evidence and acceptance fields.
- Add enums/constants or stable string helpers without introducing a large framework.
- Preserve `from_result` backward compatibility.
- Add unit tests for malformed/missing evidence.

### Step 2 — Real page probe

- Extend `detect.js` with anchor/challenge/response evidence.
- Add safe URL classification and page identity.
- Run exact JS through the existing node harness.
- Add badge-only, challenge, dialog, page iframe, hidden response, mixed-frame, and malformed DOM tests.

### Step 3 — Terminal error/stale polling

- Make `_note_page_error` return a structured observation.
- Check stop, page error, and identity before every provider poll and before token injection.
- Return/delete on page error and stale identity.
- Add solver tests proving no injection occurs after page error and late tokens are not solved.

### Step 4 — Post-injection acceptance gate

- Replace the current boolean-only verification with a bounded structured result.
- Preserve callback/field diagnostics.
- Classify dialog-gone plus no-error as `solved` candidate.
- Classify dialog-gone plus page error as `page_error`.
- Classify dialog-persisting as `not_accepted`.
- Add solver tests for every branch.

### Step 5 — Service penalty/fallback semantics

- Stop applying penalty on page-error/stale outcomes.
- Keep exactly-once report emission.
- Prevent page-error auto outcomes from becoming misleading manual waits.
- Add service tests for auto solved, auto page error, stale token, manual solved, stopped, and no penalty cases.

### Step 6 — Runner/job recovery

- Preserve page error through `WAIT_OUTPUT` and `CAPTCHA_JOB`.
- Ensure recovery does not reuse a stale token or encounter.
- Add runner tests for page error before token, late token, and output failure after CAPTCHA candidate.

### Step 7 — Documentation and live diagnostic run

- Update SOR and docs map only after behavior is verified.
- Run one diagnostic-only live attempt before enabling any task-type change.
- Confirm reports show `page_error`/`token_stale` rather than false `solved` for the user’s observed sequence.

## 9. Test matrix

| Scenario | Expected solver | Expected penalty | Expected job |
|---|---|---:|---|
| token + callback + dialog clears + no error | `solved` candidate | yes only if job/manual resolution completes | output decides |
| page error before token | `page_error`/`token_stale` | no | failed with page error |
| page error after injection | `page_error` | no | failed with page error |
| dialog persists after callback | `auto_failed/not_accepted` | no | manual fallback or failed |
| page identity changes | `token_stale` | no | failed/recovery path |
| provider timeout/API failure | `auto_failed` | no | manual fallback |
| user clears challenge and page healthy | `manual` | yes | output decides |
| output fails after CAPTCHA candidate | CAPTCHA candidate remains; job failed | no additional CAPTCHA penalty | failed |
| badge only | `none` | no | normal flow |
| stop during provider wait | `stopped` | no | stopped |

## 10. Quality and design recheck

### RULE 18 — ideal sizes

Do not create a monolithic “verification manager.” Keep these leaf boundaries:

- `signals.py`: data only;
- `detect.js`: page observation only;
- `solver.py`: provider and injection lifecycle only;
- `service.py`: policy/penalty/report orchestration only;
- runner/controller: output/job acceptance only.

Use `SolvePlan` and structured observation objects rather than growing function signatures. Keep probe result fields grouped. Keep comments for invariants and security decisions, not line-by-line narration.

### RULE 16 — quality gates

After every production change batch, run:

```text
pytest tests/ -q -p no:cacheprovider --ignore=tests/integration
npm run test:js
python tools/verify_quality.py --changed --allow-legacy
python -m radon cc <changed-production-files> -s
```

Required result:

- zero quality-gate fails;
- new/changed production code at B or better;
- real probe tests through the harness;
- lifecycle tests cover all rows in the table;
- no pre-existing tests regress;
- docs map/SOR updated;
- final diff reviewed for RULES 8, 9, 16, 18, 20, 21, and 22.

## 11. Rollback/stop condition

If live evidence shows the page integration is not the assumed Enterprise/v2 model, stop before changing task type. Keep diagnostic-only evidence and request approval for a new provider/task contract. If any change would require spoofing identity, cookies, proxies, or telemetry, stop; it is outside this design.
