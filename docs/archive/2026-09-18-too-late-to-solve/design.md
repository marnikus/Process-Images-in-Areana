# Round 9 — "solving too late?" diagnosis + strategy options

## Verdict: YES — proven by the 13:14 run's own evidence trail

Task #83882904043 (tab 59FA0C): submitted 13:14:25 → heartbeats at 31 s /
61 s → **token received in 71 s (`len=2468 head=0cAFcWeA tail=suFA`)** —
a REAL provider token — but:

1. `token arrived but the dialog is already gone (page moved on?)`
   (pre-inject probe caught it),
2. `solved in 71s (token 71s, token accepted)` — vacuous: there was
   nothing left to accept it,
3. **same second**: `Wait failed: Page error: Something went wrong…`
   → job failed fast, reset to new chat.

The token is genuine; it is simply useless for THIS attempt. Page
patience (~60 s from submit: captcha at +4 s, error ~1 min later) is
shorter than the enterprise worker queue (61–101 s observed).

## What rounds 7+8 validated in this run

- Heartbeats, task id, token fingerprint, pre-inject state, split
  timing — all present, coherent story in the log.
- Fast-fail fired INSTANTLY at solve end — no 180 s burn (compare the
  12:36 run: 180 s × 4 tabs + failed resubmits).
- Fail-fast + new-chat reset is the CORRECT handling here: the thread
  is explicitly dead (revival resubmit is for QUIET death, not for an
  explicit page error — resubmitting into a dead thread was the round-7
  failure mode).

## Structural picture

- EVERY observed captcha'd attempt fails; progress comes from fresh-
  thread retries that (hopefully) don't draw a captcha.
- Blind window: the error scan is BLOCKED during the solve (the solve
  runs synchronously inside `_security_gate`), so the error's APPEARANCE
  time is unknown — we only see it after the token lands. Any "abort
  early" design must break this coupling.
- Observation: the fail message LACKS the Trace ID, so the match came
  from the original alert/toast selector (collector lines always contain
  `trace id`), not the round-7 collector. Doubly covered; the 12:36 miss
  (no selector matched) is unexplained but moot.

## Options

**A. Data-first (RECOMMENDED).** Tiny slice: log `isInvisible` in the
submit line (verify we're not slowing workers with a wrong flag) +
W1 watch-only CONCURRENT error timestamps during the solve (log when
the error appears; change NO behavior). After 1–2 runs we own the
histogram (time-to-token vs page patience) and decide B vs C on facts.
Cost: ~15 lines + tests. Risk: ~nil.

**B. Abort-race now.** Race the solve against a concurrent error watch;
when the page dies, cancel the poll (`page_error` reason) and let the
wait abort. Saves wall-clock (tens of seconds per captcha) but NOT
credit (task already paid). Risk: touching the choke point
(`_security_gate` ↔ solver await); manual-wait fallback must be
suppressed/skipped for `page_error` (waiting for a user on a dead page
is wrong) — service-layer reason routing. ~60 lines + tests.

**C. Skip-solving experiment.** If the histogram says tokens NEVER beat
the page, auto-solve on this site is pure waste (time + credit): on
captcha, skip 2Captcha entirely → instant new-chat retry. Biggest
saving IF the premise holds; catastrophic if wrong (throws away solves
that would have landed). MUST be data-gated — never implement blind.

**D. Faster provider.** Research CapSolver et al. for enterprise speed;
new account/key/plumbing + RULE 20 review. Only if A-data says our
queue times are the outlier, not the page patience.

## RULE 18 sketch (as-built target, whichever option)

- A: 1 log token + watcher ≤ B, no signature growth.
- B: race helper + reason route, all ≤ B; no new Bridge methods.
- C/D: design doc first (this file's successor).

## Decision: A (data-first) — user skipped the vote, proceeding with the recommendation

As-built refinement: W1 runs SEQUENTIALLY inside the solver poll loop
(`_note_page_error` per provider poll, ~5 s cadence), NOT as a concurrent
race task. Reason: `CDPClient.send` is id-matched and probably safe, but
a watcher would be the FIRST concurrent CDP use in the choke point —
unneeded risk for a watch-only diagnostic. Sequential gives the same
timestamps with zero new failure modes:

- `SolvePlan.err_base/err_seen` (+2 defaulted fields, no signature change);
- `_note_page_error(plan, log)` (B(8)): first poll takes the baseline,
  later polls report only FRESH errors as
  `🛡️ page error appeared during solve (Ns in): <text>`;
- `CDPArenaController.scan_page_errors()` public corpus (3 lines);
- submit line gains `isInvisible=<flag>` (worker-payload check).

`_poll_task` stays B(9) (one await, no new branches). Next: 1–2 live runs
→ histogram (time-to-token vs error-appearance) → decide B vs C on facts.
