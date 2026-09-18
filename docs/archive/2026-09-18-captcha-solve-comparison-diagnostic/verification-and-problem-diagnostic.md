# CAPTCHA SOLVE COMPARISON — VERIFICATION AND PROBLEM DIAGNOSTIC

**Date:** 2026-09-18  
**Status:** evidence-gated diagnostic prepared before implementation  
**Scope:** user-authorized Arena pages; compare manual-pass, bot-pass, and bot-fail sessions  
**Safety boundary:** diagnose integration, lifecycle, page-state, timing, callback, and server-result differences. Do not collect behavioral biometrics, spoof fingerprints, conceal automation, replay credentials, or weaken anti-bot controls.

## 1. Problem statement

The automatic CAPTCHA path can report a local solve attempt while the page does not accept that attempt or the image job still fails. A human solve may succeed from an apparently similar visible challenge. The required analysis must determine the **first evidence-backed divergence** between successful manual sessions and failed automatic sessions, then map that divergence to a reproducible correction.

A CAPTCHA solve has several independent boundaries:

1. challenge detected;
2. provider task created and token returned;
3. challenge/page identity still current;
4. token delivered into the correct response field;
5. the page's correct callback/continuation path invoked;
6. CAPTCHA dialog cleared;
7. page/backend accepted the transition;
8. generation resumed and produced a verified output.

Dialog disappearance is not proof of steps 7 or 8. The analysis must not collapse these boundaries into one `solved` flag.

## 2. Evidence availability — mandatory limitation

No recording directory exists in this repository workspace at the time of this audit:

```text
config/captcha_recordings/  -> not present
```

The recordings are intentionally local and git-ignored. Therefore this document **does not claim an empirical root cause for a specific recorded failure yet**. Exact session conclusions require selected recording folders from the machine where they were captured.

Required evidence set:

- at least one user-confirmed `manual + passed` session;
- preferably one `bot + passed` session;
- at least one `bot + failed` session;
- sessions should use the same page route, CAPTCHA integration/kind, app build, and similar page state;
- each session folder must retain `manifest.json`, `events.jsonl`, and all `snapshots/*.json.gz` files.

Until those folders are available, findings below are separated into:

- **confirmed recorder/comparison defects** — proven from source/schema inspection;
- **candidate solve causes** — plausible mechanisms with explicit evidence tests, not conclusions.

## 3. Ground-truth model required for valid comparison

Current evidence has three related but different concepts:

| Concept | Current field | Owner | Meaning |
|---|---|---|---|
| Attempt actor | `actor_label=unknown|bot|manual` | user | Who performed the solve |
| Runtime method | `method` | application | Path used by the final outcome |
| Runtime outcome | `outcome/status` | application | What the application inferred |

This is not sufficient for the user's requested manual labels of both actor and success. A bot attempt that fails and then falls back to a person can end with `method=manual`, while its earlier automatic failure exists only as a state event. Likewise, the application may call dialog disappearance `solved` even if the user knows the page rejected it.

The comparison dataset needs two independent user-owned labels:

```text
actor_label:  unknown | bot | manual | mixed
result_label: unknown | passed | failed
```

`method` and `outcome` must remain immutable observed evidence. They must not replace ground truth. `mixed` is important for “bot failed, then user solved” sessions; otherwise those sessions contaminate either the manual or bot cohort.

## 4. Confirmed problems in the current comparison evidence

### P1 — The A/B viewer reads fields that recordings do not write

**Severity:** critical for diagnosis  
**Confidence:** confirmed from source

Recorder events are written as flattened objects:

```json
{
  "seq": 4,
  "at": "...Z",
  "offset_ms": 1200,
  "kind": "network_response",
  "request_id": "...",
  "status": 200
}
```

The UI reads:

```javascript
event.at_ms
event.payload
```

Neither field exists. The practical result is a timeline that displays `0ms`, the event kind, and no event details. Important evidence such as mutation changes, network status, auto-attempt reason, `dialog_at_token`, and injection result is hidden.

**Required correction:** use `offset_ms` and render a bounded copy of all non-envelope event fields, or change the read model to explicitly provide `offset_ms` and `payload`.

### P2 — Snapshot timestamp schema also disagrees with the reader

**Severity:** high  
**Confidence:** confirmed from source

Snapshots write `at` and the recorder knows the event offset, but `EvidenceReader` asks for `at_ms`. The comparison cannot accurately align the displayed DOM checkpoint to the solve timeline.

**Required correction:** persist and expose both UTC `at` and monotonic `offset_ms` on every checkpoint.

### P3 — The viewer compares only the latest snapshot

**Severity:** high  
**Confidence:** confirmed from source

The file store keeps up to 25 checkpoints, but `EvidenceReader` returns only the latest snapshot. The first divergence usually occurs before the final state. Two final pages can look similar despite different token delivery, callback, error, or transition histories.

**Required correction:** expose a bounded checkpoint index and compare aligned checkpoint pairs: detected, token-ready/pre-injection, injection/callback, dialog-cleared, terminal.

### P4 — There is no computed DOM or timeline diff

**Severity:** high  
**Confidence:** confirmed from source

Current A/B panes show text independently. They do not normalize paths, align milestones, or highlight additions/removals/attribute changes. The operator must manually scan large HTML excerpts.

**Required correction:** produce a deterministic comparison report containing common events, manual-only events, bot-only events, changed DOM paths, network sequence differences, first divergence, and truncation warnings.

### P5 — Cross-origin challenge-frame DOM is not recorded

**Severity:** high, but expected browser boundary  
**Confidence:** confirmed from design and snapshot probe

Snapshots clone only the parent document. reCAPTCHA challenge internals usually live in cross-origin iframes, so the recording cannot see checkbox/challenge internals or a person's actions inside that iframe. This means parent-DOM equality does not prove equivalent CAPTCHA state.

**Safe correction:** do not bypass iframe isolation and do not record mouse trajectories. Record only allowed semantic evidence already visible to CDP/page integration: frame lifecycle classification, challenge/anchor presence, safe frame host/path, page response-field count/scope, challenge identity change, and parent-page acceptance signals.

### P6 — Critical solver milestones are incomplete in the recording

**Severity:** critical for exact root-cause attribution  
**Confidence:** confirmed from recorder/source

The recording includes `recording_started`, a terminal state, and one `auto_attempt_finished` note. It does not persist the full structured solver evidence already available elsewhere, including all of:

- task-created offset;
- poll count and token-ready offset;
- page/challenge identity at detection and token receipt;
- response-field count/scope before and after injection;
- callback source and whether it was called/threw;
- continue-button result;
- first page-error offset/text classification;
- dialog-clear offset;
- acceptance-candidate offset;
- final job/output result joined by encounter id.

Without these milestones, several root causes produce the same final `bot failed` record.

**Required correction:** persist bounded, token-free semantic milestones from `SolveOutcome`/solve plan. Never persist raw tokens, cookies, headers, POST data, or provider API credentials.

### P7 — Actor and result labels cannot represent mixed fallback sessions

**Severity:** high for cohort validity  
**Confidence:** confirmed from manifest/UI schema

Only `unknown|bot|manual` can be manually labeled. There is no independent user-owned passed/failed label and no `mixed` actor. Automatic outcome is not reliable ground truth for this research question.

**Required correction:** add `result_label` and `mixed`, preserve label history timestamp, and exclude unknown/mixed sessions from pure manual-vs-bot aggregate comparisons unless analyzing fallback explicitly.

### P8 — Network evidence is broad but not semantically correlated

**Severity:** medium/high  
**Confidence:** confirmed from collector schema

The recorder stores safe host/path, method, resource type, status, cache flag, failures, and bounded redacted textual bodies. It does not classify which request corresponds to challenge bootstrap, verification, page acceptance, generation resume, or output. A large page can generate hundreds of unrelated events.

**Required correction:** derive a safe semantic classification from host/path/resource type and align request/response pairs by request id. Keep URL queries, headers, cookies, and form bodies excluded.

### P9 — Network event handoff crosses event-loop threads unsafely

**Severity:** medium/high for evidence completeness  
**Confidence:** source-level risk; runtime loss not yet proven

`NetworkCollector.on_event()` can run on the CDP websocket loop while writing directly to an `asyncio.Queue` owned/drained by another loop. `asyncio.Queue` is not a cross-thread transport. Missing or delayed network events could create false differences between recordings.

**Required correction:** use a thread-safe deque protected by a lock, or schedule queue insertion on the recorder's owner loop with `call_soon_threadsafe`. Add a worker-thread regression test and explicit dropped-event count.

### P10 — Truncation can invalidate comparisons without blocking conclusions

**Severity:** medium  
**Confidence:** confirmed from limits

Sessions cap events, mutation queue, snapshots, DOM length, and bodies. The manifest records truncation flags, but the comparison UI does not prominently invalidate or downgrade conclusions when evidence is truncated.

**Required correction:** show an “incomplete evidence” banner and prohibit a high-confidence root-cause result if either compared session lost the relevant evidence class.

## 5. Candidate causes of bot failure and exact verification signatures

These are ordered by likely diagnostic value. They are hypotheses until matched against recordings.

### H1 — Token arrives after the page/challenge is no longer valid

**Mechanism:** provider latency exceeds page patience, a page error appears, navigation occurs, or challenge identity changes before injection.

**Bot-fail signature:**

- long detection → token-ready interval;
- `dialog_at_token=gone`, page error before token, or changed page/challenge identity;
- no comparable delay/error in manual-pass sessions;
- verification/generation request absent or rejected after late injection.

**Safe fix:** abort and delete the provider task when page error or identity mismatch occurs; never inject stale tokens; retry only through the site's normal fresh-challenge flow. Do not attempt to extend or defeat challenge validity.

### H2 — Token is delivered to the wrong response field or scope

**Mechanism:** badge and active dialog expose multiple response fields; the integration expects the challenge-scoped field/client, not a stale badge field.

**Bot-fail signature:**

- token ready while challenge remains current;
- response-field count/scope differs from manual transition;
- injection reports fields changed, but expected callback/verification transition does not occur;
- dialog persists or page reports not accepted.

**Safe fix:** bind delivery to the detected active challenge integration and verify post-delivery semantic state. Treat “field changed” as an attempt, never acceptance.

### H3 — Wrong callback/client is invoked or callback throws

**Mechanism:** token field update alone is insufficient; the site expects its active callback/client. A generic grecaptcha client search can select a badge or stale client.

**Bot-fail signature:**

- correct current challenge and timely token;
- callback source missing, stale, wrong-sitekey client, or exception;
- manual-pass shows a parent-page transition/request that bot-fail lacks;
- dialog may remain or disappear without backend acceptance.

**Safe fix:** use the callback associated with the active sitekey/challenge evidence, record callback source/result, and fail closed to manual handling when association is ambiguous. Do not invoke unrelated page callbacks.

### H4 — CAPTCHA dialog disappearance is incorrectly treated as acceptance

**Mechanism:** UI closes locally, but the page/backend rejects verification or generation never resumes.

**Bot-fail signature:**

- callback called and dialog removed;
- no successful acceptance/generation transition matching manual-pass;
- a page error or failed verification response follows;
- manifest says `solved` while user `result_label=failed` or final job fails.

**Safe fix:** rename this state internally to `accepted_candidate`; require page-error-free acceptance evidence and preserve final output verification as the job authority.

### H5 — Required page continuation is missing, premature, or disabled

**Mechanism:** after verification, the page expects a normal Continue/Verify/Submit transition, or enables it asynchronously. Bot clicks too early, does not click, or clicks a stale element.

**Bot-fail signature:**

- token/callback path succeeds;
- manual-pass has a later button-state mutation and acceptance request;
- bot-fail lacks that transition or records disabled/no action;
- no immediate page error or identity mismatch.

**Safe fix:** observe the site's normal enabled state, invoke at most the intended continuation once, and verify the expected subsequent page transition. Do not add synthetic human behavior.

### H6 — Wrong CAPTCHA integration/task classification or sitekey context

**Mechanism:** Enterprise/v2, visible/invisible mode, active sitekey, or page URL context supplied to the provider does not match the active challenge.

**Bot-fail signature:**

- bot-fail grouping differs in `kind`, integration, sitekey source, invisibility, or challenge identity from manual-pass;
- provider returns a token but active page evidence does not transition;
- repeated failures cluster by one classification.

**Safe fix:** create a task only from the active, visible challenge's verified public integration metadata; reject ambiguous/no-sitekey cases to manual handling.

### H7 — Page error occurs independently of CAPTCHA delivery

**Mechanism:** generation request already failed or timed out before solve completion. Solving the visible challenge cannot revive a dead operation by itself.

**Bot-fail signature:**

- page error precedes token/injection;
- both manual and bot records may clear the dialog, but only sessions with an explicit normal resubmit/revival produce output;
- CAPTCHA-layer evidence is otherwise equivalent.

**Safe fix:** preserve the original page error, stop the stale solve, and use the application's existing bounded normal retry/new-request flow. Do not classify this as provider token incorrectness.

### H8 — Recording/runtime concurrency drops evidence or disconnects CDP

**Mechanism:** cross-loop/thread event handling interrupts recording or command replies, making a successful or failed sequence incomplete.

**Bot-fail signature:**

- `interrupted`, missing final snapshot, event sequence gaps, CDP disconnect warnings, or truncation;
- behavior cannot be reproduced when recorder is disabled;
- no reliable acceptance conclusion can be drawn from the incomplete session.

**Safe fix:** correct thread-safe event delivery and rerun. Never diagnose page behavior from a structurally incomplete recording.

## 6. Comparison procedure

### Step 1 — Validate each session

Reject or downgrade sessions when:

- manifest is still `recording` or `interrupted`;
- actor/result labels are unknown;
- evidence is truncated in a relevant class;
- initial or final checkpoint is absent;
- event sequence has gaps or non-monotonic offsets;
- app build/integration/route differs materially;
- a mixed bot→manual fallback is placed in a pure cohort.

### Step 2 — Build cohorts

Use three cohorts rather than only two:

- **MP:** manual + passed;
- **BP:** bot + passed;
- **BF:** bot + failed.

BP is essential. A difference shared by BP and BF is unlikely to explain failure. A difference shared by MP and BP but absent in BF is a strong candidate success condition.

Pair exact sessions first, then aggregate only after pair-level validation. Recommended minimum for aggregate claims: three valid sessions per cohort.

### Step 3 — Normalize and align milestones

Align by semantic milestone, not event sequence number or wall clock:

```text
detected
challenge_current
task_created                 [bot only]
token_ready                  [bot only]
pre_injection
response_field_delivery      [bot only]
callback_or_manual_clear
dialog_cleared
page_acceptance_candidate
generation_resumed
output_verified | page_error | timeout
```

Manual sessions legitimately lack provider milestones. Compare their challenge-clear → acceptance → output path against the equivalent bot path.

### Step 4 — Compute four evidence diffs

1. **State diff:** milestone existence, order, and duration.
2. **DOM diff:** normalized changed paths/attributes/text around aligned milestones.
3. **Network diff:** ordered semantic endpoint classes, methods, statuses, failures, and durations.
4. **Outcome diff:** runtime outcome vs user ground truth vs final job result.

Ignore unstable IDs, timestamps, generated CSS classes, opaque values, and redacted placeholders. Never interpret missing redacted secrets as a behavioral difference.

### Step 5 — Identify the first divergence

The root-cause candidate is the earliest divergence that:

- appears in BF;
- does not appear in matched MP/BP;
- occurs before the failure;
- has a plausible causal mechanism;
- reproduces across sessions or in a controlled test.

Later differences are consequences until proven otherwise.

### Step 6 — Score conclusions

| Confidence | Requirement |
|---|---|
| Confirmed | Direct event/checkpoint evidence plus reproduction after targeted correction |
| High | Same first divergence in ≥3 BF sessions and absent in valid MP/BP controls |
| Medium | One strong pair with complete evidence and a plausible mechanism |
| Low | Incomplete/truncated evidence or timing correlation only |
| Unknown | Required evidence missing |

## 7. Required comparison output format

Every generated report must contain:

### Session matrix

| Session | Actor label | Result label | Runtime method/outcome | Route/kind | Complete? |
|---|---|---|---|---|---|

### Common successful sequence

Events and transitions present in both MP and BP, including timing ranges.

### First failed divergence

```text
Milestone:
BF evidence:
Matched MP/BP evidence:
Why causal rather than consequential:
Confidence:
```

### Root cause

One precise statement, or “not proven” when evidence is insufficient. Do not say “bot behavior differs” without naming the integration/page transition.

### Fix proposal

- smallest responsible component;
- exact state/contract change;
- no fingerprint/behavioral-evasion mechanism;
- regression test;
- success and rollback criteria.

## 8. Verification plan for any fix

A proposed fix is accepted only when all are true:

1. unit test reproduces the divergent state and fails before the fix;
2. recorder schema and A/B read model tests pass;
3. one fresh bot session reaches the missing success milestone;
4. user marks the fresh result independently;
5. final page/output result agrees with the user result label;
6. no token, header, cookie, POST body, credential, or local sensitive value is persisted;
7. manual fallback remains functional;
8. CDP/recording failures remain fail-open and cannot alter solve outcome;
9. full Python/JavaScript and RULE 16 quality gates pass.

## 9. Implementation order after evidence is supplied

1. Correct the comparison read-model schema (`offset_ms`, flattened payload, checkpoint offsets).
2. Add independent `result_label` and `mixed` actor support.
3. Make network event handoff thread-safe and expose evidence-loss counters.
4. Persist bounded semantic solve/acceptance/job milestones.
5. Add checkpoint index and deterministic DOM/timeline/network diff engine.
6. Import/select MP, BP, and BF sessions and generate the first evidence-backed report.
7. Implement only the smallest verified solve-lifecycle correction.
8. Record fresh controls and verify the correction against the acceptance criteria.

## 10. Evidence transfer checklist

Because `config/captcha_recordings/` is git-ignored, recordings must be supplied separately. Before sharing:

- select only the needed session folders;
- confirm labels and note which are MP/BP/BF;
- retain folder structure and gzip files;
- review sanitized HTML/text for page content you do not want to share;
- do not include `config/2captcha.json`, browser profile, cookies, logs containing credentials, or API keys.

Once valid session folders are available, this diagnostic can move from hypotheses to an exact pairwise and cohort report.

## 11. Current conclusion

The repository already records useful bounded evidence, but the present A/B viewer cannot display most event details because its field names do not match the persisted schema. The evidence also lacks independent passed/failed ground truth, mixed-session labeling, aligned checkpoints, complete semantic solver milestones, and a computed first-divergence report. These limitations must be corrected before claiming exactly why a bot session failed.

The highest-priority solve hypotheses to test are stale/late token delivery, active-challenge response-field mismatch, wrong callback/client association, false acceptance inferred from dialog disappearance, and missing page continuation. None is declared the cause of the user's recordings until those recordings are available and pass the integrity checks above.
