# Summary — captcha penalty never lands on the finished cooldown

Date: 2026-09-17 · Branch: `arena/01a0a9cf-process-images-in-areana`

## Problem

User: a detected captcha (🛡️(x1,+15m) in the log) did not lengthen the
finished job's cooldown — the URL row still showed the classic 5 min.

## Cause

The record → persist → finish → display chain was proven airtight (code +
tests), so the row showed ANOTHER tab's 5:00: greedy URL matching ties across
same-site pooled tabs and the first twin in snapshot order wins. The job tab's
real 20:00 sat unclaimed (pool panel only). Full forensics: `solution.md` §1-8.

## Fix (this change)

- `note_captcha_event` choke point (record + guarded log + persist + emit).
- Sticky URL-row → run-tab binding (`UrlRow.link_tab`, set on both paths,
  claimed first in `assignPoolPages` / `matchPoolPage`).
- Captcha wait + record at submit/download boundaries (both paths).
- Finish log breakdown (`total = base + captcha xN`); 🛡️ only on success.
- Reset preserves the running job's captcha debt; record-on-BUSY tested.

## Files

`app/services/cooldown_service.py`, `app/services/single_job_runner.py`,
`app/services/multi_page_dispatcher.py`, `app/core/models.py`,
`app/ui/bridge.py`, `app/ui/web/js/panels/url-list.js`,
`tests/test_cooldown_service.py`, `tests/test_captcha_boundaries.py` (new),
`tests/js/test_url_cooldown.mjs`.

## Verification

- pytest 220 passed (baseline 198 + 22 new; failing-first per RULE 8).
- node 40 passed (`test:js` suite incl. 5 new sticky tests).
- radon: all new/changed functions A/B, CC ≤ 9, params ≤ 4, nesting ≤ 3.
- coverage: `cooldown_service` 80%, `models` 82% (single_job_runner 41%,
  dispatcher 34% — pre-existing debt, all touched lines covered).

## RULE 18 recheck (§10)

- New functions 4–24 lines (`_settle_boundary_captcha` 24, CC 9 — under the
  RULE 16 LOC ≤ 30 / CC ≤ 10 hard gates; split further would scatter one
  straight-line flow).
- No new modules (1 new test file only); module file counts unchanged.
- `bridge.py` net +12 (record blocks −16, method +24, calls +4); hotspot
  stays pre-existing, not grown in kind.
- `cooldown_service.py` +~90 (one cohesive feature: note/wait/log-capture);
  kept whole per RULE 19 (complexity fine, split would be dishonest).
