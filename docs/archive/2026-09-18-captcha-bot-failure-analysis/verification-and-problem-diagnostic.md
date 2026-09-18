# CAPTCHA BOT FAILURE — VERIFICATION AND PROBLEM DIAGNOSTIC

**Date:** 2026-09-18
**Status:** verified against current source + live solve-round logs (rounds 5–11); recording-level confirmation pending user session folders
**Structure:** problem statement → evidence from diffs → root cause → fix proposal
**Supersedes (partially):** `docs/archive/2026-09-18-captcha-solve-comparison-diagnostic/verification-and-problem-diagnostic.md` (pre-fix audit; its P1–P10/H1–H8 inventory is re-verified here against current code)
**Safety boundary (RULE 20):** diagnose integration, lifecycle, timing, callback, and server-result differences only. No behavioral biometrics, no fingerprint spoofing, no automation concealment, no anti-bot control weakening. Bot fixes may only make the *site's own flow* run correctly with a valid, current, correctly-associated token.

---

## 1. Problem statement

The automatic (bot) CAPTCHA path — opt-in 2Captcha Enterprise, `handle_captcha` choke point — can return a locally "solved" attempt while the page never accepts it and the image job still fails. A human (manual) solving the *same visible challenge* from the same page state succeeds. The question is: **exactly where does the bot path diverge from the manual path, and what is the smallest correction for each divergence?**

A solve has eight independent boundaries; conflating them into one `solved` flag is how false success hides:

```text
1 challenge detected        5 token delivered to the correct response field(s)
2 provider task created     6 the site's real solve callback invoked
3 challenge/page identity   7 CAPTCHA dialog cleared
4 token returned current    8 backend accepted the transition and generation resumed
```

Dialog disappearance proves boundary 7 at most. Boundaries 8 (acceptance, output) remain the authority for job success.

**Evidence availability.** User recordings exist on the user's machine under `config/captcha_recordings/<session-id>/` (git-ignored, local) and are labeled in the Captcha Session Records window. They are not in this workspace, so session-level conclusions below carry **recording-signature confirmation pending**. What IS available and is used as evidence: (a) the current source of the bot path, the manual path, and the recorder; (b) live-log evidence from solve rounds 5–11 archived in this repo.

## 2. Evidence from diffs

### 2.1 Manual vs bot path — structural differences (as implemented)

| Stage | Manual (human) | Bot (2Captcha) | Structural difference |
|---|---|---|---|
| See challenge | Inside the cross-origin reCAPTCHA iframe: checkbox/grid visible | Parent-page probes only (`visible.js`, `detect.js`) | **D1** — bot cannot observe challenge-internal state; can only infer it from parent signals |
| Produce token | Site's own JS, in-iframe, instant, bound to the live challenge | Third-party provider: `createTask(websiteURL, websiteKey[, isInvisible])`, poll 30 s | **D2** — token origin has latency (Google single-use ≈ 2-min TTL), task-classification and sitekey-scoping risk |
| Deliver token | Site's active client writes its own field | React-safe set of EVERY `g-recaptcha-response` field (dialog first, then document) | **D3** — bot must *discover* the right field/client; badge vs dialog field disambiguation |
| Invoke callback | The site's own flow calls its own callback | Chain: `data-callback` → `___grecaptcha_cfg.clients` (sitekey-preferred) → legacy anchor `&cb=` last resort | **D3** — wrong/missing callback = no acceptance even with a valid token (proven, §2.3-R5) |
| Identity currency | Implicit — human acts on the live challenge | Re-probed before injection: page URL + `performance.timeOrigin` + challenge-frame identity (round 11 gate) | **D1/D2** — mismatch ⇒ task deleted, `token_stale`; guard detects, it does not prevent the divergence |
| Continue | Human clicks when the button is enabled | Best-effort click, once enabled, with terminal-state diagnostics (round 7) | **D4** — may be premature, missing, or land on a stale element |
| Acceptance | User sees generation resume | No direct acceptance signal — dialog-gone is recorded as `accepted_candidate` only | **D5** — bot path structurally lacks an acceptance oracle; output verification is the final authority |
| Dead request | User resends manually | Server-side request can die *before* the solve finishes → dead-generation toast → bounded one-resubmit per wait | **D6** — a perfectly correct solve cannot revive an already-dead generation |

### 2.2 Recorder vs comparison viewer — re-verified defects (P-inventory, current code)

Re-audited against the current tree (this change), line-level:

| # | Defect | Evidence (current code) | Status |
|---|---|---|---|
| P1 | A/B viewer reads `event.at_ms` / `event.payload`; persisted events carry `offset_ms` + **flat** fields | `captcha-recording-comparison.js` `render()`; `recorder.py::_event` writes `{seq, at, offset_ms, kind, …flat}` | **OPEN — fixed in this change (F-A)** |
| P2 | Snapshot reader reads `at_ms`; snapshots persist `at` (ISO) | `reader.py::_snapshot` vs `recorder.py::_checkpoint` | **OPEN — fixed in this change (F-A)** |
| P3 | Only the **latest** snapshot is exposed; store keeps up to 25 | `reader.py::details` → `latest_snapshot` only | OPEN (F-E) |
| P4 | No computed DOM/timeline/network diff — two independent text panes | `captcha-recording-comparison.js` | OPEN (F-E) |
| P5 | Cross-origin challenge iframe not recorded (browser boundary) | `snapshot.js` clones parent document only | EXPECTED — safe evidence only (frame lifecycle, host/path, field count) |
| P6 | Milestones incomplete: `token_at_ms`, `dialog_at_token`, `inject` now recorded via `note_outcome`; still missing task-created offset, poll count, field count pre/post, callback source/result, continue result, acceptance offset, job-result join | `recorder.py::note_outcome`; `SolveOutcome` (all fields exist in `app/services/captcha/signals.py`, round-10 `CAPTCHA_SOLVE` log line) | PARTIAL (F-B) |
| P7 | Labels are actor-only `unknown\|bot\|manual`; UI wording even reads "Bot passed"/"User passed" — **no independent passed/failed label, no `mixed`** | `models.py::VALID_LABELS`; `captcha-recordings.js::labelSelect` | OPEN (F-C) |
| P8 | Network events stored safe (host/path/status/type) but not semantically classified (bootstrap / verification / acceptance / generation-resume) | `network.py::_request/_response` | OPEN (F-E) |
| P9 | Network handoff crosses threads: `on_event` runs on the websocket receive thread (`cdp_events.py::route_cdp_message` — replies need `call_soon_threadsafe`), while `drain()` runs on the bridge loop. `drain` uses `while not empty(): get_nowait()` — a put between check and get raises `QueueEmpty`, which kills the recorder worker task ⇒ silent evidence loss | `network.py::on_event/drain`; `recorder.py::_run` | OPEN (F-D) — concrete failure mode identified |
| P10 | Truncation flags recorded in manifest but UI never downgrades/invalidate conclusions | `manifest.truncated`; no UI banner | OPEN (F-E) |

Also verified: the **JS test fixture encodes the wrong contract** (`tests/js/test_captcha_recording.mjs` feeds `{at_ms, payload}` events) — a RULE 8 violation: the test passes even though it matches no persisted recording. Fixed in F-A by pinning the fixture to the real schema.

### 2.3 Empirical bot-failure evidence (live logs, archived rounds)

These are **confirmed** mechanisms with log proof in this project — they are the leading explanations for user-reported bot failures until a specific session shows otherwise:

- **R5 — callback premise wrong (confirmed, fixed).** Live logs `cb=not found in anchor` ×4: the anchor `cb=` is recaptcha's internal *loader* argument; `window[cb]` never exists in the parent page. Token was injected but the site's real callback never ran → no acceptance. Fix: dialog-first field set + `data-callback` → `___grecaptcha_cfg` → anchor chain.
- **R9 — token real but too late (confirmed, guarded).** Google tokens are single-use with a ≈ 2-minute window. Long provider latency ⇒ page/challenge no longer accepts the token. Guard: refuse stale tokens, delete provider task (`token_stale`).
- **R11 — identity drift detect→inject (confirmed, guarded).** Page navigated or challenge changed between detection and injection. Guard: re-probe page URL + `timeOrigin` + challenge-frame identity before inject; mismatch deletes the task.
- **Sitekey scoping (confirmed, fixed).** Badge widget key ≠ dialog key; a paid task for the wrong widget is rejected. Fix: dialog-scoped sitekey preference; badge key excluded from fallbacks.
- **Dead generation (confirmed, classified).** The generation request can die server-side *before* the solve finishes; the site toasts "Something went wrong while generating…". Correct solve cannot revive it; fix: classify toast as dead request, bounded one-resubmit per wait.

### 2.4 What the recordings must confirm (per-session verification signatures)

For each user `bot + failed` session, compare against a matched `manual + passed` session on the same route/kind/build:

| Mechanism | Recording signature that confirms it |
|---|---|
| RC-1 stale token / identity drift | long detect→token interval; `dialog_at_token` = `gone`/error; page-error event before token; identity fields changed between checkpoints |
| RC-2 wrong callback association | `inject` OK + token current, but no callback/verification request in network class, dialog persists or page rejects |
| RC-3 no acceptance oracle | callback OK + dialog cleared, yet no acceptance request / generation-resume class; final job failed |
| RC-4 dead generation | page-error or dead-generation toast **before** token/injection; CAPTCHA milestones otherwise normal |
| H2 wrong field/scope | response-field count/scope differs between manual and bot checkpoints; injection changes a field the manual path never touched |
| H5 continue missing/premature | manual session shows a button-enable mutation + click + acceptance request; bot session lacks it or lacks the enabling mutation |
| H6 wrong task classification | failures cluster by one `kind`/sitekey-source group in the manifest |
| H8 recorder evidence loss | `status=interrupted`, seq gaps, non-monotonic offsets, truncation flags, missing final snapshot |

Cohorts required: **MP** (manual+passed), **BP** (bot+passed), **BF** (bot+failed). A difference shared by BP and BF is unlikely causal; a difference in BF absent from MP *and* BP is a strong success-condition candidate. Minimum three valid sessions per cohort for aggregate claims; pair-level first.

## 3. Root cause — why the bot solve is exactly incorrect

Ordered by confidence. "Guarded" means the current code detects and fails closed — the guard is *evidence the mechanism is real*, and it does not prevent the underlying divergence.

| ID | Root cause | Confidence | Current state |
|---|---|---|---|
| RC-1 | **Token delivered to a challenge that is no longer the active/valid one** (provider latency vs ≈ 2-min single-use TTL; navigation/challenge change between detect and inject) | **Confirmed** (R9, R11 logs) | Guarded: `token_stale` abort + identity re-probe. Guard detects; it does not shorten provider latency — sessions with long detect→token intervals still fail, now *honestly* |
| RC-2 | **Wrong or missing solve-callback association** — anchor `cb=` is a loader arg, not the site callback; badge vs dialog client confusion | **Confirmed** (R5 logs ×4) | Fixed (round 5 chain); ambiguous association fails closed to manual — correct |
| RC-3 | **No acceptance oracle on the bot path** — dialog disappearance is structurally not acceptance (D1/D5); the site's acceptance is only observable as a parent-page transition | **Confirmed** (design boundary, cross-origin) | `accepted_candidate` state + output verification as authority; *not yet provable from recordings* (P6) |
| RC-4 | **Generation request already dead before the solve finished** — no correct solve can revive it (D6) | **Confirmed** (dead-gen toast round) | Classified + bounded one-resubmit; must not be misattributed to the provider |
| RC-5 | **Comparison tooling cannot display the persisted evidence** — viewer contract ≠ persisted schema (P1/P2), latest-snapshot-only (P3), no result/mixed labels (P7), no computed diff (P4), thread-unsafe handoff can drop network evidence (P9) | **Confirmed** (source audit §2.2) | P1/P2 fixed in this change (F-A); rest ordered below |
| RC-6 | **Candidate (recording-pending):** wrong response field/scope (H2), premature/missing continue (H5), task-classification error (H6), evidence loss (H8) | Candidate — signatures in §2.4 | Verify against user recordings; smallest fix only after confirmation |

**Why a manual solve succeeds where the bot fails:** the human operates *inside* the live challenge (boundaries 3/4 are trivially current), through the site's own callback (D3 impossible to get wrong), and continues only when the page enables it (D4). The bot path replaces each of those with inference across a process boundary — and every inference has a measured failure mode above. The fix direction is therefore never "make the bot act more human" but **"make each inferred step verifiable, and fail closed to the manual path the moment an inference is not supported by evidence."**

## 4. Fix proposal (by difference)

### Implemented in this change

**F-A — comparison read-model matches the persisted schema (fixes P1, P2, RULE 8 fixture).**
- `EvidenceReader._snapshot` returns `at` (persisted ISO) instead of the nonexistent `at_ms`;
- A/B viewer renders `event.offset_ms` and the event's own non-envelope fields (`seq/at/offset_ms/kind` excluded), bounded;
- JS test fixture pinned to the **real** persisted schema — the test now fails if the viewer contract and the recorder schema drift apart again.
- Acceptance: JS test renders event details + timestamp from a real-shape fixture; Python reader test asserts `at`.

**F1 — see all records ever made (within the documented retention boundary).**
- `RecordingStore.count_sessions()`; `manager.count_sessions()`; bridge `list_sessions` reply gains `total`; UI requests all retained sessions (store cap 1000) and the title-bar summary shows the exact total, with a "showing last 1000" note only when truncated.
- Boundary (documented, unchanged): retention prunes oldest beyond 200 sessions / 512 MiB — "all ever made" means *all still retained*. Deletion (F2) lets the user curate what retention keeps, so valuable labeled sessions survive.
- Acceptance: store/bridge tests for `total`; JS test for summary text.

**F2 — remove records.**
- `RecordingStore.delete_session(session_id)` — same path-traversal guard as label/get; removes the session folder; `FileNotFoundError` when absent.
- `manager.delete_session` + bridge `@Slot delete_session` (JSON envelope, errors surfaced to the log, never fatal).
- UI: per-row 🗑 button; native `confirm()` (same pattern as action-block delete); re-list on success.
- Acceptance: store tests (success / not-found / traversal reject), bridge envelope test, JS test for confirm+delete+reload.

### Proposed next (recorded for the implementation order — none started)

**F-B — persist bounded semantic milestones (P6).** From `SolveOutcome`/solve plan, token-free: task-created offset + task id, poll count, token-ready offset, page/challenge identity at detect vs token, response-field count/scope pre/post injection, callback source + result, continue result, first page-error offset, dialog-clear offset, acceptance-candidate offset, final job result joined by `eid`. This is the enabler that turns RC-3/RC-6 from "candidate" into "proven or refuted" from recordings.

**F-C — independent ground-truth labels (P7).** `result_label: unknown|passed|failed` + `mixed` actor; label history timestamp; UI wording corrected (labels mean actor, not outcome); MP/BP/BF cohort builder excludes unknown/mixed from pure cohorts.

**F-D — thread-safe network handoff (P9).** Replace `asyncio.Queue` with a lock-protected deque (or `call_soon_threadsafe` schedule onto the recorder loop) + explicit dropped-event counter in the manifest + worker-thread regression test.

**F-E — aligned checkpoints + deterministic diff (P3, P4, P8, P10).** Bounded checkpoint index with milestone alignment (detected / token-ready / pre-injection / dialog-cleared / terminal), safe network endpoint classes, a computed report (common / manual-only / bot-only events, changed DOM paths, **first divergence**, truncation warning banner that downgrades conclusion confidence).

**Solve-lifecycle corrections — only after RC-6 recording confirmation.** Smallest responsible component per confirmed mechanism; no fingerprint/behavioral-evasion mechanism (RULE 20); each with a failing-first regression test and manual-fallback check.

## 5. Verification plan

For every implemented fix:

1. F-A: JS + Python tests fail before the fix, pass after; full pytest green; no new RULE 16 violations.
2. F1/F2: store/manager/bridge/JS tests (unit, no Qt beyond the existing import-shim pattern); delete is irreversible — confirm dialog mandatory in UI.
3. For any solve-lifecycle fix later: unit test reproduces the divergent state (fails pre-fix) → one fresh bot session reaches the missing milestone → user labels the fresh result independently → final page/output agrees with the label → no token/header/cookie/credential persisted → manual fallback intact → recording failures fail-open → RULE 16 gates green.

For the recordings themselves, once valid MP/BP/BF folders are supplied (see §10 of the comparison-diagnostic doc for the transfer checklist): integrity checks (complete manifest, labels known, no relevant truncation, seq monotonic) → milestone alignment (§2.4) → first-divergence report → confidence score (Confirmed/High/Medium/Low/Unknown) → smallest fix only.

## 6. Current conclusion

The bot path fails for **proven, integration-level reasons** — stale-token currency (RC-1), callback association (RC-2), the structural absence of an acceptance oracle (RC-3), and pre-solve dead generations (RC-4) — each now either guarded or fixed, and each with a recording signature that will confirm which one fired in any specific user session. What blocked *proving* which mechanism caused a specific user recording was the comparison tooling itself (RC-5): the viewer could not display the persisted evidence. F-A makes the recordings readable; F1/F2 make the record set manageable (view all retained, delete); F-B…F-E are the ordered path to a computed, first-divergence, evidence-backed root-cause report. Until a session passes §5, no specific user bot-fail session is declared caused by any single mechanism.
