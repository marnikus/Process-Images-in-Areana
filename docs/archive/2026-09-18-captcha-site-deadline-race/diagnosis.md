# Captcha site-deadline race — diagnosis from 34 recorded sessions

Date: 2026-09-18 · Status: diagnosed · Fixes S-1/S-2 + analyzer robustness shipped; Option A pending owner decision.

## 1. Report

User recorded a batch of sessions in which **every bot (auto) attempt failed while every
manual attempt passed** and asked for the cause and a fix.

## 2. Evidence (34 sessions, `config/captcha_recordings/`, 15:39–18:40 UTC)

| Outcome (method) | Sessions | Elapsed |
|---|---|---|
| `solved` (auto) | 6 | **45–56 s** |
| `page_error` (auto) | 16 | **60–61 s** |
| `token_stale` (auto) | 2 | 51 s, 56 s |
| `manual` | 4 | 26–40 s |
| `interrupted` (user stop) | 1 | 69 s |

No exceptions to the boundary: **every auto solve that finished ≤ 56 s passed; every one
still waiting at ~58 s failed.** 2Captcha tokens arrived at 45–56 s in the winning
sessions; in the failing ones the task was still `processing` through poll 13 (~60–65 s).

What the failing sessions actually show (identical in all 16, old and hardened code alike):

* at **58.3–60.4 s** the page renders
  `Something went wrong. Please try again.` / `Something went wrong while generating…`
  (matched by `app/utils/page_errors.py`, `something\s+went\s+wrong`);
* in the **same mutation batch** the site closes the captcha dialog and removes
  `#recaptcha-v2-container` (the challenge is no longer on screen);
* the chat counter increments (the failed attempt still counts as a chat);
* the next solver poll observes the page error, deletes the 2Captcha task (credit freed),
  and returns `page_error: no solution token` — the token was never injected because the
  site had already abandoned the generation.

Network timelines of failing vs solved sessions contain **no HTTP errors** (only 2xx
telemetry); the kill is purely the site's own deadline. The dialog was open from t=0 in
every session, so the site's clock starts at dialog appearance; the wall is **≈ 57 s ± 2**.

The `token_stale: sitekey_changed` session (18:33:55, hardened) is the same family: the
site removed the challenge widget at 43 s (rotation), the token arrived at 55 s against a
new sitekey, and the H1 retry correctly did **not** fire — there was no solvable
challenge left to retry (`_rebaseline` → not solvable → skip). By design, not a defect.

**Not a regression:** 15 of 16 `page_error` failures ran the pre-hardening code; the
hardened build shows the identical signature. H1–H5 behaved exactly as designed
(fail-closed, ≤ 2 paid tasks, credit freed, no retry without a live challenge).

## 3. Root cause

arena.ai gives a captcha-gated generation **≈ 57 s** to clear the challenge; after that
it aborts the job with “Something went wrong while generating” and removes the dialog.
2Captcha processing latency in this batch was **45–65 s** (token at 45–56 s when it
arrived at all). The two are a race:

* token ≤ ~55 s → injected before the wall → **solved** (6/22 auto wins ≈ 27 %);
* token > ~57 s → job already dead, dialog already gone → **page_error** (16/22).

Manual always wins because a human checkbox click resolves reCAPTCHA in **seconds**
(26–40 s sessions include user reaction time). The bot cannot win a race it starts
~50 s into, with a wall 57 s out, unless the provider is unusually fast.

Nothing in the solve path is broken; the code starts the paid task at dialog detection
(the earliest moment the sitekey exists), polls every 5 s, and fails closed with the
exact budget RULE 20 prescribes.

## 4. Secondary defects found while diagnosing

* **S-1 — recorder sanitizer over-redacts evidence fields.** `sanitize._SECRET_KEY`
  matches any key *containing* `token|response|…`, so `token_at_ms` (int),
  `dialog_at_token` (enum), `token_sec`, `token_fp` were all written as `[REDACTED]` —
  precisely the fields needed to distinguish token-timing races from other causes.
  Fix: for secret-named keys, redact only credential-shaped values (long or opaque
  strings); ints/floats/short statuses pass. One legacy test pinned the over-broad
  behavior with a synthetic 6-char value and was updated to a realistic credential shape.
* **S-2 — failure reason drops the site's own words.** A page error aborting the poll
  produced `page_error: no solution token` while the actual matched text
  (`Something went wrong…`) sat in `outcome.page_error`. Fix: the reason now carries the
  site text (prefix `Page error: ` stripped), e.g.
  `page_error: Something went wrong. Please try again.` — so manifests, stats and the
  analyzer tell the whole story without a second field.
* **S-3 — 5 s detection granularity (accepted, not fixed).** A fatal page error is
  observed at the next poll (≤ 5 s late). No change: tightening the poll interval does
  not change the win/loss outcome (it is set by token arrival vs the wall) and only adds
  2Captcha API traffic.

## 5. Fix options for the race itself

* **A — one automatic job re-run on a deadline kill.** Signature: captcha settle ends
  `page_error` with **no token delivered** (the site killed the job while the task was
  still processing). Re-run the job once (fresh encounter → fresh paid task → independent
  latency draw). Expected effect on this batch: ~11 of 16 failures flip to success
  (P(win) ≈ 27 % per draw). Costs per flipped job: **one more paid 2Captcha task** (RULE 20
  per-encounter cap respected — a re-run is a new encounter) **and one more site generation
  credit**. Not implemented yet: it is a job-queue behavior change with a real cost model
  — owner decision needed (recommended: opt-in setting, default off).
* **B — poll every 2.5 s instead of 5 s.** Rejected: shaves only detection latency; the
  wall is hit by token *arrival*, not by how fast we notice it.
* **C — 2Captcha latency.** Provider-side (45–65 s observed; no standard-plan API lever
  such as a priority queue). External factor — monitor; if it trends down the race fades
  on its own.

## 6. Changes in this pass

1. `sanitize.py` S-1 fix + updated/added unit tests.
2. `solver.py` S-2 reason-text fix + test assertion (site text survives into `outcome.reason`).
3. `tools/analyze_captcha_recording.py` robust against legacy redacted fields
   (`[REDACTED]` instead of `token_at_ms` no longer crashes; marked in output).
4. `.gitignore`: `config/captcha_recordings/` re-ignored (recordings hold user page
   content and must not travel to the shared repo again).

## 7. Verification

* New/updated unit tests for S-1, S-2 and the analyzer redaction path (tests-first,
  RED → GREEN).
* Full suite + `verify_quality.py --changed --allow-legacy`.
* Next recorded batch (fixed build) must show real `token@Nms` / `dialog_at=…` values in
  the analyzer output — the evidence gap is closed.
* If Option A is approved: design note for the re-run hook + cost guard tests.
