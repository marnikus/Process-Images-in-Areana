# Captcha solve hardening — bounded fresh-token retry, spend guards, thread-safe evidence

**Date:** 2026-09-18
**Status:** design + implementation in this change
**Built on:** `docs/archive/2026-09-18-captcha-bot-failure-analysis/verification-and-problem-diagnostic.md` (root causes RC-1…RC-5) and the round 5–11 live-log evidence
**Safety boundary (RULE 20):** every change only makes the site's own challenge flow run correctly with a **fresh, current, correctly-associated** token. No fingerprint spoofing, no behavioral evasion, no anti-bot control weakening, no retry storms — paid tasks per encounter are hard-capped at 2.

## 1. Problem statement

User report class: the bot path gets **rejected** (token not accepted) or produces **web-page/job errors**, while a human solving the same challenge succeeds. The round 5–11 fixes eliminated the known *wiring* causes (wrong callback chain, badge-sitekey tasks, dead generations). What remains, per the bot-failure diagnostic, is that the #1 confirmed rejection mechanism — **RC-1: the token is no longer matched to the current challenge when it is delivered** — is only *detected* today: the solver aborts (`token_stale`) and the encounter ends. Two consequences:

1. The challenge is often **still on screen** (the page rotated the challenge, or the server rejected the first token), yet the encounter ends with **no retry and no manual fallback** — the user is left staring at a captcha the app no longer handles; the job then fails or stalls.
2. Between detection and solve, a paid task can be **created for a challenge that is already gone** (user started solving manually), and the bot keeps polling — and may even inject — while the user is mid-solve, creating exactly the "error web page" the report describes.

Goal: **avoid rejection and job errors** by (a) giving freshness a bounded second chance inside the encounter, (b) never billing for a gone challenge, (c) never racing the user's manual solve, (d) making the recording evidence thread-safe so remaining failures stay diagnosable.

## 2. Research — what the current pipeline already guarantees (guard audit)

Audited against `app/services/captcha/solver.py` + `service.py` at HEAD:

| Guard | Where | Status |
|---|---|---|
| Per-tab inflight dedup (no double billing) | `CaptchaSolver.solve` | solid |
| Mid-poll **page-error** abort + task delete | `_provider_result` → `_note_page_error` every poll | solid |
| Pre-injection identity re-probe (page URL, challenge identity, sitekey) | `_stale_outcome` before inject | solid — but **abort-only** |
| Dialog-gone-at-token → no inject, task deleted | `_inject_and_verify` (`dialog_gone_before_token_injection`) | solid — but **abort-only** |
| 20 s verify-grace; dialog-not-gone = `not_accepted`, task deleted | `_verify_gone` + `_reject_reason` | solid — but **one attempt only** |
| Stop honoured in poll + verify loops (RULE 7) | `plan.stop()` checks | solid |
| Manual fallback for `auto_failed` outcomes (RULE 20) | `service._resolve_captcha` last branch | solid |
| **`token_stale` returns WITHOUT any fallback** | `service._resolve_captcha`: `if outcome.status in ("page_error", "token_stale"): return outcome` | **gap G1** |
| **Paid task created without re-checking the dialog** | `_solve_once` → `_create_task` (no visibility probe between detect and createTask) | **gap G3** |
| **Poll loop never notices the dialog leaving** (user manual-solves mid-poll) | `_poll_task` checks page errors but not dialog presence | **gap G4** |
| **`not_accepted` ends the encounter after one attempt** | `_inject_and_verify` → auto_failed | **gap G2** |
| Recording network handoff crosses threads (websocket → bridge loop) via `asyncio.Queue.put_nowait` + `get_nowait` race | `NetworkCollector.on_event/drain` (P9) | **gap G5** |

Evidence tie-in (bot-failure diagnostic): G1/G2 are where RC-1 (stale token — rounds 9/11 proof) currently *lands*: the guard proves the mechanism is real but gives the encounter no way to recover. G3/G4 are conflict sources the recordings cannot even show reliably (G5).

## 3. Design — the hardened pipeline

### 3.1 Invariant (new behaviour, recorded as I-34 in SYSTEM_OF_RECORD)

> **One encounter, at most two paid tasks, and the token is always re-validated against a still-visible challenge.** The solver retries **once** with a fresh task when — and only when — the challenge is still visible and rotated (identity/sitekey changed, or the first token was rejected with the dialog still up). Every abort path deletes its provider task. When the auto budget is exhausted, a still-visible challenge **always** degrades to the manual-wait fallback; a gone challenge ends the encounter.

### 3.2 Changes (smallest responsible component each)

**H1 — bounded fresh-token retry (`solver.py`).**
`_run_task` becomes a small attempt loop around the existing `_attempt` (old body, unchanged logic):

```text
attempt 1: create → poll → pre-inject guards → inject → verify
retry decision `_retry_with(plan, outcome)`:
  only if attempts < 2 AND stop() is false AND
  ( outcome token_stale with stale_reason ∈ {page_identity_changed,
    challenge_identity_changed, sitekey_changed}
    OR outcome auto_failed "not_accepted: dialog still visible …" )
  AND a FRESH detect probe returns a solvable signal AND
  the dialog is still visible right now
→ re-baseline plan (fresh signal identity, cleared token/inject/stale fields,
  polls cumulative, original start kept), log the retry, attempt 2
otherwise → return the outcome (existing behaviour)
```

Attempt 2 runs the identical guards (identity re-probe, page-error check, grace) — a second failure fails closed exactly as before. `SolveOutcome` gains `attempts: int = 1` for the report line.

Why this avoids rejection: RC-1 is a **latency/rotation** problem, not an impossibility — a fresh task bound to the current challenge identity is what a human's second attempt would be. The retry is the same operation, bounded, with every guard re-applied.

**H2 — pre-task spend + conflict guard (`solver.py`).**
At the start of each attempt, before `createTask`: one `is_security_dialog_visible()` probe; gone → `dialog_gone_before_task` (auto_failed), **no task created, nothing charged**. The service's existing fallback then sees a cleared dialog and resolves immediately as manual — the user's own solve is credited, penalty recorded as for any solved captcha, and no provider token is ever injected into a page the user is operating.

**H3 — mid-poll dialog watch (`solver.py`).**
Every 3rd provider poll (≈15 s at the 5 s cadence — negligible probe load), check dialog visibility; gone → delete the task (frees credit while still processing) and fail with `dialog_gone_during_poll`. This stops the bot paying past the moment the user takes over, and removes the bot-injects-into-user-mid-solve conflict (G4).

**H4 — `token_stale` fallback completion (`service.py`).**
`token_stale` no longer silently ends the encounter: after the retry budget, if the dialog is **still visible**, the encounter degrades to the existing `_manual_wait` (overlay + wait-for-clear + penalty) with the stale reason in the overlay's why-line. If the dialog is gone, the encounter ends (page moved on) — current behaviour. No new status values; the report journal keeps its two-line pattern (auto attempt line, then final resolution line) already used for other fallbacks.

**H5 — thread-safe recording evidence (`captcha_recording/network.py`).**
Replace the cross-loop `asyncio.Queue` with a lock-protected `deque` appended from the websocket thread and drained on the recorder loop — the `QueueEmpty` check-then-get race (P9) is removed by construction (no drops possible with an unbounded locked deque). A worker-thread regression test locks the no-loss behaviour. Recording finish now also persists `task_id`, `polls`, `attempts` (bounded, token-free) so the comparison data covers the retry behaviour (F-B lite from the bot-failure diagnostic).

### 3.3 Spend & loop safety (non-negotiable)

* ≤ **2 paid tasks per encounter** (hard constant `MAX_SOLVE_ATTEMPTS = 2`);
* no retry on `stop`, `page_error`, `no_key`, `task_create`, `no_credit`, `poll_timeout`, `dialog_gone_*`, or `task_failed`;
* every abandoned/finished task deleted (existing `_delete_task`);
* one dialog probe per attempt start + one per 3 polls + one at the retry decision — probe cost ≪ poll cost;
* `SolveOutcome.attempts` appears in the CAPTCHA_SOLVE report so over-retry is observable.

### 3.4 Rejected alternatives

* **Unbounded/3-attempt retry** — spend risk + server-side rejection feedback loop; the evidence (RC-1) supports exactly one freshness refresh, and the manual path is the correct second fallback.
* **Retry on `dialog_gone_*`** — dialog gone means the user or the page already handled it; re-solving would fight the user.
* **Re-probing identity *continuously* during poll** — probe load + no benefit: the token is only ever used at injection, where the identity re-probe already runs. The dialog watch (H3) covers the user-takeover case that identity can't see.
* **Auto-retry `task_failed` (provider failed the task)** — provider-side failure (e.g. unsolvable content) is not a freshness problem; immediate manual fallback is cheaper and honest.
* **New "retrying" UI state** — the log line + existing `waiting_captcha` pool state already surface it; a new state would touch the state machine (00-22) for no diagnostic gain.

## 4. Test plan (tests first, RULE 8 — real solver/service against fakes)

1. Pre-task probe: dialog gone before task → **no** `create_task` call, `dialog_gone_before_task`, no charge, fallback resolves immediately as manual (service level).
2. Mid-poll dialog watch: dialog leaves during poll → task deleted, `dialog_gone_during_poll`, poll count stays small.
3. Retry success: attempt 1 stale (`challenge_identity_changed`) with dialog still visible + fresh solvable signal → **exactly 2 tasks created**, attempt 2 solved, `attempts == 2`, single `auto_solved` stat.
4. Retry exhausted: both attempts stale → `token_stale`, `attempts == 2`, both tasks deleted.
5. No retry when dialog gone at the decision (rotation + navigation) → `attempts == 1`.
6. No retry on stop / page_error / not-retryable reasons.
7. `not_accepted` with dialog still visible retries once; second `not_accepted` → manual wait.
8. Service: `token_stale` + visible dialog → `_manual_wait` (overlay + `wait_captcha_cleared` → `manual`); `token_stale` + gone dialog → returned as-is, no overlay.
9. Recording: worker-thread puts events while the recorder drains — zero loss, no exception (P9 regression); finish manifest carries `task_id`/`polls`/`attempts`.
10. Equivalence gate: full existing suite green (all current guard tests, incl. identity/sitekey/post-close badge tests) with only the documented `visible_seq` fixture shifts (the attempt-start probe consumes one visibility sample).

## 5. Acceptance criteria

1. All §4 tests red before / green after; full suite green.
2. No encounter can ever bill > 2 tasks (asserted in tests 3/4/7).
3. `token_stale` + visible challenge can never end an encounter without either a solved outcome or the manual-wait overlay.
4. CAPTCHA_SOLVE report line carries `attempts`; RULE 16 gate 0 fails; RULE 18 sizes held (new solver helpers ≤ 20 lines); no legacy metric worsened.
5. No token, key, or credential in any new log/manifest field.
