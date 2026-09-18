# Revival round 6: trigger on spinner loss, not only on captcha settle

Date: 2026-09-18 (follows `2026-09-18-captcha-delivery-recovery/`).
Branch: `arena/01a0b3ea-process-images-in-areana`.
User report: with the round-5 code, a run with NO captcha dialog still ended
in `Wait New Output: failed — Timeout after 180000ms` (submit 12:08:57,
spinner 12:09:01→12:10:01, page showing an error/empty state, then dead wait).

## 1. Diagnosis

Round 5 arms revival exclusively from `note_settle()` — a captcha must have
been visible-and-cleared. A generation that dies any other way (transient
backend failure, unmatched error toast the fast-fail patterns don't know,
silent rate-limit) burns the full budget exactly as before: the revival gate
sees `settled_at=None` and stands down on every poll.

The observable death signature is identical with or without captcha:
spinner was visible, then lost, no new pixels arrive. Keying the trigger on
that signature instead of on the settle stamp covers both worlds. Safety
comes from latching: the trigger requires the spinner to have been SEEN at
least once during the wait, so slow starts (spinner not up yet) can never
fire; any new pixel or spinner sighting stands both triggers down, so a live
generation — even a JOB-ID-mismatched one — is never resubmitted over.

Out of scope: fast-fail patterns for the unknown error text (need the exact
text from the page; asked the user to report it if it recurs).

## 2. Design

`app/services/captcha/recovery.py` only (plus tests + this doc + one SOR
clause — no legacy touch at all):

- `ResumePolicy` gains `spinner_seen: bool = False` (latched) and
  `dead_since: Optional[float] = None` (start of the current dead run).
- `_note_activity(policy, diag, now)` (new, ~9 LOC): spinner sighting latches
  `spinner_seen`; any spinner OR `allNew > 0` clears `dead_since` AND
  `settled_at` (alive → stand down); a dead poll with the latch set starts
  `dead_since` when empty.
- `_revive_reason(policy, now) -> str` (replaces `_settle_due` +
  `_generation_dead`): `"…"` label of the matured trigger or `""` —
  settle trigger unchanged (20 s past stamp), loss trigger =
  `spinner_seen and dead_since and 20 s elapsed`.
- `_maybe_resume`: budget/cancel guards, then fire on a non-empty reason;
  `_resubmit(ctrl, policy, reason)` logs WHICH trigger fired
  (`Captcha settled but the generation died…` vs
  `Generation stalled (spinner lost, no output)…`).
- Worst case stays what round 5 accepted: one extra generation attempt per
  wait, loudly logged, same JOB-ID so a late original is still accepted.

**Rejected:** firing on dead polls without the spinner latch (would resubmit
healthy slow starts); extending the wait deadline on resubmit (loop owns the
deadline; the fresh generation uses the remaining budget, strictly better
than a certain timeout).

## 3. RULE 18 recheck (changed code)

- `recovery.py`: +2 dataclass fields, −2 helpers +2 helpers (all 4–13 LOC,
  ≤3 params); file stays ~150 lines.
- No other production file touched. No new modules.

## 4. Verification

- pytest: **302 passed** (all 13 pre-existing recovery tests unchanged-green —
  settle trigger preserved; +3: loss fires with the stalled reason, flicker
  re-arms, settle→resume→die fires via loss).
- node `test:js`: **92/92** (untouched).
- `tools/verify_quality.py --changed --allow-legacy`: **PASSED, 0 fails**;
  radon new code max B(7); `recovery.py` 89% line / **100% branch**, zero
  missing arcs (only `except: pass` scaffolding uncovered).
