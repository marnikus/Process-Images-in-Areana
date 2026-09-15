# Steps 7–9 — offline implementation checkpoint

**Update:** [Offline Steps 10–12](STEPS-10-12.md) now extend the lifecycle with
validated local save/recovery and read-only UI evidence. The description below
records the original Steps 7–9 scope; its Step 10 deferrals are historical.

Date: 2026-09-15. The owner chose offline/testable work while live upload and
submission remain disabled. These are **offline portions, not live acceptance of
Steps 7–9**. No production adapter, fabricated site selectors, desktop execution
commands, real upload, Send or generation were added. Steps 10–12 remain pending.

## 7: retained visual runner and fixture contract

`automation/visual.py` packages and adapts the actual legacy `dom_highlight.py`
helpers, FIND body, CLICK body and wrapper. `ui/visual/provenance.json` records the
original and fragment hashes. Tests independently reconstruct the fragments from
the original AST without importing/executing the old application.

One runner performs red FIND, configured confirmation delay, orange staging for
250 ms, then one click on the same connected target. Persisted highlight settings
are snapshotted per attempt. Zero duration disables highlights/delays rather than
falling back to the old default. Success leaves outlines to expire naturally;
failure/cancellation clears owned overlays. Missing, ambiguous, changed, hidden,
detached or disabled targets are rejected, not guessed. Click is not confirmation.

The controlled jsdom peer executes the actual probes and observes click count,
outline colours/expiry and stash cleanup. Geometry is doubled: this does **not**
prove native rendering, Windows timing or live site behavior. Diagnostic summaries
require explicit consent and contain only allowlisted phase/live-disabled fields;
URLs, prompt text, page contents, exceptions and session data are not included.

## 8: immutable sequential preparation

`OfflineExecution` accepts only an explicitly test-only adapter; enabled fixture
rows must use reserved `.invalid` hosts. No concrete live implementation is shipped.
Fresh observations select a ready, empty, exact-URL row round-robin. Preparation
validates selected source bytes/fingerprint and snapshots source identity, exact
row/URL, prompt mode/text, variables, highlight settings, target/context and message/
response baselines. Every attempt has a full `[JOB-ID:<uuid>]` marker.

`prepare(source_id)` reserves one attempt; `advance(id)` advances one phase.
Upload and prompt actions are bounded, intent-first operations. Attachment name,
SHA-256 and persistent identity must match; prompt readback must equal the complete
marked text. Source, context, attachment and prompt changes are tested. No automatic
batch driver is exposed; observed output cannot release the queue before Step 10.

## 9: durable Send intent, observation and interruption

The existing atomic JSON writer stores `jobs.execution` outside global undo:

`prepared → upload_intent → uploaded → prompt_intent → ready_to_submit →
submit_intent → submitted → output_observed`

Inputs and existing event prefixes cannot change. Evidence binds attachment ID,
prompt hash, submitted message ID and response ID. Send intent must be durable
before the shared visual runner executes. A new uniquely marked message, absent
from baseline, confirms submission. Response observation is bound to that same
persisted message and excludes baseline responses; it does not validate/download
image bytes or claim completion.

- One unresolved attempt owns the sequential session, including after restart.
- Pause blocks new effects; an already-submitted attempt can continue read-only
  observation. Stop-after blocks the next preparation, not the current attempt.
  Controls are durable; resuming controls does not itself launch work.
- Pre-effect auth/security blockers pause for explicit manual recheck. Post-intent
  uncertainty, disconnect, timeout or cancellation becomes `needs_review`.
  There is no CAPTCHA solving or automatic Send retry.
- Explicit idle cancellation before Send is `cancelled`; task cancellation before
  an effect intent is recorded as `failed`. Neither automatically retries. Cancel
  an active task and await it before changing its lifecycle through `cancel()`.
- Preparation has a 10-second bound; each advance has a 75-second bound. Pending
  responses poll at 50 ms in this fixture-only library; timeout requires review.
- A restored engine refuses advance until explicit `recover()`. Recovery performs
  no adapter calls: pre-effect prepared/uploaded/ready states become `interrupted`;
  persisted effect intent/submitted states become `needs_review`.
- `needs_review` and `output_observed` retain ownership. No review-resolution,
  download/save/completed state or UI action is implemented yet. Do not manually
  remove evidence to resume work. Ledger limits are 100 attempts/20 events each,
  with bounded JSON validation; archival is not implemented.

Fault tests include failed intent writes, lost confirmation publication, concurrent
advance exclusion, changed evidence, and an actual child process that exits after
synthetic Send. Reopening the durable intent never replays Send. An integration
test executes the retained DOM click and checks disk intent immediately before it;
upload/observation methods are still scripted fixture doubles, not site behavior.

## Verification and remaining gates

`python tools/check.py` passes: 318 Python tests (including 33 execution and 10 new
retained-probe tests), 15 workspace DOM integration tests, selected retained suites,
Ruff, strict mypy (52 files), JS lint/format, size/complexity/coverage gates and 13
killed targeted safety mutations. Combined headless coverage is 98.59%; automation
statements/branches are 99.38%/97.78%. This is not a full mutation score.

The current wheel builds and installs in a fresh environment. Outside the checkout,
the offline engine imports, CLI version runs, provenance loads and all three probe
phases build from packaged assets. Native GUI execution is not established.

Live acceptance still needs privacy-consented, sanitized same-conversation captures
of idle, attachment, enabled Send, submitted, processing, completed, security and
authentication states, reviewed under [research requirements](rebuild/01-RESEARCH.md).
Native WebEngine/Windows Chrome manual gates and inactive CI are unchanged. Safe
output byte validation/publication is Step 10, not an inferred success here.
