# Design — per-tab Watcher warnings and identity-safe new-chat handover

**Status: approved and implemented on the working branch; automated Python, JavaScript, and RULE 16 checks pass. Real-Chrome acceptance with two authorized Arena accounts remains pending.** This design responds to the 2026-09-29 report: on two worker pages, a Watcher warning disappears on one page but remains on the other; enabling “Start new chat as new tab” can make a worker opened under one Arena account appear to hand over to a tab showing another account.

## 1. User-visible contract

1. **Each worker page is independent.** A warning shown for a wait on tab A is cleared when A's own wait ends or a fresh terminal page error is detected on A. Clearing A must not clear, replace, or resume away tab B's warning while B still has a live wait. The same transitions apply to both pages; this is not special-cased for the primary tab.
2. **One worker cannot clear another worker's warning.** A job-level hide and a passive-Watcher hide are distinct owners, even when they target the same page. Hiding one owner's warning must leave any other still-valid warning visible.
3. **Global pause is aggregate.** If a Watcher wait on any checked pooled worker requires pausing, jobs remain paused until every such wait has ended, timed out, become terminal, or its page has left the pool. A page error ends only that page's Watcher episode; it does not release the pause while another page remains blocked.
4. **New-tab handover preserves the worker's real identity.** The new target must be on the exact old tab's CDP endpoint and browser context, pass the new-chat proof, and show the same verified Arena account. Cached labels alone are not proof. Until all checks pass, the old tab, its clients, pool key, URL-row binding, and alias remain untouched.
5. **Unprovable identity is a failed handover, not a guessed success.** On mismatch, unknown identity, wrong context, or timeout, close only the candidate tab, leave the original tab open and attached, then use the existing in-place New Chat fallback. Never close the original tab on behalf of a candidate with a different or unverified account.

This design treats “Chrome profile” (CDP endpoint + `BrowserContextId`) and “Arena account” (the email returned by the page owner probe) as separate identities. Logs must name these separately; an endpoint match is not proof that the Arena account matches.

## 2. Evidence from current code and supplied run

### 2.1 Watcher warning asymmetry

* The passive Watcher obtains one controller from `get_watcher_cdp_controller(bridge)`, which wraps `bridge.cdp`; its `check_once()` probes and draws/clears an overlay on that one page (`app/ui/panels/watcher_captcha.py`, `app/services/watcher_pkg/{loop,cdp,handlers,generation}.py`). The page pool can have multiple independently running workers.
* The job pipeline also shows and hides the same watcher-overlay type through each job's own controller (`app/services/single_job_runner.py`, `app/services/captcha/service.py`).
* In the generated overlay JS, `show` removes every existing node with `WATCHER_ATTR` before adding its own, while `hide` removes every node with that attribute. There is no owner/episode key. Thus a passive-Watcher clear, job completion/error cleanup, or competing wait on the same page can erase another active warning on that page. Different page documents, meanwhile, are cleared independently.
* The Watcher holds one `waiting_kind` / `waiting_since` / generation episode, not one episode per pooled tab. Its generation probe does not include the shared page-error result used by the output path (`scan_page_errors` + `match_page_error`). An error can therefore settle one job while the Watcher's spinner-based warning follows a different lifecycle.

These are direct code facts; the pasted log demonstrates two simultaneous worker jobs and generation/CAPTCHA events, but does not include overlay DOM snapshots or target ids at each hide. Therefore the precise hide race in that run remains to be confirmed by the characterization tests and a two-tab repro.

### 2.2 New-tab account mismatch

* The supplied run names both worker accounts on endpoint `127.0.0.1:9223`. Anton's handover succeeds. For mxxy, a candidate opens, but `_check_owner_preserved` reads `anton.melnikov.90@gmail.com`; `handover` rejects it, rolls back, and keeps mxxy's old tab. The log does **not** show the old mxxy tab being closed in this latest attempt; the initial report describes an earlier wrong-profile close. Both outcomes violate the intended experience: the current one falls back rather than creating the requested fresh tab, and the earlier one could close the wrong worker's tab.
* `new_tab._plan` stores the owner from cached `PageInfo.owner`, and `_open_and_prove` captures cookies, creates a candidate, reconnects all old-tab clients to the candidate, then applies cookies and checks its owner. `_check_owner_preserved` accepts an empty owner probe as success. `_verify_context_same` only rejects when the old context id is truthy and a different non-`None` id is observed. This leaves unknown context/identity as weak evidence.
* `Network.getAllCookies` / `Network.setCookie` operate on a browser context's cookie store, not a per-tab cookie jar. Copying cookies after candidate navigation is both too late to establish the candidate's loaded app identity and potentially changes shared session state for other tabs. Cookie values must never enter logs or tests.
* The handover tests prove pool rekey/rollback and endpoint preference, but `_world()`'s fake clients do not implement `Target.getTargets` or `Target.createTarget`; the real same-context open fails into mocked `/json/new`. The regression suite therefore does not exercise context selection, context proof, or owner readiness.

## 3. Proposed architecture and decisions

### A. Per-tab Watcher lifecycle

**D1 — enumerate active worker targets, do not hard-code two pages.** Add a narrow target-source seam that snapshots the existing checked page-pool entries as `(tab_id, readable_label, controller/client)`. Pool membership already follows checked URL rows (I-56/I-58); the Watcher must not create a second eligibility rule. A missing/disconnected target is handled as a named per-tab outcome, not as a successful empty probe.

**D2 — episode state is keyed by CDP tab id.** Each target owns its wait kind, start time, observed JOB-ID baseline, page-error baseline, stale/timeout state, and last answered status. Keep `WatcherState`'s public aggregate fields for existing UI compatibility; derive aggregate status from the per-tab episodes and add a bounded per-tab summary only if the existing signal can carry it without a new slot. A tab id, not account email or URL, is the identity key.

**D3 — use overlay leases, not “remove all.”** Give each overlay a stable owner key (at minimum `watcher:<tab-id>` versus `job:<job-id>:<tab-id>`). The DOM payload stores/replaces/removes only that owner's lease and re-renders the currently applicable message. A hide without an owner is prohibited for normal lifecycle paths; force-clear/teardown may explicitly clear all leases on its target page. Keep messages, timer behavior, and existing visual styles unchanged. The browser-facing generated JS must be run in the existing Node DOM-probe lane, not string-asserted (RULE 8 / I-38).

**D4 — use one terminal-error predicate.** Reuse the existing page-error scan/matcher rather than adding a Watcher-only vocabulary. Capture a baseline at the start of each tab episode; only a fresh error relative to that baseline ends that page's wait. A stale pre-existing toast is not a terminal event. Record the reason with the worker label and tab id, hide only the Watcher lease for that page, and let the normal job path settle its own lease/result.

**D5 — pause/resume is edge-triggered from the set of waiting tabs.** Transition from zero waiting tabs to one pauses once. A page entering/leaving while the set is non-empty does not issue duplicate pause/resume calls. Resume once, only when the final blocking episode leaves. An unanswered probe holds its existing episode (I-71); it is not interpreted as clear. A timeout ends only its own episode (I-66). Removing a tab clears only that tab's episode and lease.

**D6 — tick every pooled target with a bounded per-target probe.** The existing configured interval remains the cadence knob. The target pass must honor cancellation and avoid an unbounded serial wait: use the established short page-check timeout and report partial/unanswered targets. Tests must include more than two targets so the solution generalizes, while the owner acceptance run uses two.

### B. Transactional new-tab handover

**D7 — resolve endpoint and context from the old pooled target.** Parse/validate the endpoint from the old tab's own `ws_url` and confirm it agrees with the pooled client. Resolve the exact `BrowserContextId` for the old target, representing the default context explicitly when Chrome omits the id. Resolve the candidate only through `Target.createTarget` in that context. Remove the unverified `/json/new` fallback for this identity-preserving path: if exact context creation or proof is unavailable, fail safely and use in-place reset.

**D8 — capture the expected account from the old page immediately before handover.** Run the existing owner probe on the still-attached old tab and require a valid normalized owner for an account-preserving new-tab move. Do not substitute a cached alias when the live identity read is empty. This prevents moving a stale label as if it were proof.

**D9 — prove candidate before mutating any worker holder.** Attach a temporary candidate client; wait for page readiness; prove new chat; verify the candidate's context exactly equals the old context; and poll the existing owner probe until the candidate returns the expected owner on consecutive answered samples within one bounded deadline. Empty/unanswered results remain “unknown”; an observed different email is immediate mismatch. Only then move the existing job/pool/home clients, rekey the page, adopt alias, repoint the URL row, persist/emit, and close/verify the old id at the old endpoint.

**D10 — remove cookie copying.** Same-context creation is the session-preservation mechanism. Do not read, log, serialize, or copy cookies. If a real Chrome experiment proves account state is not inherited by a same-context target, stop and decide the supported product model before coding: separate CDP endpoints/browser contexts per Arena account, or an explicitly designed isolated context. Do not “fix” it by writing account A's shared cookie jar while account B is active.

**D11 — preserve atomic rollback.** Every pre-commit failure closes the candidate and leaves the old client objects, `PagePool`, `AliasBook`, URL rows, cooldown, and old target unchanged. Commit/rekey happens only after identity proof. Close-old failure after a committed move remains a distinct close-verification error; it must never redirect the worker or close a candidate with another owner.

## 4. Implementation shape and quality budget (for a later approved implementation)

This is a multi-file behavior change; tests-first and a structural pass are required. The current `app/services/new_tab.py` is **539 physical lines**, already beyond RULE 18's 150–300-line preference. The proposed work must not grow it. Split by domain responsibility before adding handover branches: keep the public setting/entry facade small; put context/owner proof in a cohesive identity leaf; put transaction commit/rollback in a handover leaf only if the measured call graph supports that boundary. Remove the cookie-copy path rather than relocating it. For Watcher, keep per-target episode/lease decisions in the watcher package, with the CDP target source and generated overlay ownership at their existing layer boundaries; do not grow a God-class or duplicate the page-error predicate.

Radon is not installed in this checkout (`radon: command not found`; `python -m radon` also unavailable), so numeric CC/cognitive/nesting baselines were not fabricated. Before production edits, install/use the repository's pinned quality toolchain and record `radon cc -s` plus RULE 16's cognitive/nesting/maxima for every touched function. Targets: new/edited production functions 4–20 LOC preferred, never >30 LOC; CC ≤10, cognitive ≤15, nesting ≤4, ≤4 parameters; new modules 150–300 LOC where they own a coherent responsibility. Follow RULE 19 order (nesting → CC → cognitive → size), not line-count splitting. Preserve current public Watcher signal/slot surface unless a concrete UI requirement proves a new slot is necessary.

## 5. RED-first test plan

### Watcher / overlay tests

1. Two worker targets both start generation waits; A gets a fresh page error and clears. Assert A's Watcher lease is gone, B's remains visible, and jobs remain paused until B ends. Then assert exactly one global resume.
2. Run the same matrix with A/B swapped, then with captcha on one and generation on the other. Results must be symmetric and target-keyed.
3. Put a job-owned overlay and a Watcher-owned overlay on the same tab. Hiding either owner leaves the other visible; force-clear explicitly removes both.
4. A stale error baseline does not end an episode; a newly appearing error does. Unanswered probe holds; timeout ends only that tab; tab removal clears only that tab.
5. Watcher OFF remains zero pipeline activity (I-48); cancellation remains prompt (RULE 7); counters/logs are per real transitions, not every poll.
6. Execute the actual generated overlay payload with the existing Node DOM harness and test duplicate-show, owner-specific hide, reveal-next-owner, and all-clear behavior (I-38).

### New-tab handover tests

1. Fake CDP Target APIs with two distinct browser contexts on one endpoint. Handover from each context must create in that same context; bridge primary connection may point elsewhere and must not affect selection.
2. Same owner + exact context + ready new chat commits once, preserves pool order/cooldown/count/alias/row checkbox, then closes only the old id on the old endpoint.
3. Different owner, empty owner, unstable owner, wrong context, unreadable old owner, or proof timeout: candidate closed; old target remains; clients/pool/alias/rows/cooldown are byte-for-byte unchanged; caller takes the ordinary in-place reset.
4. Assert there are no `Network.getAllCookies` / `Network.setCookie` calls in the handover path and no cookie values in logs/recordings.
5. Two workers with different owners complete in both orders. The new candidate for mxxy must never be adopted or closed as Anton, and vice versa.
6. Keep existing `test_new_tab_handover.py` behavior tests, but replace the fallback-only fake with protocol fakes that exercise `Target.getTargets` / `Target.createTarget` and context identity.

## 6. Verification and owner acceptance

After tests are green, run the complete Python and JS lanes, source-lock/quality gates, and the required RULE 16 coverage checks. Execute the generated JavaScript probes in Node. Then perform a real-Chrome acceptance run with two user-authorized Arena accounts in the exact configuration that produced the report:

* Start one job on Anton and one on mxxy; force each to finish/error in turn. Verify a terminal error clears only its own Watcher warning, the other warning remains, and the global run resumes only after all blocking pages clear.
* Enable new-tab handover. For each account, verify logs show old endpoint + normalized context identity + old owner, candidate context + stable candidate owner, move commit, and old-tab close on the same endpoint. The address bar must be the configured new-chat URL and the account probe must still match the source worker.
* Verify no original tab is closed on mismatch/unknown; the user sees a warning naming the failed proof and an in-place reset instead. Verify the other worker's cookies/session and running job are unchanged.

**Decision gate before implementation:** if the two Arena accounts are actually in one shared Chrome browser context and the site does not provide independent per-tab authentication, the app cannot safely promise distinct accounts by merely opening another target in that context. Confirm the actual context ids and owner probes first; if they are the same context, get the owner's product decision on separate browser endpoints/contexts rather than weakening identity verification.

## 7. Explicit non-goals

No CAPTCHA solving changes, no account credential capture or cookie migration, no auto-login, no change to checked-row pool membership, no change to URL reconciliation ownership, no unrelated Watcher UI redesign, and no change to Firefox's Ui.Vision lane. Do not update `SYSTEM_OF_RECORD.md` with this proposed behavior until implementation lands and passes verification (RULE 17).
