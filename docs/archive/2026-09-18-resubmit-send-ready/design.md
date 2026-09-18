# Round 7 — resubmit Send + in-thread error fast-fail

## Evidence (user log 12:36–12:39 + screenshot, 2026-09-18)

4 tabs, all identical: token injected (`fields=1, cb=called client:0 via
grecaptcha-cfg`), "token accepted" after 61–101 s, dialog never re-appeared →
**the token genuinely worked**; the generation then died page-side. Page shows
(an in-thread bubble, not a toast):

> Something went wrong while generating the response. Please try again.
> Trace ID: 5132d45a-77b6  … ✦ Clear

Revival fired on all 4 tabs: re-insert ok (`Inserted len 4213`) →
`Resubmit Send: send not found (FAILED)` → job burned the full 180 s and
timed out. The screenshot composer is EMPTY despite insert-ok.

## Diagnosis — one cause explains insert-ok + empty composer + send-missing

1. **Blind insert.** `JS_INSERT_PROMPT` fills the FIRST matching textarea with
   NO visibility check — while `JS_FIND_TEXTAREA` in the same file HAS an
   `offsetParent` check. The error-state DOM provides a hidden first match
   (collapsed feedback form / second composer / detached node): we fill THAT
   (`len 4213` ok), the visible composer stays empty, Send stays disabled →
   `JS_CLICK_SEND` (visible+enabled required) reports `send not found`.
2. **Single-shot Send.** No wait for React to enable the button after the
   synthetic `input` event (only ~2–3 CDP round-trips between insert and
   click), no terminal-state diagnostics (missing vs hidden vs disabled).
3. **Error scan blind to in-thread bubbles.** `_poll_output_diag` scans every
   poll and the `something\s+went\s+wrong` pattern EXISTS — but
   `build_error_scan_js` only covers toast/alert roles. Arena's error is an
   inline bubble → no match → 180 s burn instead of fast fail.
4. **Gap: resubmit never re-attaches the image.** `ResumePolicy` carries the
   prompt only; the error state may have dropped the attachment, in which
   case even a working Send submits text-only (wrong output).

`_verify_gone` ("token accepted") is NOT the bug: the dialog genuinely closed
via our invoked callback and never returned. A rejected token keeps the
dialog up → `not_accepted`. The failure is downstream (dead generation +
failed resubmit).

## Fixes

**A. Visible-textarea insert** (`app/browser/cdp_arena.py`): `JS_INSERT_PROMPT`
picks the first VISIBLE match across the same 3 selectors; distinct errors
`textarea not found` (no match at all) vs `textarea hidden` (matches exist,
none laid out).

**B. Send-ready resubmit** (`cdp_arena.py` + `recovery.py`): new `JS_SEND_STATE`
probe → `{found, visible, enabled}`; new ctrl method
`submit_when_ready(timeout_sec)` polls it every 0.5 s, clicks the moment Send
is visible+enabled, else returns the terminal state
(`send not found` / `send hidden` / `send disabled`) for the log. `submit()`
unchanged (main flow). `_resubmit` prefers `submit_when_ready` with
`hasattr` fallback to `submit()` (foreign ctrls, RULE 9).

**C. In-thread error fast-fail** (`app/utils/page_errors.py`):
`build_error_scan_js` gains a Trace-ID collector — arena error bubbles always
carry `Trace ID: …` (screenshot-proven signature); scan divs (capped, first
hits) for `/trace\s*id\s*:/i` and append their text to the corpus. Plus a
`trace\s*id` pattern (belt & suspenders). Baseline/stale semantics unchanged:
a previous job's banner is stale-ignored, a fresh one aborts with the exact
page text.

**D. Re-attach on resubmit** (`recovery.py` + `single_job_runner.py`):
`ResumePolicy.image_path` (default `None`, set post-arm by `_arm_revival`
from `ctx.img.absolute_path` — `arm_resume` signature UNCHANGED, RULE 16).
`_resubmit` runs `_ensure_attachment` first: `verify_attachment(basename)` →
re-`attach_image` when missing; fail-open when the ctrl lacks the methods or
no path is armed.

## Rejected alternatives

- Clicking the banner's ✦ Clear: unknown effect (may clear thread/attachment);
  verify composer-usability instead and report states.
- Treating a page error inside verify-grace as `not_accepted`: diverts to the
  manual-wait overlay — strictly worse than revival attempting recovery.
- Moving composer probes to standalone `.js` files: scope creep; node tests
  extract the REAL consts from `cdp_arena.py` instead (below).

## RULE 18 recheck (design-time)

- `JS_SEND_STATE` ~14 lines JS; `submit_when_ready` split into poll helper +
  clicker (each ≤ ~12 lines, `# ideal-size` noted); `_resubmit` splits
  `_ensure_attachment`; policy +1 field; `arm_resume` signature unchanged.
- No new Bridge methods; browser/services layers only.

## Verification

- pytest: `test_page_errors.py` (exact screenshot text; `trace id` pattern;
  stale-baseline ignore); `test_captcha_recovery.py` (re-attach when missing,
  skip when present, `submit()` fallback, no-path fail-open);
  `tests/test_cdp_arena_submit.py` (fake cdp: immediate / delayed-enable /
  never → terminal states; insert uses visible textarea).
- node Tier A `tests/js/test_composer_probes.mjs`: regex-extract the REAL
  `JS_INSERT_PROMPT`/`JS_SEND_STATE` consts from `cdp_arena.py`, run against a
  stub document (hidden-first textarea picked correctly; state mapping).
- Full pytest + node + quality gate + radon (new code ≤ B).
- Live: resubmit Send succeeds; fresh in-thread errors abort fast with page
  text; no 180 s burns. Open question for logs: ✦ Clear semantics if Send
  never enables.
